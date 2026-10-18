"""Operator-owned, process-local context for compatibility tests, not platform binding.

No public provisioning API. Restart/expiry loses handles and fails closed; this is
intentionally unsuitable for multiple workers or durable conversation recovery.
"""

import json
import logging
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic
from uuid import uuid4

from psycopg import Error as DatabaseError
from pydantic import ValidationError

from app.agent.policies import MAX_HTTP_ATTEMPTS, MAX_LOGICAL_CALLS
from app.agent.tools import ARGUMENT_MODELS
from app.schemas.agent_integration import Envelope, Result, validate_data

logger = logging.getLogger(__name__)


class BoundaryError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class Invocation:
    handle: str
    tool: str
    arguments_json: str


@dataclass
class _Attempt:
    phone: str
    customer_id: str
    expires_at: float
    run_id: str | None = None
    stopped: bool = False
    calls: int = 0
    pending: str | None = None
    orders: set[str] = field(default_factory=set)


@dataclass
class _Delivery:
    attempt: _Attempt
    ticket: Invocation
    attempts: int = 0
    result: Envelope | None = None


class SessionRegistry:
    def __init__(self):
        self._lock = RLock()
        self._sessions: dict[str, _Attempt] = {}
        self._deliveries: dict[str, _Delivery] = {}

    def bind(self, *, phone: str, customer_id: str) -> str:
        """Trusted operator code only. Never call with customer-authored identity."""
        with self._lock:
            handle = uuid4().hex
            self._sessions[handle] = _Attempt(phone, customer_id, monotonic() + 900)
            return handle

    def revoke(self, session: str):
        with self._lock:
            attempt = self._sessions.pop(session, None)
            if attempt is not None:
                attempt.stopped = True
                self._deliveries = {
                    key: item
                    for key, item in self._deliveries.items()
                    if item.attempt is not attempt
                }

    @staticmethod
    def _active(attempt):
        if attempt.expires_at <= monotonic():
            raise BoundaryError("CONTEXT_EXPIRED")

    def prepare(self, session: str, tool: str, arguments: dict) -> Invocation:
        """Runtime issues ONE ticket per logical call and retains it for retries."""
        if tool not in ARGUMENT_MODELS:
            raise BoundaryError("TOOL_DISABLED", 403)
        try:
            arguments_json = (
                ARGUMENT_MODELS[tool].model_validate(arguments).model_dump_json()
            )
        except ValidationError:
            raise BoundaryError("INVALID_TOOL_ARGUMENTS", 422) from None
        with self._lock:
            attempt = self._sessions.get(session)
            if attempt is None:
                raise BoundaryError("CONTEXT_NOT_FOUND", 403)
            self._active(attempt)
            if attempt.stopped:
                raise BoundaryError("ATTEMPT_STOPPED")
            if attempt.pending is not None:
                raise BoundaryError("INVOCATION_PENDING")
            if attempt.calls >= MAX_LOGICAL_CALLS:
                raise BoundaryError("TOOL_BUDGET_EXHAUSTED")
            if (tool == "identify_customer") != (attempt.run_id is None):
                raise BoundaryError("INVALID_TOOL_SEQUENCE")
            if tool == "get_order" and arguments["order_id"] not in attempt.orders:
                raise BoundaryError("ORDER_NOT_IN_CONTEXT", 403)
            ticket = Invocation(uuid4().hex, tool, arguments_json)
            attempt.calls += 1
            attempt.pending = ticket.handle
            self._deliveries[ticket.handle] = _Delivery(attempt, ticket)
            return ticket

    def execute(self, handle: str, tool: str, arguments: dict, service) -> Envelope:
        # Serial execution is adequate for the local single-process harness.
        with self._lock:
            delivery = self._deliveries.get(handle)
            if delivery is None:
                raise BoundaryError("INVOCATION_NOT_FOUND", 403)
            attempt, ticket = delivery.attempt, delivery.ticket
            self._active(attempt)
            if tool != ticket.tool or arguments != json.loads(ticket.arguments_json):
                raise BoundaryError("INVOCATION_CONFLICT", 409)
            if delivery.result is not None:
                replay = delivery.result.model_copy(deep=True)
                replay.replayed = True
                if attempt.stopped:
                    replay.next_action_allowed = False
                return replay
            if attempt.stopped or delivery.attempts >= MAX_HTTP_ATTEMPTS:
                raise BoundaryError("ATTEMPT_STOPPED")
            delivery.attempts += 1
            key = "agent:" + ticket.handle
            try:
                if tool == "identify_customer":
                    raw = service.start_run(attempt.phone, key)
                else:
                    raw = getattr(service, tool)(attempt.run_id, key, **arguments)
                result = Result.model_validate(raw.model_dump(mode="json"))
                data = validate_data(tool, result)
                if attempt.run_id is not None and result.run_id != attempt.run_id:
                    raise ValueError("Run identity mismatch")
                if result.status == "SUCCEEDED":
                    run = service.get_run(result.run_id)
                    if run["customer_id"] != attempt.customer_id:
                        raise ValueError("Customer identity mismatch")
                    if (
                        tool == "identify_customer"
                        and data.customer_id != attempt.customer_id
                    ):
                        raise ValueError("Customer identity mismatch")
                    if tool == "get_order" and (
                        data.order.id != arguments["order_id"]
                        or data.order.customer_id != attempt.customer_id
                    ):
                        raise ValueError("Order identity mismatch")
                    if tool == "get_open_orders":
                        attempt.orders = {order.id for order in data.orders}
                    allowed = (
                        run["status"] == "RUNNING" and attempt.calls < MAX_LOGICAL_CALLS
                    )
                else:
                    allowed = False
                envelope = Envelope(**result.model_dump(), next_action_allowed=allowed)
            except (ValidationError, ValueError, KeyError, TypeError):
                attempt.stopped = True
                logger.warning("agent_boundary result_invalid tool=%s", tool)
                raise BoundaryError("INVALID_TOOL_RESULT", 502) from None
            except (OSError, DatabaseError):
                # One transport retry may recover a committed result using the SAME key.
                if delivery.attempts >= MAX_HTTP_ATTEMPTS:
                    attempt.stopped = True
                logger.warning("agent_boundary backend_unavailable tool=%s", tool)
                raise BoundaryError("TOOL_BACKEND_UNAVAILABLE", 503) from None
            except Exception:  # noqa: BLE001 - redact unknown backend failures and stop.
                attempt.stopped = True
                logger.error("agent_boundary unexpected_failure tool=%s", tool)
                raise BoundaryError("TOOL_INTERNAL_FAILURE", 500) from None
            attempt.run_id = result.run_id
            attempt.pending = None
            attempt.stopped = not allowed
            delivery.result = envelope.model_copy(deep=True)
            logger.info(
                "agent_boundary tool=%s status=%s replayed=%s run=%s action=%s",
                tool,
                result.status,
                result.replayed,
                result.run_id,
                result.action_id,
            )
            return envelope
