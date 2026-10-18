# Business Rules

## Money and domain validation

Use integer kobo (`BIGINT` / strict Python integers), exclusively NGN in the MVP.
NGN 84,000 = 8,400,000 kobo; NGN 28,000 per carton × 3 = 8,400,000.
Reject floats, booleans, negative amounts, nonpositive quantities, empty orders,
duplicate product lines, and inconsistent line totals. Quantities fit PostgreSQL
INTEGER; monetary values fit BIGINT. Partial reservations are not supported.

## Order state machine

CREATED → AWAITING_PAYMENT → PAYMENT_VERIFIED → STOCK_RESERVED → CONFIRMED → FULFILMENT.

Any state before FULFILMENT can enter ESCALATED. ESCALATED and FULFILMENT have no
outgoing transitions except same-state replay. Recovery/reopening is outside this phase.
No skipped/backward transitions. Repeating a state returns the same snapshot after
rechecking applicable payment/reservation evidence; this performs no business effects.

- PAYMENT_VERIFIED requires one matching successful payment with trusted evidence.
- STOCK_RESERVED requires payment evidence and every line fully reserved.
- CONFIRMED and FULFILMENT require the same evidence and the same payment identity.
- Reservation planning requires PAYMENT_VERIFIED and a linked verified-payment ID.
- Stock must cover every unreserved line. Reject missing products and duplicate stock rows.
- Escalation is allowed without payment evidence so an unsafe case can stop immediately.

## Deterministic matching

Inputs are backend-loaded order and the complete set of potentially relevant payments.
An agent must not filter candidates to hide ambiguity or supply verification fields.

1. Select payments explicitly linked by order ID.
2. No candidate: `UNLINKED_PAYMENT` if the customer has an unassigned payment;
   otherwise `NO_PAYMENT`. No automatic inference from amount, name, or timing.
3. More than one candidate: `AMBIGUOUS_PAYMENT`, including successful plus failed
   attempts. Identical repeated candidate entries also fail closed.
4. Require same customer and exact amount/currency; reject mismatches.
5. Require SUCCESS plus non-null verification timestamp and source.
6. DEMO evidence is rejected by default. Only explicit local/demo calls enable it.
   PROVIDER evidence must eventually come from a backend provider adapter; merely
   constructing a Payment object does not verify a real payment.

No partial-payment aggregation, overpayment tolerance, refunds, date windows, or
reference inference. `(provider, reference)` is unique in SQL; separate payments
with different references for the same order remain ambiguous.

**Checkpoint proposal:** retain explicit order linkage for MVP automation. If actual
provider data lacks this link, approve a simple reference-based association rule
before integrating it. Unlinked payments currently always require review.

## Phase 3 persistence and idempotency

| Invariant | Enforcement and verification |
|---|---|
| Valid values/quantities/statuses | Pydantic plus PostgreSQL CHECK constraints; real database rejection tests |
| Exact order total | Domain hydration validates all persisted lines before mutation |
| Valid transitions | Every mutation service calls the approved pure transition rules |
| Verified matching payment | Complete customer candidate retrieval; trusted adapter boundary; SQL composite FK |
| Stock availability | Product row locks in sorted order and conditional decrements |
| All-or-nothing reservation | Decrement, line markers, order state and audit share a transaction |
| Repeated tool call | PostgreSQL advisory lock + persistent unique action key + request hash |
| New-key reservation/confirmation retry | Persisted line/state/timestamp markers prevent duplicate effects |
| Open escalation uniqueness | Order/reason or orderless run/reason partial unique indexes |
| Audit failure | Entire business transaction rolls back |
| Unsafe operation | Savepoint rollback, persisted escalation, failed action, stopped run |

Tested on real PostgreSQL: schema/seed, successful workflow, amount mismatch,
ambiguous/unlinked/pending/failed payments, no/multiple open orders, short stock,
wrong-owner/nonexistent orders, illegal confirmation, retries, rollback, and concurrent
inventory requests. Authentication and notification idempotency remain unimplemented.

An escalated run cannot perform further payment/reservation/confirmation mutations.
Explicit human escalation and read operations remain available. Successful order
confirmation leaves the run RUNNING pending the future notification/finalization step.
This avoids marking the full MVP workflow complete before communication exists.

SQL CHECK constraints do not establish all cross-row business truth. Services must
remain the mutation boundary; future ingestion/editing must use the same order-first
locking protocol. See [PostgreSQL constraints](https://www.postgresql.org/docs/16/ddl-constraints.html).

The demo verifier reuses explicit seed evidence. Real provider verification is
unavailable; injected trusted test adapters verify persistence without claiming a
live provider call. Adapter results cannot alter payment identity, association,
amount, currency, provider or reference.

Notification failure/timeout behavior remains a future requirement: preserve paid
order confirmation, record uncertainty and avoid blind resends. No notification is
sent in this phase. Resuming an escalated order requires a later approved rule.
