import pytest
from app.models.domain import Order, OrderItem, Payment, Product
from pydantic import ValidationError


@pytest.mark.parametrize("value", [-1, 1.5, "8400000", True, 2**63])
def test_money_rejects_invalid_minor_units(load_order, value):
    raw = load_order("OGA-1042").model_dump()
    raw["total_minor"] = value
    with pytest.raises(ValidationError):
        Order(**raw)


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, 2**31])
def test_quantity_must_be_positive_integer(quantity):
    with pytest.raises(ValidationError):
        OrderItem(product_id="PRD-OIL", quantity=quantity, unit_price_minor=2800000)


def test_totals_and_duplicate_lines_are_rejected(load_order):
    raw = load_order("OGA-1042").model_dump()
    with pytest.raises(ValidationError, match="total"):
        Order(**{**raw, "total_minor": 1})
    with pytest.raises(ValidationError, match="only once"):
        Order(**{**raw, "items": raw["items"] * 2, "total_minor": 16800000})


@pytest.mark.parametrize("reserved", [-1, 1, 4])
def test_reservation_is_zero_or_full_quantity(reserved):
    with pytest.raises(ValidationError):
        OrderItem(
            product_id="PRD-OIL",
            quantity=3,
            unit_price_minor=2800000,
            reserved_quantity=reserved,
        )


def test_stock_cannot_be_negative():
    with pytest.raises(ValidationError):
        Product(id="PRD-OIL", name="Oil", available_quantity=-1)


@pytest.mark.parametrize(
    "changes",
    [
        {"verification_source": None},
        {"verified_at": None},
        {"verified_at": "2026-10-01T00:00:00"},
        {"status": "PENDING"},
        {"status": "FAILED"},
        {"currency": "USD"},
    ],
)
def test_payment_rejects_invalid_evidence(payments, changes):
    with pytest.raises(ValidationError):
        Payment(**{**payments[0].model_dump(), **changes})


def test_snapshots_are_immutable(load_order):
    order = load_order("OGA-1042")
    with pytest.raises(ValidationError):
        order.total_minor = 0
