# OgaFlow Architecture

## Canonical architecture

One orchestrator interprets customer intent and chooses restricted tools. The
backend decides whether an action is valid. No LLM establishes payment, inventory,
order state or ownership truth.

```text
Customer channels → single orchestrator (future BimpeAI integration)
  → restricted tools → FastAPI → services → repositories → PostgreSQL
```

Workflow: identify customer → retrieve open order → find payment → verify payment →
match payment → check inventory → reserve inventory → confirm order → notify customer
→ record actions. Unsafe cases stop and persist a human escalation.

## Implemented Phase 3 boundaries

- `api/operations.py`: typed HTTP requests/responses and dependency injection.
- `schemas/operations.py`: restricted request DTOs and trace response types.
- `services/operations.py`: transaction coordination, customer/order scope,
  payment/stock guards, state transitions and server-owned auditing.
- `services/order_state.py`, `payment_matching.py`: approved pure Phase 2 rules.
- `services/verification.py`: trusted verification protocol, explicit seed-evidence
  demo adapter, unavailable real-provider adapter.
- `repositories/operations.py`: all domain SQL, row/advisory locks, persistence.
- `repositories/unit_of_work.py`: one transaction for each operation.
- `core/database.py`: bounded connections/timeouts; no import-time database I/O.
- `models`: validated domain snapshots and tool result envelope.
- `agent`: remains scaffold only; no database access.

Python 3.10, integer kobo, FastAPI, Pydantic, pytest, HTTPX and React/TypeScript/Vite
remain unchanged. `psycopg[binary]==3.3.6` is the approved minimal driver. No ORM,
migration framework, queue, external lock system or second agent was added.
The existing frontend remains at `backend/frontend` and was not implemented here.

## Transactions and locking

Each tool invocation opens a short-lived connection. Database transactions use
READ COMMITTED. Lock order: idempotency key → run → order/lines → payments sorted by
ID → products sorted by ID. Product locks are held through stock decrement,
reservation marking, order transition, audit insertion and commit.
A conditional stock update (`available_quantity >= required`) adds a final guard.
No HTTP requests or notifications are made while holding these locks.

PostgreSQL transaction advisory locks serialize first-use idempotency keys;
agent_actions.idempotency_key remains the persistent uniqueness constraint.
A new retry key cannot bypass already-persisted reservation/confirmation markers.
Orderless escalation uses the run lock; order escalation uses the order lock and
existing partial unique indexes. Other payment/order writers must follow the same
order-first locking protocol when future ingestion/editing is introduced.

A savepoint surrounds the attempted domain operation. On a DomainError, partial
work rolls back to the savepoint, while the outer transaction records the failure,
escalation, stopped run and permitted ESCALATED order transition. Infrastructure or
audit failure rolls back the entire transaction; no success is returned. The API
returns a safe error, and the caller may retry with the original idempotency key.

See [PostgreSQL locking](https://www.postgresql.org/docs/16/explicit-locking.html)
and [Psycopg transactions](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).

## Observability and safety

Run/action IDs are generated server-side. Stored metadata consists of a request
hash and allowlisted tool output, with status/timestamps and stable failure codes.
No raw phone input, credentials, full transcripts or provider payloads are recorded.
Escalations preserve run/order links, reason, safe details, status and timestamps.

Services bind operations to the run's customer. Authentication remains out of scope;
these endpoints are for local development and are not approved for public exposure.
SQL constraints supplement service invariants; direct privileged SQL can bypass
cross-row domain semantics. Do not give agent/browser code database credentials.

## Local environment and remaining targets

Local verification uses real PostgreSQL 16 in `.local/`, with a private Unix socket,
no TCP listener, and no system daemon. The driver still supports the unchanged
PostgreSQL/Supabase production target. Supabase connectivity and Vercel deployment
are unverified and have not been attempted. OGAFLOW_DEBUG replaces the unrelated
host DEBUG setting; demo mode is permitted only in development/test.

BimpeAI, channels, notifications, provider integration, authentication and frontend
Control Center remain outside Phase 3. ESCALATED/FULFILMENT recovery is not defined.
