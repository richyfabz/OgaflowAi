# Failure Matrix — Phase 3

VERIFIED means executed tests. PostgreSQL-backed tests use real PostgreSQL 16.15,
not SQLite or mocked SQL. External integrations remain UNVERIFIED/out of scope.

| Case | Required/current behavior | Verification |
|---|---|---|
| Unknown customer | Run with no customer, orderless escalation, failed identification action | VERIFIED persistence/retry |
| No open order | NO_OPEN_ORDER; stop run and escalate | VERIFIED integration |
| Multiple open orders | MULTIPLE_OPEN_ORDERS; do not select one | VERIFIED integration |
| No payment | NO_PAYMENT; no payment/stock progression | VERIFIED integration |
| Pending/failed payment | PAYMENT_PENDING / PAYMENT_FAILED | VERIFIED integration and domain |
| Incorrect amount | AMOUNT_MISMATCH; order ESCALATED, stock unchanged | VERIFIED integration |
| Ambiguous payments | AMBIGUOUS_PAYMENT before choosing candidate | VERIFIED integration |
| Duplicate provider reference | Reject at SQL unique constraint | VERIFIED PostgreSQL |
| Unlinked payment | UNLINKED_PAYMENT; no amount-only inference | VERIFIED integration |
| Success without evidence | PAYMENT_UNVERIFIED | VERIFIED domain/adapter tests |
| Demo evidence in normal mode | DEMO_PAYMENT_NOT_ALLOWED | VERIFIED integration |
| Real payment verification requested | PAYMENT_PROVIDER_UNAVAILABLE; no invented evidence | VERIFIED adapter unit test; real provider UNVERIFIED |
| Provider timeout | Stop without evidence; review | Real provider integration deferred |
| Insufficient stock | Roll back attempted reservation; escalate | VERIFIED integration |
| Concurrent stock contention | One of two three-carton requests wins with stock three | VERIFIED concurrent PostgreSQL test |
| Missing/duplicate product | Reject inventory requirements | VERIFIED domain tests |
| Database/audit failure | Roll back whole transaction; safe 503 for driver errors | VERIFIED injected failures against PostgreSQL/API |
| Domain rejection after partial work | Roll back savepoint; preserve failure/escalation only | VERIFIED integration |
| Duplicate tool call, same key | Original action/result; one effect | VERIFIED sequential/concurrent integration |
| Retry with new key | New audit attempt, persisted effect reused | VERIFIED sequential/concurrent integration |
| Reuse key for different request | IDEMPOTENCY_KEY_CONFLICT, HTTP 409 | VERIFIED integration/API |
| Repeated escalation across runs | One open order/reason escalation | VERIFIED integration and SQL uniqueness |
| Nonexistent/wrong-owner order | ORDER_NOT_FOUND; no foreign order mutation | VERIFIED integration |
| Nonexistent payment | PAYMENT_NOT_FOUND with failed action/escalation | VERIFIED integration |
| Illegal confirmation | Reject and escalate; no confirmation timestamp | VERIFIED integration + 49-pair domain matrix |
| Injected business truth in API | Extra fields rejected, HTTP 422 | VERIFIED API |
| Invalid OGAFLOW_DEBUG | Configuration validation fails | VERIFIED unit test |
| Host DEBUG=release | Ignored by OgaFlow | VERIFIED plain pytest/config tests |
| Reset outside private local target | Refuse before destructive SQL | VERIFIED safety unit tests; local reset rehearsed |
| Notification failure | Keep confirmation; review delivery uncertainty | Deferred, no notifications implemented |
| Topic change / uncertain transcription | Reassess or clarify; do not guess | Agent/voice phase deferred |
| Agent/phone platform failure | Preserve state and offer shared text fallback | Integration deferred |

A failed business tool returns HTTP 200 with status FAILED and a stable reason.
Database outages cannot reliably persist their own audit; the transaction fails
closed and the caller retries with the same key. No automatic provider retry,
notification retry, or recovery from ESCALATED is implemented.

## Phase 4A compatibility failures (2026-10-02)

| Failure | Enforced local outcome | Evidence status |
| --- | --- | --- |
| Boundary disabled / token unconfigured | 404 / 503; no tool execution | VERIFIED |
| Missing or wrong bearer | 401 | VERIFIED |
| Valid token calls legacy mutation route | 403; no bypass | VERIFIED |
| Unknown/expired/revoked/restarted invocation | Reject; never generate replacement context | VERIFIED |
| Body/tool differs from registered invocation | 409 | VERIFIED |
| LLM supplies runtime metadata | Preparation rejects extra fields; delivery rejects mismatched body | VERIFIED |
| Cross-customer/unobserved order ID | Rejected before backend lookup | VERIFIED |
| Duplicate concurrent delivery | Same action/result; replay flag; one persisted action | VERIFIED |
| Response lost after commit | Same ticket/key recovers persisted result | VERIFIED |
| Local transient failure twice | Stop; no third backend attempt | VERIFIED |
| HTTP 200 business FAILED | Preserve reason/review/escalation; deny continuation | VERIFIED |
| Malformed envelope/data or binding mismatch | Sanitized 502; stop | VERIFIED |
| Twelve logical calls completed | Deny further execution; replay cannot restart attempt | VERIFIED |
| Missing Bimpe credentials | No authenticated connection; stop at owner action | VERIFIED absence |
| Bimpe trusted context, response mapping, retry semantics | Mutation gate stays closed | UNKNOWN |
| Bimpe configured bearer auth capability | Available in registration docs; no live callback proof | DOCUMENTED BUT UNTESTED |
| Hosted callback cannot reach loopback | Would require connectivity decision | INFERRED; exact runtime requirement UNKNOWN |

Lookup audit/escalation effects remain possible. No inventory/payment/order mutation
tool is enabled. Adapter diagnostics omit raw payloads, credentials and exceptions.
