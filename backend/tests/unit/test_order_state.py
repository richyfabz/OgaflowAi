import pytest
from app.core.exceptions import DomainError
from app.models.domain import Order, Product
from app.models.enums import OrderStatus as S
from app.services.order_state import check_reservation, transition_order


def snapshot(order, status, *, reserved=True, payment_id="PAY-88921"):
    return Order(
        **{
            **order.model_dump(),
            "status": status,
            "verified_payment_id": payment_id,
            "items": [
                {
                    **item.model_dump(),
                    "reserved_quantity": item.quantity if reserved else 0,
                }
                for item in order.items
            ],
        }
    )


@pytest.mark.parametrize("source", list(S))
@pytest.mark.parametrize("target", list(S))
def test_complete_transition_matrix(load_order, payments, source, target):
    forward = {
        (S.CREATED, S.AWAITING_PAYMENT),
        (S.AWAITING_PAYMENT, S.PAYMENT_VERIFIED),
        (S.PAYMENT_VERIFIED, S.STOCK_RESERVED),
        (S.STOCK_RESERVED, S.CONFIRMED),
        (S.CONFIRMED, S.FULFILMENT),
    }
    allowed = (
        source == target
        or (source, target) in forward
        or (target == S.ESCALATED and source not in {S.FULFILMENT, S.ESCALATED})
    )
    order = snapshot(load_order("OGA-1042"), source)
    if allowed:
        result = transition_order(order, target, payments, allow_demo=True)
        assert result.status == target
        if source == target:
            assert result is order
    else:
        with pytest.raises(DomainError, match="ILLEGAL_STATE_TRANSITION"):
            transition_order(order, target, payments, allow_demo=True)


@pytest.mark.parametrize("target", [S.STOCK_RESERVED, S.CONFIRMED, S.FULFILMENT])
def test_advanced_states_require_full_reservation_even_on_replay(
    load_order, payments, target
):
    order = snapshot(load_order("OGA-1042"), target, reserved=False)
    with pytest.raises(DomainError, match="INVENTORY_NOT_RESERVED"):
        transition_order(order, target, payments, allow_demo=True)


@pytest.mark.parametrize(
    "status", [S.PAYMENT_VERIFIED, S.STOCK_RESERVED, S.CONFIRMED, S.FULFILMENT]
)
def test_advanced_states_require_payment_even_on_replay(load_order, status):
    order = snapshot(load_order("OGA-1042"), status)
    with pytest.raises(DomainError, match="NO_PAYMENT"):
        transition_order(order, status)


def test_payment_link_cannot_change(load_order, payments):
    order = snapshot(load_order("OGA-1042"), S.STOCK_RESERVED, payment_id="PAY-WRONG")
    with pytest.raises(DomainError, match="VERIFIED_PAYMENT_MISMATCH"):
        transition_order(order, S.CONFIRMED, payments, allow_demo=True)


def test_invalid_status_is_not_accepted(load_order):
    with pytest.raises(DomainError, match="INVALID_ORDER_STATUS"):
        transition_order(load_order("OGA-1042"), "CONFIRMED")


def test_inventory_check_is_pure_and_replay_has_no_stock_requirement(
    load_order, payments, products
):
    order = transition_order(
        load_order("OGA-1042"), S.PAYMENT_VERIFIED, payments, allow_demo=True
    )
    assert check_reservation(order, products) == {"PRD-OIL": 3}
    assert check_reservation(order, products) == {"PRD-OIL": 3}
    assert products[0].available_quantity == 12
    assert check_reservation(snapshot(order, S.PAYMENT_VERIFIED), []) == {}


def test_inventory_rejects_missing_duplicate_or_short_stock(
    load_order, payments, products
):
    order = transition_order(
        load_order("OGA-1042"), S.PAYMENT_VERIFIED, payments, allow_demo=True
    )
    cases = [
        ([], "PRODUCT_NOT_FOUND"),
        (products * 2, "DUPLICATE_PRODUCT"),
        (
            [Product(id="PRD-OIL", name="Oil", available_quantity=2)],
            "INSUFFICIENT_INVENTORY",
        ),
    ]
    for stock, reason in cases:
        with pytest.raises(DomainError, match=reason):
            check_reservation(order, stock)


def test_inventory_cannot_be_reserved_before_verification(load_order, products):
    with pytest.raises(DomainError, match="ILLEGAL_STATE_TRANSITION"):
        check_reservation(load_order("OGA-1042"), products)


def test_all_lines_must_have_stock_and_reservations(load_order, payments, products):
    from app.models.domain import Payment

    raw = load_order("OGA-1042").model_dump()
    raw["items"] = (
        *raw["items"],
        {
            "product_id": "PRD-LOW",
            "quantity": 3,
            "unit_price_minor": 2800000,
        },
    )
    order = Order(**{**raw, "total_minor": 16800000})
    payment = Payment(**{**payments[0].model_dump(), "amount_minor": 16800000})
    verified = transition_order(order, S.PAYMENT_VERIFIED, [payment], allow_demo=True)
    with pytest.raises(DomainError, match="INSUFFICIENT_INVENTORY"):
        check_reservation(verified, products)
    assert products[0].available_quantity == 12
    assert all(item.reserved_quantity == 0 for item in verified.items)
    raw = verified.model_dump()
    raw["items"][0]["reserved_quantity"] = 3
    with pytest.raises(DomainError, match="INVENTORY_NOT_RESERVED"):
        transition_order(Order(**raw), S.STOCK_RESERVED, [payment], allow_demo=True)
