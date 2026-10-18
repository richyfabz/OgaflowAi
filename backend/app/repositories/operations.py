"""PostgreSQL operations needed by the single MVP workflow."""

from uuid import uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.core.exceptions import DomainError
from app.models.domain import Customer, Order, Payment, Product


class OperationsRepository:
    """Persist workflow records within the caller-owned transaction."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def savepoint(self):
        return self.connection.transaction()

    def lock_key(self, key: str) -> None:
        # Transaction-scoped PostgreSQL lock serializes even the first use of a key.
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,)
        )

    def action_by_key(self, key: str):
        return self.connection.execute(
            "SELECT * FROM agent_actions WHERE idempotency_key = %s", (key,)
        ).fetchone()

    def record_action(self, run_id, tool, key, metadata, failure=None):
        action_id = "ACT-" + uuid4().hex
        self.connection.execute(
            """INSERT INTO agent_actions
            (id, run_id, tool, status, idempotency_key, result_metadata, failure_code, finished_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, clock_timestamp())""",
            (
                action_id,
                run_id,
                tool,
                "FAILED" if failure else "SUCCEEDED",
                key,
                Jsonb(metadata),
                failure,
            ),
        )
        return action_id

    def customer(self, customer_id: str) -> Customer:
        row = self.connection.execute(
            "SELECT id, name, phone, preferred_language FROM customers WHERE id=%s",
            (customer_id,),
        ).fetchone()
        if row is None:
            raise DomainError("CUSTOMER_NOT_FOUND")
        return Customer(**row)

    def identify_customer(self, phone: str):
        row = self.connection.execute(
            "SELECT id FROM customers WHERE phone=%s", (phone,)
        ).fetchone()
        return row["id"] if row else None

    def create_run(self, customer_id):
        run_id = "RUN-" + uuid4().hex
        self.connection.execute(
            "INSERT INTO agent_runs(id, customer_id) VALUES (%s, %s)",
            (run_id, customer_id),
        )
        return run_id

    def run(self, run_id: str):
        row = self.connection.execute(
            "SELECT * FROM agent_runs WHERE id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        if row is None:
            raise DomainError("RUN_NOT_FOUND")
        return row

    def escalate_run(self, run_id):
        self.connection.execute(
            "UPDATE agent_runs SET status='ESCALATED', finished_at=clock_timestamp() WHERE id=%s",
            (run_id,),
        )

    def order(self, order_id: str) -> Order:
        row = self.connection.execute(
            """SELECT id, customer_id, status, total_minor, currency, verified_payment_id
            FROM orders WHERE id=%s FOR UPDATE""",
            (order_id,),
        ).fetchone()
        if row is None:
            raise DomainError("ORDER_NOT_FOUND")
        items = self.connection.execute(
            """SELECT product_id, quantity, unit_price_minor, reserved_quantity
            FROM order_items WHERE order_id=%s ORDER BY product_id FOR UPDATE""",
            (order_id,),
        ).fetchall()
        return Order(**row, items=items)

    def open_orders(self, customer_id):
        return self.connection.execute(
            """SELECT id, status, total_minor, currency FROM orders
            WHERE customer_id=%s AND status IN ('CREATED','AWAITING_PAYMENT','PAYMENT_VERIFIED','STOCK_RESERVED')
            ORDER BY id""",
            (customer_id,),
        ).fetchall()

    def payments(self, customer_id):
        rows = self.connection.execute(
            """SELECT id, customer_id, order_id, amount_minor, currency, status, provider,
            reference, verified_at, verification_source FROM payments
            WHERE customer_id=%s ORDER BY id FOR UPDATE""",
            (customer_id,),
        ).fetchall()
        return [Payment(**row) for row in rows]

    def payment_order_id(self, payment_id):
        row = self.connection.execute(
            "SELECT order_id FROM payments WHERE id=%s", (payment_id,)
        ).fetchone()
        if row is None:
            raise DomainError("PAYMENT_NOT_FOUND")
        return row["order_id"]

    def store_verification(self, payment: Payment):
        self.connection.execute(
            """UPDATE payments SET status=%s, verified_at=%s, verification_source=%s WHERE id=%s""",
            (
                payment.status.value,
                payment.verified_at,
                payment.verification_source.value,
                payment.id,
            ),
        )

    def products(self, product_ids):
        rows = self.connection.execute(
            """SELECT id, name, unit, available_quantity FROM products
            WHERE id=ANY(%s) ORDER BY id FOR UPDATE""",
            (list(product_ids),),
        ).fetchall()
        return [Product(**row) for row in rows]

    def reserve(self, order_id, requirements):
        for product_id, quantity in sorted(requirements.items()):
            row = self.connection.execute(
                """UPDATE products SET available_quantity=available_quantity-%s
                WHERE id=%s AND available_quantity >= %s RETURNING id""",
                (quantity, product_id, quantity),
            ).fetchone()
            if row is None:
                raise DomainError("INSUFFICIENT_INVENTORY")
            self.connection.execute(
                """UPDATE order_items SET reserved_quantity=quantity
                WHERE order_id=%s AND product_id=%s""",
                (order_id, product_id),
            )

    def store_order(self, order: Order):
        self.connection.execute(
            """UPDATE orders SET status=%s, verified_payment_id=%s,
            stock_reserved_at=CASE WHEN %s='STOCK_RESERVED' THEN COALESCE(stock_reserved_at,CURRENT_TIMESTAMP) ELSE stock_reserved_at END,
            confirmed_at=CASE WHEN %s='CONFIRMED' THEN COALESCE(confirmed_at,CURRENT_TIMESTAMP) ELSE confirmed_at END,
            updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
            (
                order.status.value,
                order.verified_payment_id,
                order.status.value,
                order.status.value,
                order.id,
            ),
        )

    def create_escalation(self, run_id, order_id, reason, details):
        # The service holds the order lock, or the run lock for an orderless case.
        existing = self.connection.execute(
            """SELECT id FROM escalations WHERE status='OPEN' AND reason=%s
            AND ((%s::text IS NOT NULL AND order_id=%s) OR (%s::text IS NULL AND order_id IS NULL AND run_id=%s))""",
            (reason, order_id, order_id, order_id, run_id),
        ).fetchone()
        if existing:
            return existing["id"]
        escalation_id = "ESC-" + uuid4().hex
        self.connection.execute(
            "INSERT INTO escalations(id,run_id,order_id,reason,details) VALUES (%s,%s,%s,%s,%s)",
            (escalation_id, run_id, order_id, reason, details),
        )
        return escalation_id

    def run_actions(self, run_id):
        return self.connection.execute(
            """SELECT id, tool, status, failure_code, started_at, finished_at FROM agent_actions
            WHERE run_id=%s ORDER BY started_at,id""",
            (run_id,),
        ).fetchall()
