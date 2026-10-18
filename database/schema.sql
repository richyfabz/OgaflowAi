-- Approved schema. Apply once to a new, isolated PostgreSQL database.
-- Cross-table business checks and transactional writes are enforced by services/repositories.
BEGIN;

CREATE TABLE customers (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    name TEXT NOT NULL CHECK (length(name) > 0),
    phone TEXT NOT NULL UNIQUE CHECK (length(phone) > 0),
    preferred_language TEXT NOT NULL DEFAULT 'English/Pidgin',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    name TEXT NOT NULL CHECK (length(name) > 0),
    unit TEXT NOT NULL DEFAULT 'carton',
    available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    status TEXT NOT NULL DEFAULT 'CREATED' CHECK (status IN (
        'CREATED', 'AWAITING_PAYMENT', 'PAYMENT_VERIFIED', 'STOCK_RESERVED',
        'CONFIRMED', 'FULFILMENT', 'ESCALATED'
    )),
    total_minor BIGINT NOT NULL CHECK (total_minor >= 0),
    currency TEXT NOT NULL DEFAULT 'NGN' CHECK (currency = 'NGN'),
    verified_payment_id TEXT UNIQUE,
    stock_reserved_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, customer_id),
    CHECK (updated_at >= created_at),
    CHECK (status NOT IN ('PAYMENT_VERIFIED', 'STOCK_RESERVED', 'CONFIRMED', 'FULFILMENT')
        OR verified_payment_id IS NOT NULL),
    CHECK (status NOT IN ('STOCK_RESERVED', 'CONFIRMED', 'FULFILMENT')
        OR stock_reserved_at IS NOT NULL),
    CHECK (status NOT IN ('CONFIRMED', 'FULFILMENT') OR confirmed_at IS NOT NULL)
);

CREATE TABLE order_items (
    order_id TEXT NOT NULL REFERENCES orders(id),
    product_id TEXT NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_minor BIGINT NOT NULL CHECK (unit_price_minor >= 0),
    reserved_quantity INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (order_id, product_id),
    CHECK (reserved_quantity = 0 OR reserved_quantity = quantity)
);

CREATE TABLE payments (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    customer_id TEXT NOT NULL REFERENCES customers(id),
    order_id TEXT,
    amount_minor BIGINT NOT NULL CHECK (amount_minor >= 0),
    currency TEXT NOT NULL DEFAULT 'NGN' CHECK (currency = 'NGN'),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'SUCCESS', 'FAILED')),
    provider TEXT NOT NULL CHECK (length(provider) > 0),
    reference TEXT NOT NULL CHECK (length(reference) > 0),
    verified_at TIMESTAMPTZ,
    verification_source TEXT CHECK (verification_source IN ('DEMO', 'PROVIDER')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (provider, reference),
    UNIQUE (id, order_id, customer_id, amount_minor, currency),
    FOREIGN KEY (order_id, customer_id) REFERENCES orders(id, customer_id),
    CHECK ((verified_at IS NULL AND verification_source IS NULL)
        OR (verified_at IS NOT NULL AND verification_source IS NOT NULL AND status = 'SUCCESS'))
);

-- A claimed verification cannot refer to another order/customer/amount/currency.
-- Services must additionally validate successful, trusted verification evidence.
ALTER TABLE orders ADD CONSTRAINT orders_verified_payment_fk
    FOREIGN KEY (verified_payment_id, id, customer_id, total_minor, currency)
    REFERENCES payments(id, order_id, customer_id, amount_minor, currency);

CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    customer_id TEXT REFERENCES customers(id),
    status TEXT NOT NULL DEFAULT 'RUNNING'
        CHECK (status IN ('RUNNING', 'COMPLETED', 'ESCALATED', 'FAILED')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE agent_actions (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    tool TEXT NOT NULL CHECK (length(tool) > 0),
    status TEXT NOT NULL DEFAULT 'STARTED' CHECK (status IN ('STARTED', 'SUCCEEDED', 'FAILED')),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) > 0),
    result_metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(result_metadata) = 'object'),
    failure_code TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE escalations (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    run_id TEXT NOT NULL REFERENCES agent_runs(id),
    order_id TEXT REFERENCES orders(id),
    reason TEXT NOT NULL CHECK (length(reason) > 0),
    details TEXT NOT NULL CHECK (length(details) > 0),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'RESOLVED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMPTZ,
    CHECK ((status = 'OPEN' AND resolved_at IS NULL)
        OR (status = 'RESOLVED' AND resolved_at IS NOT NULL AND resolved_at >= created_at))
);

CREATE UNIQUE INDEX one_open_order_escalation
    ON escalations(order_id, reason) WHERE status = 'OPEN' AND order_id IS NOT NULL;
CREATE UNIQUE INDEX one_open_run_escalation
    ON escalations(run_id, reason) WHERE status = 'OPEN' AND order_id IS NULL;
CREATE INDEX orders_customer_idx ON orders(customer_id);
CREATE INDEX payments_customer_idx ON payments(customer_id);
CREATE INDEX payments_order_idx ON payments(order_id);
CREATE INDEX agent_actions_run_idx ON agent_actions(run_id);

COMMIT;
