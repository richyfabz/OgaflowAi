from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from app.core.exceptions import DomainError
from app.models.domain import Payment
from app.repositories.operations import OperationsRepository
from app.repositories.unit_of_work import UnitOfWork
from app.services.operations import OperationsService


def row(database, statement, params=()):
    with database.connect() as connection:
        return connection.execute(statement, params).fetchone()


def prepare(service, run_id, order_id="OGA-1042"):
    result = service.match_payment(run_id, "match-" + uuid4().hex, order_id)
    assert result.status == "SUCCEEDED", result


def test_repository_reads_seed_and_missing_order(database):
    with UnitOfWork(database).transaction() as repo:
        assert repo.identify_customer("DEMO-PHONE-001") == "CUS-001"
        assert repo.customer("CUS-001").name == "Tunde Adebayo"
        assert repo.order("OGA-1042").total_minor == 8400000
        assert repo.payments("CUS-001")[0].reference == "TRF92839201"
        assert repo.products(["PRD-OIL"])[0].available_quantity == 12
        with pytest.raises(DomainError, match="ORDER_NOT_FOUND"):
            repo.order("UNKNOWN")


def test_complete_persisted_golden_workflow(service, database, run_id):
    assert service.get_open_orders(run_id, "orders").status == "SUCCEEDED"
    assert (
        service.find_payments(run_id, "payments").data["payments"][0]["id"]
        == "PAY-88921"
    )
    assert (
        service.verify_payment(run_id, "verify", "PAY-88921").data["verified"] is True
    )
    prepare(service, run_id)
    assert (
        service.check_inventory(run_id, "stock", "OGA-1042").data["available"] is True
    )
    assert (
        service.reserve_inventory(run_id, "reserve", "OGA-1042").status == "SUCCEEDED"
    )
    assert service.confirm_order(run_id, "confirm", "OGA-1042").status == "SUCCEEDED"
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 9
    )
    assert (
        row(
            database,
            "SELECT reserved_quantity FROM order_items WHERE order_id='OGA-1042'",
        )["reserved_quantity"]
        == 3
    )
    order = row(database, "SELECT * FROM orders WHERE id='OGA-1042'")
    assert order["status"] == "CONFIRMED"
    assert order["verified_payment_id"] == "PAY-88921"
    assert order["stock_reserved_at"] and order["confirmed_at"]
    assert len(service.get_run(run_id)["actions"]) == 8


def test_retries_same_and_new_keys_do_not_repeat_effects(service, database, run_id):
    prepare(service, run_id)
    first = service.reserve_inventory(run_id, "reserve", "OGA-1042")
    replay = service.reserve_inventory(run_id, "reserve", "OGA-1042")
    another = service.reserve_inventory(run_id, "reserve-again", "OGA-1042")
    assert replay.replayed and replay.action_id == first.action_id
    assert another.data["already_applied"]
    first_confirm = service.confirm_order(run_id, "confirm", "OGA-1042")
    timestamp = row(database, "SELECT confirmed_at FROM orders WHERE id='OGA-1042'")[
        "confirmed_at"
    ]
    assert (
        service.confirm_order(run_id, "confirm", "OGA-1042").action_id
        == first_confirm.action_id
    )
    assert service.confirm_order(run_id, "confirm-again", "OGA-1042").data[
        "already_applied"
    ]
    assert (
        row(database, "SELECT confirmed_at FROM orders WHERE id='OGA-1042'")[
            "confirmed_at"
        ]
        == timestamp
    )
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 9
    )
    assert (
        row(
            database,
            "SELECT count(*) AS n FROM agent_actions WHERE idempotency_key='reserve'",
        )["n"]
        == 1
    )


def test_idempotency_key_conflict(service, database, run_id):
    service.get_order(run_id, "shared", "OGA-1042")
    with pytest.raises(DomainError, match="IDEMPOTENCY_KEY_CONFLICT"):
        service.confirm_order(run_id, "shared", "OGA-1042")
    assert (
        row(database, "SELECT status FROM orders WHERE id='OGA-1042'")["status"]
        == "AWAITING_PAYMENT"
    )


def test_start_run_retry_and_unknown_customer(service, database):
    first = service.start_run("unknown secret text", "unknown")
    replay = service.start_run("unknown secret text", "unknown")
    assert first.reason_code == "CUSTOMER_NOT_FOUND"
    assert replay.replayed and replay.run_id == first.run_id
    assert row(database, "SELECT count(*) AS n FROM escalations")["n"] == 1
    action = row(database, "SELECT result_metadata FROM agent_actions")
    assert "unknown secret text" not in str(action)


@pytest.mark.parametrize(
    "phone,order_id,reason",
    [
        ("DEMO-PHONE-002", "OGA-1051", "AMOUNT_MISMATCH"),
        ("DEMO-PHONE-003", "OGA-1060", "NO_PAYMENT"),
        ("DEMO-PHONE-004", "OGA-1061", "PAYMENT_PENDING"),
        ("DEMO-PHONE-005", "OGA-1062", "PAYMENT_FAILED"),
        ("DEMO-PHONE-006", "OGA-1063", "AMBIGUOUS_PAYMENT"),
    ],
)
def test_matching_failures_persist_escalation_and_audit(
    service, database, phone, order_id, reason
):
    run_id = service.start_run(phone, "start").run_id
    first = service.match_payment(run_id, "match", order_id)
    assert first.reason_code == reason
    assert first.human_review_required
    assert service.match_payment(run_id, "match", order_id).replayed
    order = row(database, "SELECT * FROM orders WHERE id=%s", (order_id,))
    assert order["status"] == "ESCALATED" and order["verified_payment_id"] is None
    assert (
        row(
            database, "SELECT count(*) AS n FROM escalations WHERE reason=%s", (reason,)
        )["n"]
        == 1
    )
    assert (
        row(database, "SELECT status FROM agent_actions WHERE idempotency_key='match'")[
            "status"
        ]
        == "FAILED"
    )
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 12
    )


def test_short_stock_and_no_advance(service, database):
    run_id = service.start_run("DEMO-PHONE-007", "start").run_id
    prepare(service, run_id, "OGA-1064")
    result = service.reserve_inventory(run_id, "reserve", "OGA-1064")
    assert result.reason_code == "INSUFFICIENT_INVENTORY"
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-LOW'")[
            "available_quantity"
        ]
        == 2
    )
    assert (
        row(
            database,
            "SELECT reserved_quantity FROM order_items WHERE order_id='OGA-1064'",
        )["reserved_quantity"]
        == 0
    )


def test_order_ownership_and_hallucinated_id(service, database, run_id):
    result = service.confirm_order(run_id, "wrong-owner", "OGA-1051")
    assert result.reason_code == "ORDER_NOT_FOUND"
    assert (
        row(database, "SELECT status FROM orders WHERE id='OGA-1051'")["status"]
        == "AWAITING_PAYMENT"
    )
    run2 = service.start_run("DEMO-PHONE-001", "new-run").run_id
    assert (
        service.get_order(run2, "missing", "NONEXISTENT").reason_code
        == "ORDER_NOT_FOUND"
    )


def test_illegal_confirmation_escalates_without_mutation(service, database, run_id):
    result = service.confirm_order(run_id, "confirm", "OGA-1042")
    assert result.reason_code == "ILLEGAL_STATE_TRANSITION"
    assert (
        row(database, "SELECT confirmed_at FROM orders WHERE id='OGA-1042'")[
            "confirmed_at"
        ]
        is None
    )


def test_explicit_escalation_is_unique_across_runs(service, database, run_id):
    first = service.create_escalation(run_id, "escalate", "OGA-1042")
    assert service.create_escalation(run_id, "escalate", "OGA-1042").replayed
    run2 = service.start_run("DEMO-PHONE-001", "start2").run_id
    second = service.create_escalation(run2, "escalate2", "OGA-1042")
    assert second.data["escalation_id"] == first.data["escalation_id"]
    assert row(database, "SELECT count(*) AS n FROM escalations")["n"] == 1


def test_transaction_rollback_when_state_write_fails(
    service, database, run_id, monkeypatch
):
    prepare(service, run_id)

    def broken(*args):
        raise RuntimeError("simulated failure after stock decrement")

    monkeypatch.setattr(OperationsRepository, "store_order", broken)
    with pytest.raises(RuntimeError):
        service.reserve_inventory(run_id, "reserve", "OGA-1042")
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 12
    )
    assert (
        row(
            database,
            "SELECT reserved_quantity FROM order_items WHERE order_id='OGA-1042'",
        )["reserved_quantity"]
        == 0
    )
    assert (
        row(database, "SELECT status FROM orders WHERE id='OGA-1042'")["status"]
        == "PAYMENT_VERIFIED"
    )
    assert (
        row(
            database,
            "SELECT count(*) AS n FROM agent_actions WHERE idempotency_key='reserve'",
        )["n"]
        == 0
    )


def test_audit_failure_rolls_back_business_effect(
    service, database, run_id, monkeypatch
):
    prepare(service, run_id)

    def broken(*args):
        raise psycopg.OperationalError("simulated unavailable audit storage")

    monkeypatch.setattr(OperationsRepository, "record_action", broken)
    with pytest.raises(psycopg.OperationalError):
        service.reserve_inventory(run_id, "reserve", "OGA-1042")
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 12
    )
    assert (
        row(database, "SELECT status FROM orders WHERE id='OGA-1042'")["status"]
        == "PAYMENT_VERIFIED"
    )


def test_verification_evidence_persists_from_trusted_adapter(database, service, run_id):
    with UnitOfWork(database).transaction() as repo:
        original = repo.payments("CUS-001")[0]
        repo.connection.execute(
            "UPDATE payments SET verified_at=NULL, verification_source=NULL WHERE id='PAY-88921'"
        )

    class TrustedTestVerifier:
        def verify(self, payment):
            return Payment(
                **{**original.model_dump(), "verified_at": datetime.now(timezone.utc)}
            )

    verified_service = OperationsService(
        UnitOfWork(database), allow_demo=True, verifier=TrustedTestVerifier()
    )
    assert (
        verified_service.verify_payment(run_id, "verify", original.id).status
        == "SUCCEEDED"
    )
    assert (
        row(database, "SELECT verified_at FROM payments WHERE id='PAY-88921'")[
            "verified_at"
        ]
        is not None
    )


def test_concurrent_orders_cannot_oversell(service, database, run_id):
    with database.connect() as connection:
        connection.execute(
            "UPDATE products SET available_quantity=3 WHERE id='PRD-OIL'"
        )
        connection.execute(
            "UPDATE payments SET amount_minor=8400000 WHERE id='PAY-88922'"
        )
    run2 = service.start_run("DEMO-PHONE-002", "start2").run_id
    prepare(service, run_id)
    prepare(service, run2, "OGA-1051")
    barrier = Barrier(2)

    def reserve(run, order):
        barrier.wait(timeout=5)
        return service.reserve_inventory(run, "reserve-" + run, order)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(reserve, run_id, "OGA-1042"),
            pool.submit(reserve, run2, "OGA-1051"),
        ]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(r.status for r in results) == ["FAILED", "SUCCEEDED"]
    assert (
        next(r for r in results if r.status == "FAILED").reason_code
        == "INSUFFICIENT_INVENTORY"
    )
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 0
    )
    assert (
        row(
            database,
            "SELECT sum(reserved_quantity) AS n FROM order_items WHERE product_id='PRD-OIL'",
        )["n"]
        == 3
    )


def test_concurrent_same_key_is_one_effect_and_action(service, database, run_id):
    prepare(service, run_id)
    barrier = Barrier(2)

    def reserve():
        barrier.wait(timeout=5)
        return service.reserve_inventory(run_id, "reserve", "OGA-1042")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert len({r.action_id for r in results}) == 1
    assert sum(r.replayed for r in results) == 1
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 9
    )


@pytest.mark.parametrize(
    "statement,exception",
    [
        (
            "UPDATE products SET available_quantity=-1 WHERE id='PRD-OIL'",
            psycopg.errors.CheckViolation,
        ),
        (
            "UPDATE orders SET total_minor=-1 WHERE id='OGA-1042'",
            psycopg.errors.CheckViolation,
        ),
        (
            "UPDATE orders SET status='UNKNOWN' WHERE id='OGA-1042'",
            psycopg.errors.CheckViolation,
        ),
        (
            "UPDATE orders SET status='CONFIRMED' WHERE id='OGA-1042'",
            psycopg.errors.CheckViolation,
        ),
        (
            "UPDATE order_items SET quantity=0 WHERE order_id='OGA-1042'",
            psycopg.errors.CheckViolation,
        ),
        (
            "UPDATE payments SET reference='TRF92839201' WHERE id='PAY-88922'",
            psycopg.errors.UniqueViolation,
        ),
        (
            "UPDATE orders SET verified_payment_id='PAY-88922' WHERE id='OGA-1042'",
            psycopg.errors.ForeignKeyViolation,
        ),
    ],
)
def test_postgresql_constraints(database, statement, exception):
    with pytest.raises(exception), database.connect() as connection:
        connection.execute(statement)


def test_savepoint_undoes_partial_work_but_keeps_rejection_audit(
    service, database, run_id, monkeypatch
):
    prepare(service, run_id)
    original = OperationsRepository.reserve

    def rejected(repo, order_id, requirements):
        original(repo, order_id, requirements)
        raise DomainError("INSUFFICIENT_INVENTORY")

    monkeypatch.setattr(OperationsRepository, "reserve", rejected)
    result = service.reserve_inventory(run_id, "reserve", "OGA-1042")
    assert result.reason_code == "INSUFFICIENT_INVENTORY"
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 12
    )
    assert (
        row(
            database,
            "SELECT reserved_quantity FROM order_items WHERE order_id='OGA-1042'",
        )["reserved_quantity"]
        == 0
    )
    assert (
        row(database, "SELECT status FROM orders WHERE id='OGA-1042'")["status"]
        == "ESCALATED"
    )
    assert (
        row(
            database,
            "SELECT count(*) AS n FROM agent_actions WHERE idempotency_key='reserve'",
        )["n"]
        == 1
    )


def test_unlinked_payment_and_normal_mode_reject_demo(service, database, run_id):
    normal = OperationsService(UnitOfWork(database))
    result = normal.match_payment(run_id, "match-normal", "OGA-1042")
    assert result.reason_code == "DEMO_PAYMENT_NOT_ALLOWED"
    run2 = service.start_run("DEMO-PHONE-002", "start2").run_id
    with database.connect() as connection:
        connection.execute("UPDATE payments SET order_id=NULL WHERE id='PAY-88922'")
    assert (
        service.match_payment(run2, "match2", "OGA-1051").reason_code
        == "UNLINKED_PAYMENT"
    )


@pytest.mark.parametrize(
    "phone,reason",
    [("DEMO-PHONE-008", "MULTIPLE_OPEN_ORDERS"), ("DEMO-PHONE-009", "NO_OPEN_ORDER")],
)
def test_order_selection_stops_when_unsafe(service, phone, reason):
    run = service.start_run(phone, "start").run_id
    assert service.get_open_orders(run, "orders").reason_code == reason


def test_duplicate_open_escalation_is_rejected_by_sql(service, database, run_id):
    service.create_escalation(run_id, "escalate", "OGA-1042")
    with (
        pytest.raises(psycopg.errors.UniqueViolation),
        database.connect() as connection,
    ):
        connection.execute(
            "INSERT INTO escalations(id,run_id,order_id,reason,details) VALUES ('ESC-DUP',%s,'OGA-1042','HUMAN_REVIEW_REQUESTED','Review')",
            (run_id,),
        )


def test_missing_payment_is_audited(service, database, run_id):
    result = service.verify_payment(run_id, "missing-payment", "PAY-UNKNOWN")
    assert result.reason_code == "PAYMENT_NOT_FOUND"
    assert (
        row(
            database,
            "SELECT failure_code FROM agent_actions WHERE idempotency_key='missing-payment'",
        )["failure_code"]
        == "PAYMENT_NOT_FOUND"
    )


def test_concurrent_different_keys_same_order_reserve_once(service, database, run_id):
    prepare(service, run_id)
    run2 = service.start_run("DEMO-PHONE-001", "start2").run_id
    barrier = Barrier(2)

    def reserve(run):
        barrier.wait(timeout=5)
        return service.reserve_inventory(run, "reserve-" + run, "OGA-1042")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, run) for run in (run_id, run2)]
        results = [future.result(timeout=15) for future in futures]
    assert all(r.status == "SUCCEEDED" for r in results)
    assert sum(r.data["already_applied"] for r in results) == 1
    assert (
        row(database, "SELECT available_quantity FROM products WHERE id='PRD-OIL'")[
            "available_quantity"
        ]
        == 9
    )


def test_failed_confirmation_audit_rolls_back_confirmation(
    service, database, run_id, monkeypatch
):
    prepare(service, run_id)
    service.reserve_inventory(run_id, "reserve", "OGA-1042")
    original = OperationsRepository.record_action

    def fail_confirmation(repo, run, tool, key, metadata, failure=None):
        if tool == "confirm_order":
            raise psycopg.OperationalError("audit unavailable")
        return original(repo, run, tool, key, metadata, failure)

    monkeypatch.setattr(OperationsRepository, "record_action", fail_confirmation)
    with pytest.raises(psycopg.OperationalError):
        service.confirm_order(run_id, "confirm", "OGA-1042")
    order = row(database, "SELECT status, confirmed_at FROM orders WHERE id='OGA-1042'")
    assert order["status"] == "STOCK_RESERVED" and order["confirmed_at"] is None


def test_verification_identity_change_is_rejected(service, database, run_id):
    class InvalidTestVerifier:
        def verify(self, payment):
            return Payment(**{**payment.model_dump(), "amount_minor": 1})

    bad = OperationsService(
        UnitOfWork(database), allow_demo=True, verifier=InvalidTestVerifier()
    )
    result = bad.verify_payment(run_id, "verify", "PAY-88921")
    assert result.reason_code == "VERIFICATION_IDENTITY_MISMATCH"
    assert (
        row(database, "SELECT amount_minor FROM payments WHERE id='PAY-88921'")[
            "amount_minor"
        ]
        == 8400000
    )
