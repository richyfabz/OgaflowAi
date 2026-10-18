import pytest
from app.core.exceptions import DomainError
from app.models.domain import Payment
from app.services.verification import StoredDemoVerifier, UnavailablePaymentVerifier


def test_no_provider_is_fabricated(payments):
    with pytest.raises(DomainError, match="PAYMENT_PROVIDER_UNAVAILABLE"):
        UnavailablePaymentVerifier().verify(payments[0])


def test_demo_adapter_requires_existing_explicit_evidence(payments):
    without_evidence = Payment(
        **{**payments[0].model_dump(), "verified_at": None, "verification_source": None}
    )
    with pytest.raises(DomainError, match="PAYMENT_UNVERIFIED"):
        StoredDemoVerifier().verify(without_evidence)
    provider = Payment(
        **{**payments[0].model_dump(), "verification_source": "PROVIDER"}
    )
    with pytest.raises(DomainError, match="PAYMENT_UNVERIFIED"):
        StoredDemoVerifier().verify(provider)


def test_demo_adapter_returns_labelled_seed_evidence(payments):
    assert StoredDemoVerifier().verify(payments[0]) == payments[0]
