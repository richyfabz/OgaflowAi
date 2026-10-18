"""Local protocol evidence only; these tests do not contact BimpeAI."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from app.agent.session_context import BoundaryError, SessionRegistry
from app.api.agent_integration import get_registry
from app.api.operations import get_service
from app.core.config import Settings, get_settings
from app.main import app
from fastapi.testclient import TestClient

TOKEN = "synthetic-test-token-not-a-live-credential"


@pytest.fixture
def boundary(service):
    contexts = SessionRegistry()
    settings = Settings(
        _env_file=None, OGAFLOW_AGENT_BOUNDARY_ENABLED=True, OGAFLOW_TOOL_TOKEN=TOKEN
    )
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_registry] = lambda: contexts
    # Security reads configuration directly; patch its accessor, not global app settings.
    from unittest.mock import patch

    with (
        patch("app.core.integration_security.get_settings", return_value=settings),
        TestClient(app) as client,
    ):
        yield client, contexts, settings
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def bind(contexts, phone="DEMO-PHONE-001", customer_id="CUS-001"):
    return contexts.bind(phone=phone, customer_id=customer_id)


def deliver(client, ticket, **kwargs):
    import json

    return client.post(
        "/agent/tools/" + ticket.tool,
        json=json.loads(ticket.arguments_json),
        headers={
            "Authorization": "Bearer " + TOKEN,
            "X-OgaFlow-Invocation": ticket.handle,
        },
        **kwargs,
    )


def identify(boundary):
    client, contexts, _ = boundary
    session = bind(contexts)
    ticket = contexts.prepare(session, "identify_customer", {})
    result = deliver(client, ticket)
    assert result.status_code == 200, result.text
    assert result.json()["data"]["customer_id"] == "CUS-001"
    return session, result.json()["run_id"]


def test_local_lookup_flow_leaves_business_state_unchanged(boundary, database):
    client, contexts, _ = boundary
    session, run = identify(boundary)
    for tool, args in [
        ("get_open_orders", {}),
        ("get_order", {"order_id": "OGA-1042"}),
        ("find_payments", {}),
    ]:
        response = deliver(client, contexts.prepare(session, tool, args))
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "SUCCEEDED"
        assert response.json()["next_action_allowed"]
    with database.connect() as conn:
        assert (
            conn.execute("SELECT status FROM orders WHERE id='OGA-1042'").fetchone()[
                "status"
            ]
            == "AWAITING_PAYMENT"
        )
        assert (
            conn.execute(
                "SELECT available_quantity FROM products WHERE id='PRD-OIL'"
            ).fetchone()["available_quantity"]
            == 12
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM agent_actions WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            == 4
        )


def test_duplicate_delivery_reuses_result_and_audit(boundary, service):
    client, contexts, _ = boundary
    session = bind(contexts)
    ticket = contexts.prepare(session, "identify_customer", {})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: deliver(client, ticket).json(), range(2)))
    assert sorted(item["replayed"] for item in results) == [False, True]
    assert results[0]["action_id"] == results[1]["action_id"]
    assert len(service.get_run(results[0]["run_id"])["actions"]) == 1


@pytest.mark.parametrize("token", [None, "Bearer wrong", "Basic synthetic", "Bearer "])
def test_auth_rejects_missing_or_wrong_credential(boundary, token):
    client, _, _ = boundary
    headers = {} if token is None else {"Authorization": token}
    assert (
        client.post(
            "/agent/tools/identify_customer", json={}, headers=headers
        ).status_code
        == 401
    )


def test_unconfigured_and_disabled_boundary_fail_closed(boundary):
    client, _, settings = boundary
    settings.tool_token = None
    assert client.post("/agent/tools/identify_customer", json={}).status_code == 503
    settings.agent_boundary_enabled = False
    assert client.post("/agent/tools/identify_customer", json={}).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/runs",
        "/tools/get_order",
        "/tools/verify_payment",
        "/tools/match_payment",
        "/tools/check_inventory",
        "/tools/reserve_inventory",
        "/tools/confirm_order",
        "/tools/create_escalation",
    ],
)
def test_legacy_route_cannot_bypass_allowlist(boundary, path):
    client, _, _ = boundary
    assert (
        client.post(
            path, json={}, headers={"Authorization": "Bearer " + TOKEN}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/runs/anything", headers={"Authorization": "Bearer " + TOKEN}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "tool",
    [
        "verify_payment",
        "match_payment",
        "check_inventory",
        "reserve_inventory",
        "confirm_order",
        "create_escalation",
        "sql",
    ],
)
def test_mutations_and_unknown_tools_not_issuable(boundary, tool):
    _, contexts, _ = boundary
    with pytest.raises(BoundaryError, match="TOOL_DISABLED"):
        contexts.prepare(bind(contexts), tool, {})


@pytest.mark.parametrize(
    "key",
    ["phone", "customer_id", "run_id", "idempotency_key", "invocation_id", "verified"],
)
def test_model_cannot_supply_runtime_or_business_truth(boundary, key):
    client, contexts, _ = boundary
    session = bind(contexts)
    with pytest.raises(BoundaryError, match="INVALID_TOOL_ARGUMENTS"):
        contexts.prepare(session, "identify_customer", {key: "fake"})
    ticket = contexts.prepare(session, "identify_customer", {})
    response = client.post(
        "/agent/tools/identify_customer",
        json={key: "fake"},
        headers={
            "Authorization": "Bearer " + TOKEN,
            "X-OgaFlow-Invocation": ticket.handle,
        },
    )
    assert response.status_code == 409


def test_unknown_handle_and_restart_fail_closed(boundary):
    client, contexts, _ = boundary
    ticket = contexts.prepare(bind(contexts), "identify_customer", {})
    app.dependency_overrides[get_registry] = SessionRegistry
    assert deliver(client, ticket).status_code == 403


def test_expiry_and_revocation_fail_closed(boundary, monkeypatch):
    client, contexts, _ = boundary
    session = bind(contexts)
    ticket = contexts.prepare(session, "identify_customer", {})
    with monkeypatch.context() as patch:
        patch.setattr("app.agent.session_context.monotonic", lambda: float("inf"))
        assert deliver(client, ticket).status_code == 409
    contexts.revoke(session)
    assert deliver(client, ticket).status_code == 403


def test_wrong_customer_binding_does_not_return_customer_data(boundary):
    client, contexts, _ = boundary
    ticket = contexts.prepare(
        bind(contexts, customer_id="CUS-002"), "identify_customer", {}
    )
    response = deliver(client, ticket)
    assert response.status_code == 502
    assert "Tunde" not in response.text


def test_order_id_must_be_observed_in_bound_session(boundary):
    _, contexts, _ = boundary
    session, _ = identify(boundary)
    with pytest.raises(BoundaryError, match="ORDER_NOT_IN_CONTEXT"):
        contexts.prepare(session, "get_order", {"order_id": "OGA-1051"})


def test_business_failure_http_200_stops_and_is_replayable(boundary, service):
    client, contexts, _ = boundary
    session = bind(contexts, "DEMO-PHONE-009", "CUS-009")
    deliver(client, contexts.prepare(session, "identify_customer", {}))
    ticket = contexts.prepare(session, "get_open_orders", {})
    response = deliver(client, ticket)
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "FAILED"
    assert result["reason_code"] == "NO_OPEN_ORDER"
    assert result["human_review_required"]
    assert not result["next_action_allowed"]
    assert result["data"]["escalation_id"]
    assert service.get_run(result["run_id"])["status"] == "ESCALATED"
    assert deliver(client, ticket).json()["replayed"]
    with pytest.raises(BoundaryError, match="ATTEMPT_STOPPED"):
        contexts.prepare(session, "find_payments", {})


def test_budget_and_pending_call_enforced(boundary):
    client, contexts, _ = boundary
    session = bind(contexts)
    first = contexts.prepare(session, "identify_customer", {})
    with pytest.raises(BoundaryError, match="INVOCATION_PENDING"):
        contexts.prepare(session, "identify_customer", {})
    deliver(client, first)
    for index in range(11):
        result = deliver(client, contexts.prepare(session, "find_payments", {})).json()
        assert result["next_action_allowed"] == (index < 10)
    with pytest.raises(BoundaryError, match="ATTEMPT_STOPPED"):
        contexts.prepare(session, "find_payments", {})
    assert not deliver(client, first).json()["next_action_allowed"]


def test_lost_response_after_commit_replays_same_backend_key(
    boundary, service, monkeypatch
):
    client, contexts, _ = boundary
    original = service.start_run
    calls = []

    def lost_response(phone, key):
        result = original(phone, key)
        calls.append(key)
        if len(calls) == 1:
            raise OSError("synthetic lost response")
        return result

    monkeypatch.setattr(service, "start_run", lost_response)
    ticket = contexts.prepare(bind(contexts), "identify_customer", {})
    assert deliver(client, ticket).status_code == 503
    result = deliver(client, ticket).json()
    assert result["replayed"]
    assert len(set(calls)) == 1
    assert len(service.get_run(result["run_id"])["actions"]) == 1


def test_invalid_result_stops_without_leaking_payload(
    boundary, service, monkeypatch, caplog
):
    client, contexts, _ = boundary
    original = service.start_run

    def malformed(*args):
        result = original(*args)
        result.data = {"private_secret": "DO-NOT-LOG"}
        return result

    monkeypatch.setattr(service, "start_run", malformed)
    ticket = contexts.prepare(bind(contexts), "identify_customer", {})
    response = deliver(client, ticket)
    assert response.status_code == 502
    assert "DO-NOT-LOG" not in response.text + caplog.text
    assert deliver(client, ticket).status_code == 409


def test_real_local_http_envelope_through_httpx_adapter(boundary, service):
    import httpx
    from app.agent.bimpe_client import ToolTransport
    from pydantic import SecretStr

    client, contexts, _ = boundary
    session = bind(contexts)
    ticket = contexts.prepare(session, "identify_customer", {})
    requests = []

    def callback(request):
        response = client.post(
            request.url.path, content=request.content, headers=dict(request.headers)
        )
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadTimeout("synthetic lost HTTP response", request=request)
        return httpx.Response(response.status_code, content=response.content)

    with httpx.Client(
        base_url="http://local.test",
        transport=httpx.MockTransport(callback),
        trust_env=False,
    ) as http_client:
        result = ToolTransport(http_client, SecretStr(TOKEN)).invoke(ticket)
    assert result.replayed
    assert result.next_action_allowed
    assert len(requests) == 2
    assert len(service.get_run(result.run_id)["actions"]) == 1


def test_tunde_and_amaka_sessions_remain_separate(boundary):
    client, contexts, _ = boundary
    for phone, customer, order in [
        ("DEMO-PHONE-001", "CUS-001", "OGA-1042"),
        ("DEMO-PHONE-002", "CUS-002", "OGA-1051"),
    ]:
        session = bind(contexts, phone, customer)
        assert (
            deliver(client, contexts.prepare(session, "identify_customer", {})).json()[
                "data"
            ]["customer_id"]
            == customer
        )
        result = deliver(
            client, contexts.prepare(session, "get_open_orders", {})
        ).json()
        assert result["data"]["orders"][0]["id"] == order
        other = "OGA-1051" if order == "OGA-1042" else "OGA-1042"
        with pytest.raises(BoundaryError, match="ORDER_NOT_IN_CONTEXT"):
            contexts.prepare(session, "get_order", {"order_id": other})


def test_repeated_backend_failure_is_bounded_and_redacted(
    boundary, service, monkeypatch, caplog
):
    client, contexts, _ = boundary
    calls = []

    def unavailable(*args):
        calls.append(args)
        raise OSError("credential=DO-NOT-LOG")

    monkeypatch.setattr(service, "start_run", unavailable)
    ticket = contexts.prepare(bind(contexts), "identify_customer", {})
    assert [deliver(client, ticket).status_code for _ in range(3)] == [503, 503, 409]
    assert len(calls) == 2
    assert "DO-NOT-LOG" not in caplog.text


def test_mutation_path_rejects_valid_read_ticket(boundary):
    client, contexts, _ = boundary
    ticket = contexts.prepare(bind(contexts), "identify_customer", {})
    for tool in (
        "verify_payment",
        "match_payment",
        "reserve_inventory",
        "confirm_order",
        "create_escalation",
        "check_inventory",
    ):
        response = client.post(
            "/agent/tools/" + tool,
            json={},
            headers={
                "Authorization": "Bearer " + TOKEN,
                "X-OgaFlow-Invocation": ticket.handle,
            },
        )
        assert response.status_code == 409
