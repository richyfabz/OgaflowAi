"""Trusted adapter boundary. No real payment provider is integrated in Phase 3."""

from typing import Protocol

from app.core.exceptions import DomainError
from app.models.domain import Payment
from app.models.enums import PaymentStatus, VerificationSource


class PaymentVerifier(Protocol):
    def verify(self, payment: Payment) -> Payment: ...


class UnavailablePaymentVerifier:
    def verify(self, payment: Payment) -> Payment:
        raise DomainError("PAYMENT_PROVIDER_UNAVAILABLE")


class StoredDemoVerifier:
    """Read explicitly labelled seed evidence; never manufacture provider truth."""

    def verify(self, payment: Payment) -> Payment:
        if payment.status != PaymentStatus.SUCCESS:
            raise DomainError(f"PAYMENT_{payment.status.value}")
        if (
            payment.verification_source != VerificationSource.DEMO
            or payment.verified_at is None
        ):
            raise DomainError("PAYMENT_UNVERIFIED")
        return payment
