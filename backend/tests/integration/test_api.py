import psycopg
import pytest
from app.api.operations import get_service
from app.main import app
from app.repositories.operations import OperationsRepository
from fastapi.testclient import TestClient


@pytest.fixture
def client(service):
    app.dependency_overrides[get_service] = lambda: service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_api_golden_workflow_and_replay(client):
    start = client.post(
        "/runs", json={"phone": "DEMO-PHONE-001", "idempotency_key": "start"}
    )
    assert start.status_code == 200
    run = start.json()["run_id"]
    for tool in [
        "match_payment",
        "check_inventory",
        "reserve_inventory",
        "confirm_order",
    ]:
        response = client.post(
            "/tools/" + tool,
            json={"run_id": run, "idempotency_key": tool, "order_id": "OGA-1042"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "SUCCEEDED", response.text
    replay = client.post(
        "/tools/confirm_order",
        json={
            "run_id": run,
            "idempotency_key": "confirm_order",
            "order_id": "OGA-1042",
        },
    )
    assert replay.json()["replayed"]
    trace = client.get("/runs/" + run)
    assert trace.status_code == 200
    assert len(trace.json()["actions"]) == 5


def test_api_failure_contract(client):
    run = client.post(
        "/runs", json={"phone": "DEMO-PHONE-002", "idempotency_key": "start"}
    ).json()["run_id"]
    response = client.post(
        "/tools/match_payment",
        json={"run_id": run, "idempotency_key": "match", "order_id": "OGA-1051"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "FAILED" and body["reason_code"] == "AMOUNT_MISMATCH"
    assert body["human_review_required"] and body["data"]["escalation_id"]


def test_api_rejects_supplied_business_truth(client):
    response = client.post(
        "/tools/confirm_order",
        json={
            "run_id": "RUN-X",
            "idempotency_key": "confirm",
            "order_id": "OGA-1042",
            "verified": True,
        },
    )
    assert response.status_code == 422


def test_api_database_failure_does_not_leak_details(client, monkeypatch):
    def broken(*args):
        raise psycopg.OperationalError("password=SECRET private-database.example")

    monkeypatch.setattr(OperationsRepository, "identify_customer", broken)
    response = client.post(
        "/runs", json={"phone": "DEMO-PHONE-001", "idempotency_key": "start"}
    )
    assert response.status_code == 503
    assert response.json() == {"code": "DATABASE_UNAVAILABLE"}
    assert "SECRET" not in response.text


def test_missing_run_and_key_conflict(client):
    assert client.get("/runs/UNKNOWN").status_code == 404
    client.post("/runs", json={"phone": "DEMO-PHONE-001", "idempotency_key": "start"})
    response = client.post(
        "/runs", json={"phone": "DEMO-PHONE-002", "idempotency_key": "start"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "IDEMPOTENCY_KEY_CONFLICT"
