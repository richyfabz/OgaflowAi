"""Pure state validation. Persistence and atomic mutations belong to Phase 3."""

from collections.abc import Sequence

from app.core.exceptions import DomainError
from app.models.domain import Order, Payment, Product
from app.models.enums import OrderStatus
from app.services.payment_matching import match_payment

_FORWARD = {
    OrderStatus.CREATED: OrderStatus.AWAITING_PAYMENT,
    OrderStatus.AWAITING_PAYMENT: OrderStatus.PAYMENT_VERIFIED,
    OrderStatus.PAYMENT_VERIFIED: OrderStatus.STOCK_RESERVED,
    OrderStatus.STOCK_RESERVED: OrderStatus.CONFIRMED,
    OrderStatus.CONFIRMED: OrderStatus.FULFILMENT,
}
_PAYMENT_REQUIRED = frozenset(
    {
        OrderStatus.PAYMENT_VERIFIED,
        OrderStatus.STOCK_RESERVED,
        OrderStatus.CONFIRMED,
        OrderStatus.FULFILMENT,
    }
)
_RESERVATION_REQUIRED = frozenset(
    {
        OrderStatus.STOCK_RESERVED,
        OrderStatus.CONFIRMED,
        OrderStatus.FULFILMENT,
    }
)


def transition_order(
    order: Order,
    target: OrderStatus,
    payments: Sequence[Payment] = (),
    *,
    allow_demo: bool = False,
) -> Order:
    """Validate a transition using backend-loaded evidence; perform no side effects."""
    if not isinstance(target, OrderStatus):
        raise DomainError("INVALID_ORDER_STATUS")
    if target != order.status:
        escalation = target == OrderStatus.ESCALATED and order.status in _FORWARD
        if not escalation and _FORWARD.get(order.status) != target:
            raise DomainError("ILLEGAL_STATE_TRANSITION")
    payment_id = order.verified_payment_id
    if target in _PAYMENT_REQUIRED:
        payment = match_payment(order, payments, allow_demo=allow_demo)
        if order.status in _PAYMENT_REQUIRED and payment_id != payment.id:
            raise DomainError("VERIFIED_PAYMENT_MISMATCH")
        payment_id = payment.id
    if target in _RESERVATION_REQUIRED and any(
        item.reserved_quantity != item.quantity for item in order.items
    ):
        raise DomainError("INVENTORY_NOT_RESERVED")
    if target == order.status:
        return order
    return Order.model_validate(
        {
            **order.model_dump(),
            "status": target,
            "verified_payment_id": payment_id,
        }
    )


def check_reservation(order: Order, products: Sequence[Product]) -> dict[str, int]:
    """Return stock requirements without decrementing stock or marking a reservation."""
    if (
        order.status != OrderStatus.PAYMENT_VERIFIED
        or order.verified_payment_id is None
    ):
        raise DomainError("ILLEGAL_STATE_TRANSITION")
    stock = {product.id: product for product in products}
    if len(stock) != len(products):
        raise DomainError("DUPLICATE_PRODUCT")
    requirements = {}
    for item in order.items:
        if item.reserved_quantity == item.quantity:
            continue
        product = stock.get(item.product_id)
        if product is None:
            raise DomainError("PRODUCT_NOT_FOUND")
        if product.available_quantity < item.quantity:
            raise DomainError("INSUFFICIENT_INVENTORY")
        requirements[item.product_id] = item.quantity
    return requirements
