import subprocess
import sys
from pathlib import Path

from app.models.domain import Customer

from scripts.seed_demo import ROOT, demo_records, render_seed


def test_seed_artifact_matches_generator():
    assert (ROOT / "database/seed.sql").read_text(encoding="utf-8") == render_seed()
    assert render_seed() == render_seed()


def test_fixture_relationships_and_domain_validation(
    records, load_order, payments, products
):
    customers = [
        Customer(**{k: v for k, v in row.items() if k != "created_at"})
        for row in records["customers"]
    ]
    customer_ids = {customer.id for customer in customers}
    product_ids = {product.id for product in products}
    orders = {row["id"]: load_order(row["id"]) for row in records["orders"]}
    for order in orders.values():
        assert order.customer_id in customer_ids
        assert {item.product_id for item in order.items} <= product_ids
    for payment in payments:
        assert orders[payment.order_id].customer_id == payment.customer_id
    assert len({(p.provider, p.reference) for p in payments}) == len(payments)
    assert len([o for o in orders.values() if o.customer_id == "CUS-008"]) == 2
    assert not any(o.customer_id == "CUS-009" for o in orders.values())


def test_fixtures_are_fresh():
    first = demo_records()
    first["products"][0]["available_quantity"] = 0
    assert demo_records()["products"][0]["available_quantity"] == 12


def test_reset_prepares_local_artifact_and_refuses_overwrite(tmp_path: Path):
    output = tmp_path / "demo.sql"
    command = [
        sys.executable,
        str(ROOT / "scripts/reset_demo.py"),
        "--output",
        str(output),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert output.read_text().endswith(render_seed())
    previous = output.read_bytes()
    repeated = subprocess.run(command, capture_output=True, text=True, check=False)
    assert repeated.returncode != 0
    assert output.read_bytes() == previous
