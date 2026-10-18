"""Transactional orchestration. Business SQL is confined to repositories."""

import hashlib
import json

from app.core.exceptions import DomainError
from app.models.enums import OrderStatus, VerificationSource
from app.models.results import ToolResult
from app.repositories.unit_of_work import UnitOfWork
from app.services.order_state import check_reservation, transition_order
from app.services.payment_matching import match_payment
from app.services.verification import PaymentVerifier, UnavailablePaymentVerifier


def request_hash(tool: str, run_id: str | None, arguments: dict) -> str:
    value = json.dumps([tool, run_id, arguments], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


class OperationsService:
    """Apply restricted operations with persisted retries, audit and escalation."""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        allow_demo=False,
        verifier: PaymentVerifier | None = None,
    ):
        self.uow = uow
        self.allow_demo = allow_demo
        self.verifier = verifier or UnavailablePaymentVerifier()

    def _replay(self, repo, key, fingerprint):
        repo.lock_key(key)
        existing = repo.action_by_key(key)
        if existing is None:
            return None
        metadata = existing["result_metadata"]
        if metadata.get("request_hash") != fingerprint:
            raise DomainError("IDEMPOTENCY_KEY_CONFLICT")
        result = ToolResult(**metadata["result"])
        return result.model_copy(update={"action_id": existing["id"], "replayed": True})

    def _record(self, repo, tool, key, fingerprint, result):
        metadata = {
            "request_hash": fingerprint,
            "result": result.model_dump(mode="json"),
        }
        result.action_id = repo.record_action(
            result.run_id, tool, key, metadata, result.reason_code
        )
        return result

    def start_run(self, phone: str, key: str) -> ToolResult:
        fingerprint = request_hash("identify_customer", None, {"phone": phone})
        with self.uow.transaction() as repo:
            replay = self._replay(repo, key, fingerprint)
            if replay:
                return replay
            customer_id = repo.identify_customer(phone)
            run_id = repo.create_run(customer_id)
            if customer_id is None:
                escalation_id = repo.create_escalation(
                    run_id,
                    None,
                    "CUSTOMER_NOT_FOUND",
                    "Customer identification requires human review.",
                )
                repo.escalate_run(run_id)
                result = ToolResult(
                    run_id=run_id,
                    status="FAILED",
                    reason_code="CUSTOMER_NOT_FOUND",
                    human_review_required=True,
                    data={"escalation_id": escalation_id},
                )
            else:
                customer = repo.customer(customer_id)
                result = ToolResult(
                    run_id=run_id,
                    status="SUCCEEDED",
                    data={
                        "customer_id": customer.id,
                        "name": customer.name,
                        "preferred_language": customer.preferred_language,
                    },
                )
            return self._record(repo, "identify_customer", key, fingerprint, result)

    def _execute(
        self,
        tool,
        run_id,
        key,
        arguments,
        operation,
        *,
        order_id=None,
        payment_id=None,
        mutation=False,
    ):
        fingerprint = request_hash(tool, run_id, arguments)
        with self.uow.transaction() as repo:
            replay = self._replay(repo, key, fingerprint)
            if replay:
                return replay
            run = repo.run(run_id)
            order = None
            try:
                if payment_id is not None:
                    order_id = repo.payment_order_id(payment_id)
                if order_id is not None:
                    order = repo.order(order_id)
                    if order.customer_id != run["customer_id"]:
                        order = None
                        raise DomainError("ORDER_NOT_FOUND")
                if mutation and run["status"] != "RUNNING":
                    raise DomainError("RUN_NOT_ACTIVE")
                if run["customer_id"] is None:
                    raise DomainError("CUSTOMER_NOT_FOUND")
                with repo.savepoint():
                    data = operation(repo, run, order)
                result = ToolResult(
                    run_id=run_id,
                    status="SUCCEEDED",
                    data=data,
                    human_review_required=tool == "create_escalation",
                )
            except DomainError as error:
                data = {}
                review = error.code != "RUN_NOT_ACTIVE"
                if review:
                    # Locks were acquired before the savepoint; rejected mutations are gone.
                    if order is not None and order.status not in {
                        OrderStatus.FULFILMENT,
                        OrderStatus.ESCALATED,
                    }:
                        repo.store_order(transition_order(order, OrderStatus.ESCALATED))
                    escalation_id = repo.create_escalation(
                        run_id,
                        order.id if order else None,
                        error.code,
                        "Automation stopped; review the recorded reason and related business records.",
                    )
                    repo.escalate_run(run_id)
                    data["escalation_id"] = escalation_id
                result = ToolResult(
                    run_id=run_id,
                    status="FAILED",
                    data=data,
                    reason_code=error.code,
                    human_review_required=review,
                )
            return self._record(repo, tool, key, fingerprint, result)

    def get_open_orders(self, run_id: str, key: str) -> ToolResult:
        def operation(repo, run, order):
            orders = repo.open_orders(run["customer_id"])
            if not orders:
                raise DomainError("NO_OPEN_ORDER")
            if len(orders) > 1:
                raise DomainError("MULTIPLE_OPEN_ORDERS")
            return {"orders": orders}

        return self._execute("get_open_orders", run_id, key, {}, operation)

    def get_order(self, run_id: str, key: str, order_id: str) -> ToolResult:
        return self._execute(
            "get_order",
            run_id,
            key,
            {"order_id": order_id},
            lambda repo, run, order: {"order": order.model_dump(mode="json")},
            order_id=order_id,
        )

    def find_payments(self, run_id: str, key: str) -> ToolResult:
        def operation(repo, run, order):
            payments = repo.payments(run["customer_id"])
            return {
                "payments": [
                    {
                        "id": p.id,
                        "order_id": p.order_id,
                        "amount_minor": p.amount_minor,
                        "currency": p.currency,
                        "status": p.status.value,
                    }
                    for p in payments
                ]
            }

        return self._execute("find_payments", run_id, key, {}, operation)

    def verify_payment(self, run_id: str, key: str, payment_id: str) -> ToolResult:
        def operation(repo, run, order):
            candidates = repo.payments(run["customer_id"])
            payment = next((p for p in candidates if p.id == payment_id), None)
            if payment is None:
                raise DomainError("PAYMENT_NOT_FOUND")
            if payment.order_id is None:
                raise DomainError("UNLINKED_PAYMENT")
            if order is None or payment.order_id != order.id:
                raise DomainError("PAYMENT_CHANGED")
            verified = self.verifier.verify(payment)
            immutable = (
                "id",
                "customer_id",
                "order_id",
                "amount_minor",
                "currency",
                "provider",
                "reference",
            )
            if any(
                getattr(payment, name) != getattr(verified, name) for name in immutable
            ):
                raise DomainError("VERIFICATION_IDENTITY_MISMATCH")
            if verified.verified_at is None:
                raise DomainError("PAYMENT_UNVERIFIED")
            if (
                verified.verification_source == VerificationSource.DEMO
                and not self.allow_demo
            ):
                raise DomainError("DEMO_PAYMENT_NOT_ALLOWED")
            repo.store_verification(verified)
            return {
                "payment_id": verified.id,
                "verified": True,
                "source": verified.verification_source.value,
            }

        return self._execute(
            "verify_payment",
            run_id,
            key,
            {"payment_id": payment_id},
            operation,
            payment_id=payment_id,
            mutation=True,
        )

    def match_payment(self, run_id: str, key: str, order_id: str) -> ToolResult:
        def operation(repo, run, order):
            payments = repo.payments(run["customer_id"])
            payment = match_payment(order, payments, allow_demo=self.allow_demo)
            if order.status == OrderStatus.AWAITING_PAYMENT:
                order = transition_order(
                    order,
                    OrderStatus.PAYMENT_VERIFIED,
                    payments,
                    allow_demo=self.allow_demo,
                )
                repo.store_order(order)
            else:
                transition_order(
                    order, order.status, payments, allow_demo=self.allow_demo
                )
                if order.verified_payment_id != payment.id:
                    raise DomainError("ILLEGAL_STATE_TRANSITION")
            return {
                "order_id": order.id,
                "payment_id": payment.id,
                "order_status": order.status.value,
            }

        return self._execute(
            "match_payment",
            run_id,
            key,
            {"order_id": order_id},
            operation,
            order_id=order_id,
            mutation=True,
        )

    def check_inventory(self, run_id: str, key: str, order_id: str) -> ToolResult:
        def operation(repo, run, order):
            transition_order(
                order,
                order.status,
                repo.payments(run["customer_id"]),
                allow_demo=self.allow_demo,
            )
            products = repo.products([item.product_id for item in order.items])
            return {"required": check_reservation(order, products), "available": True}

        return self._execute(
            "check_inventory",
            run_id,
            key,
            {"order_id": order_id},
            operation,
            order_id=order_id,
        )

    def reserve_inventory(self, run_id: str, key: str, order_id: str) -> ToolResult:
        def operation(repo, run, order):
            payments = repo.payments(run["customer_id"])
            transition_order(order, order.status, payments, allow_demo=self.allow_demo)
            if order.status in {
                OrderStatus.STOCK_RESERVED,
                OrderStatus.CONFIRMED,
                OrderStatus.FULFILMENT,
            }:
                return {
                    "order_id": order.id,
                    "order_status": order.status.value,
                    "already_applied": True,
                }
            products = repo.products([item.product_id for item in order.items])
            requirements = check_reservation(order, products)
            repo.reserve(order.id, requirements)
            reserved = repo.order(order.id)
            reserved = transition_order(
                reserved,
                OrderStatus.STOCK_RESERVED,
                payments,
                allow_demo=self.allow_demo,
            )
            repo.store_order(reserved)
            return {
                "order_id": order.id,
                "order_status": reserved.status.value,
                "already_applied": False,
            }

        return self._execute(
            "reserve_inventory",
            run_id,
            key,
            {"order_id": order_id},
            operation,
            order_id=order_id,
            mutation=True,
        )

    def confirm_order(self, run_id: str, key: str, order_id: str) -> ToolResult:
        def operation(repo, run, order):
            confirmed = transition_order(
                order,
                OrderStatus.CONFIRMED,
                repo.payments(run["customer_id"]),
                allow_demo=self.allow_demo,
            )
            if confirmed is not order:
                repo.store_order(confirmed)
            return {
                "order_id": order.id,
                "order_status": confirmed.status.value,
                "already_applied": confirmed is order,
            }

        return self._execute(
            "confirm_order",
            run_id,
            key,
            {"order_id": order_id},
            operation,
            order_id=order_id,
            mutation=True,
        )

    def create_escalation(
        self, run_id: str, key: str, order_id: str | None = None
    ) -> ToolResult:
        def operation(repo, run, order):
            reason = "HUMAN_REVIEW_REQUESTED"
            if order and order.status not in {
                OrderStatus.ESCALATED,
                OrderStatus.FULFILMENT,
            }:
                repo.store_order(transition_order(order, OrderStatus.ESCALATED))
            escalation_id = repo.create_escalation(
                run_id, order_id, reason, "Human review requested for this workflow."
            )
            repo.escalate_run(run_id)
            return {"escalation_id": escalation_id, "status": "OPEN"}

        return self._execute(
            "create_escalation",
            run_id,
            key,
            {"order_id": order_id},
            operation,
            order_id=order_id,
        )

    def get_run(self, run_id: str) -> dict:
        with self.uow.transaction() as repo:
            run = repo.run(run_id)
            return {**run, "actions": repo.run_actions(run_id)}
