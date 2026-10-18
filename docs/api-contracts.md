# API and Tool Contracts — Phase 3

FastAPI → OperationsService → UnitOfWork / OperationsRepository → PostgreSQL.
Run locally only: authentication, BimpeAI, production exposure and notification
integrations are outside this checkpoint. Run ownership checks enforce consistent
customer/order relationships; a run ID is not an authentication credential.

## Common contract

All POST bodies reject extra fields. IDs/idempotency keys are 1–128 characters
containing letters, digits, underscore, period, colon or hyphen. Phone strings are
1–40 characters. The synthetic demo uses non-dialable `DEMO-PHONE-001` values.

Every operational POST records a server-generated action. No endpoint accepts
verification evidence, order status, stock totals, arbitrary audit metadata, raw
provider responses or free-text escalation details.

```json
{
  "run_id": "RUN-...",
  "action_id": "ACT-...",
  "status": "SUCCEEDED",
  "data": {"order_id": "OGA-1042", "order_status": "CONFIRMED", "already_applied": false},
  "reason_code": null,
  "human_review_required": false,
  "replayed": false
}
```

A business rejection uses HTTP 200 with `status: FAILED`, a stable `reason_code`,
`human_review_required: true`, and `data.escalation_id`. This is a completed tool
execution with a rejected business action; clients must inspect `status`.
`RUN_NOT_ACTIVE` prevents further mutations after escalation and creates no new
escalation for the already stopped run.

Transport/configuration errors:

- 422: invalid request or forbidden extra field.
- 404: nonexistent run at the outer service boundary.
- 409: idempotency key reused for a different tool/run/argument set.
- 503: `DATABASE_UNAVAILABLE`, or `detail.code: DATABASE_NOT_CONFIGURED`.
- Unexpected internal failures return a generic 500; database traces/DSNs are not returned.

Missing/wrong-owner orders and missing payments during a valid run produce audited
business failures. Wrong-owner orders are reported as ORDER_NOT_FOUND and are not changed.

## Implemented endpoints

| Method/path | Body | Result data |
|---|---|---|
| GET `/health` | None | Existing status/service/environment |
| POST `/runs` | phone, idempotency_key | Identified customer_id/name/language; creates run and identify_customer action |
| GET `/runs/{run_id}` | None | Run status/customer/timestamps and ordered action summaries |
| POST `/tools/get_open_orders` | run_id, idempotency_key | orders; zero/multiple orders stop with escalation |
| POST `/tools/get_order` | run_id, idempotency_key, order_id | Validated order, status and item snapshot |
| POST `/tools/find_payments` | run_id, idempotency_key | Customer's payment ID/order/amount/currency/status summaries |
| POST `/tools/verify_payment` | run_id, idempotency_key, payment_id | payment_id, verified, source |
| POST `/tools/match_payment` | run_id, idempotency_key, order_id | order_id, payment_id, order_status; persists PAYMENT_VERIFIED |
| POST `/tools/check_inventory` | run_id, idempotency_key, order_id | available, required product quantities; no reservation |
| POST `/tools/reserve_inventory` | run_id, idempotency_key, order_id | order_id, order_status, already_applied |
| POST `/tools/confirm_order` | run_id, idempotency_key, order_id | order_id, order_status, already_applied |
| POST `/tools/create_escalation` | run_id, idempotency_key, optional order_id | escalation_id, OPEN status; fixed HUMAN_REVIEW_REQUESTED reason |

`get_customer` is covered by identification; `get_order_status` by get_order.
`log_agent_action` is owned by the service transaction and is not a client-writable
route. No redundant endpoints or notification endpoints were added.

## Verification boundary

Normal mode has an unavailable provider adapter and returns
PAYMENT_PROVIDER_UNAVAILABLE from verify_payment. No external provider is simulated.
Explicit local `OGAFLOW_DEMO_MODE=true` selects StoredDemoVerifier, which accepts
only pre-existing DEMO-labelled seed evidence. It cannot invent new evidence.
The PaymentVerifier protocol permits future trusted adapter results to be persisted;
ID, customer, order, amount, currency, provider and reference must remain unchanged.

match_payment loads every payment for the bound customer; callers cannot pick a
single candidate to hide ambiguity. Existing exact amount/order/customer rules apply.

## Retries and tracing

An idempotency key identifies one logical invocation globally. Keep the same key
when retrying after a timeout. Replays return the stored result and original action
ID, with `replayed=true`; no duplicate audit row/effect is produced. Request hashes
bind keys to the complete tool/run/argument set. Hashes avoid storing raw phone input.
New keys create new audit attempts; persisted order/line state still prevents repeat
stock deductions, confirmations and duplicate open escalation conditions.

Use a new key for a fresh read: retrying a read key intentionally returns its original
snapshot. GET run trace reads the current audit summary without creating an action.
Run IDs use UUIDs. Confirmation does not mark a run COMPLETED because notification
and final agent workflow completion remain outside Phase 3.

## Phase 4A restricted boundary (2026-10-02)

The local compatibility route is `POST /agent/tools/{tool}`. Enabled logical names
are identify_customer, get_open_orders, get_order and find_payments. Bodies are `{}`
except get_order's `{"order_id":"<previously observed ID>"}`. No runtime identity,
phone, credential, key, verified flag or supplied business state is accepted.

Requires `OGAFLOW_AGENT_BOUNDARY_ENABLED=true`, nonempty OGAFLOW_TOOL_TOKEN, matching
Bearer authorization and a runtime-issued X-OgaFlow-Invocation header registered in
the same process. No HTTP route issues sessions or invocation handles. The runtime
binds operator-approved synthetic context and calls SessionRegistry.prepare before
delivery. These headers are not yet mapped to any verified Bimpe callback context.

With the boundary enabled, all original /runs and /tools endpoints return 403, even
with a valid bearer token. Without it, original Phase 3 routes remain local-only.

Successful transport preserves the original ToolResult fields and adds required
`next_action_allowed: boolean`. Every field is required and validated, including
per-tool data, identity and integer kobo. FAILED is HTTP 200 with reason_code,
human_review_required=true, an escalation_id, and next_action_allowed=false.
Malformed results stop with sanitized 502. Completed replay retains run/action/data
and sets replayed=true; a stopped attempt never regains continuation through replay.

Boundary errors use `{"detail":{"code":"..."}}`: 404 disabled; 401 bad/missing
auth; 503 auth missing or transient backend failure; 403 unknown invocation or
legacy bypass; 409 conflict/expired/stopped; 422 malformed request; 502 invalid
result; 500 unexpected backend failure. No exception text or credentials are returned.
Business failure is distinct from these transport/boundary errors.

Full lifecycle, gate evidence and limitations: [agent design](agent-integration-design.md).
