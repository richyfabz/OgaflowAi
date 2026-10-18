"""Domain rehearsals only: no database mutation, external agent, or notifications."""

import pytest
from app.core.exceptions import DomainError
from app.models.domain import Order
from app.models.enums import OrderStatus as S
from app.services.order_state import check_reservation, transition_order


def test_golden_domain_progression(load_order, payments, products):
    initial = load_order("OGA-1042")
    verified = transition_order(initial, S.PAYMENT_VERIFIED, payments, allow_demo=True)
    assert check_reservation(verified, products) == {"PRD-OIL": 3}
    # Simulate a future repository's committed reservation snapshot, not a stock mutation.
    reserved_snapshot = Order(
        **{
            **verified.model_dump(),
            "items": [
                {**item.model_dump(), "reserved_quantity": item.quantity}
                for item in verified.items
            ],
        }
    )
    reserved = transition_order(
        reserved_snapshot, S.STOCK_RESERVED, payments, allow_demo=True
    )
    confirmed = transition_order(reserved, S.CONFIRMED, payments, allow_demo=True)
    assert confirmed.verified_payment_id == "PAY-88921"
    assert confirmed.status == S.CONFIRMED
    assert (
        transition_order(confirmed, S.CONFIRMED, payments, allow_demo=True) is confirmed
    )
    assert initial.status == S.AWAITING_PAYMENT
    assert products[0].available_quantity == 12


def test_amount_mismatch_stops_progress_and_allows_escalation(load_order, payments):
    order = load_order("OGA-1051")
    with pytest.raises(DomainError, match="AMOUNT_MISMATCH"):
        transition_order(order, S.PAYMENT_VERIFIED, payments, allow_demo=True)
    assert order.status == S.AWAITING_PAYMENT
    assert order.verified_payment_id is None
    assert all(item.reserved_quantity == 0 for item in order.items)
    assert transition_order(order, S.ESCALATED).status == S.ESCALATED


def test_insufficient_inventory_stops_confirmation(load_order, payments, products):
    order = transition_order(
        load_order("OGA-1064"), S.PAYMENT_VERIFIED, payments, allow_demo=True
    )
    with pytest.raises(DomainError, match="INSUFFICIENT_INVENTORY"):
        check_reservation(order, products)
    with pytest.raises(DomainError, match="ILLEGAL_STATE_TRANSITION"):
        transition_order(order, S.CONFIRMED, payments, allow_demo=True)
    assert transition_order(order, S.ESCALATED).status == S.ESCALATED
