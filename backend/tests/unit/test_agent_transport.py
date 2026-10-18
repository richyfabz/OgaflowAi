import json

import httpx
import pytest
from app.agent.bimpe_client import ToolTransport
from app.agent.session_context import BoundaryError, Invocation
from app.agent.tools import TOOL_DEFINITIONS
from app.schemas.agent_integration import Envelope, validate_data
from pydantic import SecretStr, ValidationError


def success():
    return {
        "run_id": "RUN-test",
        "action_id": "ACT-test",
        "status": "SUCCEEDED",
        "data": {
            "customer_id": "CUS-test",
            "name": "Synthetic",
            "preferred_language": "en",
        },
        "reason_code": None,
        "human_review_required": False,
        "replayed": False,
        "next_action_allowed": True,
    }


def invoke(handler):
    with httpx.Client(
        base_url="http://local.test",
        transport=httpx.MockTransport(handler),
        trust_env=False,
    ) as client:
        return ToolTransport(client, SecretStr("synthetic-only")).invoke(
            Invocation("retained-handle", "identify_customer", "{}")
        )


@pytest.mark.parametrize("failure", ["timeout", 503, 504])
def test_one_retry_preserves_identity_body_and_credentials(failure):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic", request=request)
            return httpx.Response(failure)
        return httpx.Response(200, json=success())

    assert invoke(handler).status == "SUCCEEDED"
    assert len(requests) == 2
    assert requests[0].headers == requests[1].headers
    assert requests[0].content == requests[1].content == b"{}"
    assert requests[0].headers["X-OgaFlow-Invocation"] == "retained-handle"


def test_transport_stops_after_two_failed_attempts():
    requests = []

    def handler(request):
        requests.append(request)
        raise httpx.ConnectError("DO-NOT-LOG", request=request)

    with pytest.raises(BoundaryError, match="TOOL_TRANSPORT_UNAVAILABLE"):
        invoke(handler)
    assert len(requests) == 2


@pytest.mark.parametrize("status", [301, 401, 403, 409, 422, 429, 500, 502])
def test_no_redirect_or_independent_retry_on_other_http_failures(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://untrusted.test"})

    with pytest.raises(BoundaryError, match="TOOL_HTTP_FAILURE"):
        invoke(handler)
    assert len(requests) == 1


def test_http_200_business_failure_is_preserved_without_retry():
    body = success()
    body.update(
        status="FAILED",
        data={"escalation_id": "ESC-test"},
        reason_code="NO_OPEN_ORDER",
        human_review_required=True,
        next_action_allowed=False,
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=body)

    result = invoke(handler)
    assert result.model_dump() == body
    assert len(requests) == 1


@pytest.mark.parametrize("field", list(success()))
def test_missing_envelope_fields_are_rejected(field):
    body = success()
    del body[field]
    with pytest.raises(BoundaryError, match="INVALID_TOOL_RESULT"):
        invoke(lambda request: httpx.Response(200, json=body))


@pytest.mark.parametrize(
    "patch",
    [
        {"status": "UNKNOWN"},
        {"human_review_required": "false"},
        {"replayed": 0},
        {"next_action_allowed": "true"},
        {"reason_code": "ERROR"},
        {"data": {"customer_id": "CUS-test"}},
        {"extra": "not-allowed"},
    ],
)
def test_malformed_results_stop(patch):
    body = success() | patch
    with pytest.raises(BoundaryError, match="INVALID_TOOL_RESULT"):
        invoke(lambda request: httpx.Response(200, json=body))


def test_failure_cannot_authorize_continuation():
    body = success() | {
        "status": "FAILED",
        "reason_code": "NO_OPEN_ORDER",
        "human_review_required": True,
        "data": {"escalation_id": "ESC-test"},
    }
    with pytest.raises(ValidationError):
        Envelope.model_validate(body)


def test_payment_amount_requires_integer_kobo():
    result = Envelope.model_validate(
        success()
        | {
            "data": {
                "payments": [
                    {
                        "id": "PAY-test",
                        "order_id": None,
                        "amount_minor": "100",
                        "currency": "NGN",
                        "status": "SUCCESS",
                    }
                ]
            }
        }
    )
    with pytest.raises(ValidationError):
        validate_data("find_payments", result)


def test_tool_schemas_have_no_runtime_identity_fields():
    assert {tool["name"] for tool in TOOL_DEFINITIONS} == {
        "identify_customer",
        "get_open_orders",
        "get_order",
        "find_payments",
    }
    for tool in TOOL_DEFINITIONS:
        assert not tool["parameters"]["additionalProperties"]
        assert set(tool["parameters"]["properties"]) <= {"order_id"}
        assert "idempotency" not in json.dumps(tool)
