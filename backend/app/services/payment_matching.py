"""Pure matching rules for trusted repository snapshots, never LLM claims."""

from collections.abc import Sequence

from app.core.exceptions import DomainError
from app.models.domain import Order, Payment
from app.models.enums import PaymentStatus, VerificationSource


def match_payment(
    order: Order, payments: Sequence[Payment], *, allow_demo: bool = False
) -> Payment:
    """Return one verified, explicitly linked payment or a human-review reason."""
    candidates = [payment for payment in payments if payment.order_id == order.id]
    if not candidates:
        if any(
            p.customer_id == order.customer_id and p.order_id is None for p in payments
        ):
            raise DomainError("UNLINKED_PAYMENT")
        raise DomainError("NO_PAYMENT")
    # Even one successful candidate alongside another attempt requires review in the MVP.
    if len(candidates) != 1:
        raise DomainError("AMBIGUOUS_PAYMENT")
    payment = candidates[0]
    if payment.customer_id != order.customer_id:
        raise DomainError("CUSTOMER_MISMATCH")
    if payment.amount_minor != order.total_minor or payment.currency != order.currency:
        raise DomainError("AMOUNT_MISMATCH")
    if payment.status != PaymentStatus.SUCCESS:
        raise DomainError(f"PAYMENT_{payment.status.value}")
    if payment.verified_at is None or payment.verification_source is None:
        raise DomainError("PAYMENT_UNVERIFIED")
    if payment.verification_source == VerificationSource.DEMO and not allow_demo:
        raise DomainError("DEMO_PAYMENT_NOT_ALLOWED")
    return payment
