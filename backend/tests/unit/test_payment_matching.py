import pytest
from app.core.exceptions import DomainError
from app.models.domain import Payment
from app.services.payment_matching import match_payment


@pytest.mark.parametrize(
    "order_id,reason",
    [
        ("OGA-1051", "AMOUNT_MISMATCH"),
        ("OGA-1060", "NO_PAYMENT"),
        ("OGA-1061", "PAYMENT_PENDING"),
        ("OGA-1062", "PAYMENT_FAILED"),
        ("OGA-1063", "AMBIGUOUS_PAYMENT"),
    ],
)
def test_seed_payment_failures(load_order, payments, order_id, reason):
    with pytest.raises(DomainError, match=f"^{reason}$"):
        match_payment(load_order(order_id), payments, allow_demo=True)


def test_golden_payment_requires_explicit_demo_mode(load_order, payments):
    order = load_order("OGA-1042")
    with pytest.raises(DomainError, match="DEMO_PAYMENT_NOT_ALLOWED"):
        match_payment(order, payments)
    assert match_payment(order, payments, allow_demo=True).id == "PAY-88921"


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"customer_id": "CUS-002"}, "CUSTOMER_MISMATCH"),
        ({"verified_at": None, "verification_source": None}, "PAYMENT_UNVERIFIED"),
        ({"order_id": None}, "UNLINKED_PAYMENT"),
        ({"order_id": "OGA-UNKNOWN"}, "NO_PAYMENT"),
    ],
)
def test_matching_does_not_guess(load_order, payments, changes, reason):
    payment = Payment(**{**payments[0].model_dump(), **changes})
    with pytest.raises(DomainError, match=reason):
        match_payment(load_order("OGA-1042"), [payment], allow_demo=True)


def test_trusted_provider_evidence_is_accepted(load_order, payments):
    payment = Payment(**{**payments[0].model_dump(), "verification_source": "PROVIDER"})
    assert match_payment(load_order("OGA-1042"), [payment]) == payment


def test_duplicate_candidate_and_failed_attempt_require_review(load_order, payments):
    payment = payments[0]
    failed = Payment(
        **{
            **payment.model_dump(),
            "id": "PAY-SECOND",
            "reference": "OTHER",
            "status": "FAILED",
            "verified_at": None,
            "verification_source": None,
        }
    )
    for candidates in ([payment, payment], [payment, failed]):
        with pytest.raises(DomainError, match="AMBIGUOUS_PAYMENT"):
            match_payment(load_order("OGA-1042"), candidates, allow_demo=True)
