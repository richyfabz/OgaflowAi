from collections.abc import Callable

import pytest
from app.models.domain import Order, Payment, Product

from scripts.seed_demo import demo_records


@pytest.fixture
def records() -> dict[str, list[dict]]:
    return demo_records()


@pytest.fixture
def load_order(records: dict[str, list[dict]]) -> Callable[[str], Order]:
    def load(order_id: str) -> Order:
        raw = next(row for row in records["orders"] if row["id"] == order_id)
        items = [
            {key: value for key, value in row.items() if key != "order_id"}
            for row in records["order_items"]
            if row["order_id"] == order_id
        ]
        return Order(
            **{k: v for k, v in raw.items() if k not in {"created_at", "updated_at"}},
            items=items,
        )

    return load


@pytest.fixture
def payments(records: dict[str, list[dict]]) -> list[Payment]:
    return [
        Payment(**{k: v for k, v in row.items() if k != "created_at"})
        for row in records["payments"]
    ]


@pytest.fixture
def products(records: dict[str, list[dict]]) -> list[Product]:
    return [
        Product(**{k: v for k, v in row.items() if k != "created_at"})
        for row in records["products"]
    ]
