# Decision Log

All decisions below are dated **2026-10-01** and stay within the approved Phase 2
scope. No architectural approval was required. External connections remain gated.

## D-001 — Integer kobo

- Decision: strict Python integers / PostgreSQL BIGINT for NGN minor units.
- Context: deterministic amounts and equality without binary floating point.
- Reason: NGN 84,000 is exactly 8,400,000 kobo; no rounding policy is needed.
- Alternatives: NUMERIC/Decimal (allowed but unnecessary for current integer prices).
- Architecture impact: representation within existing models/schema only.
- Approval status: authorized by specification section 37.

## D-002 — Pure service rules and immutable snapshots

- Decision: Pydantic domain snapshots, enums, pure transition/matching/stock checks.
- Context: Phase 2 establishes rules before repository/API implementation.
- Reason: test invariants without credentials or pretending to persist mutations.
- Alternatives: put rules in endpoints or agent tools (violates separation); build
  repositories now (crosses current checkpoint scope).
- Architecture impact: preserves API → service → repository → database.
- Approval status: within approved scope.

## D-003 — Conservative payment matching

- Decision: one explicitly order-linked payment, same customer, exact NGN amount,
  SUCCESS and verification evidence; all additional candidates require review.
- Context: no approved inference/timing/partial-payment policy or provider adapter.
- Reason: fail closed on uncertainty; no invented financial matching heuristics.
- Alternatives: amount-only/timing inference or choose one of multiple attempts
  (unsafe without a specified policy).
- Architecture impact: service logic only; DEMO evidence needs explicit opt-in.
- Approval status: conservative default within scope. Reference-based linking is
  proposed at the checkpoint only if future provider data lacks an order ID.

## D-004 — Reservation and idempotency representation

- Decision: per-order/product reserved quantity is zero or full line quantity;
  order markers and unique action keys support future transactional mutations.
  Partial unique indexes prevent duplicate open escalation conditions.
- Context: no reservation/outbox entity is specified; repeats must be safe.
- Reason: stays within the eight approved entities and supports atomic replay checks.
- Alternatives: new reservation entity or messaging infrastructure (not needed now).
- Architecture impact: schema only; transactional enforcement is not yet implemented.
- Approval status: within approved schema design scope.

## D-005 — Offline fixtures and reset preparation

- Decision: synthetic, fixed IDs/timestamps, non-dialable phone placeholders; one
  Python fixture generator renders SQL and supplies tests. Reset helper only writes
  an exclusive local artifact for a fresh database.
- Context: no PostgreSQL tools or running Docker daemon; no destructive operation authorized.
- Reason: reproducible artifacts without contacting production or faking verification.
- Alternatives: execute remote seeds (credentials/approval required), destructive
  reset (approval required), SQLite substitution (does not validate PostgreSQL).
- Architecture impact: development scripts only; database target unchanged.
- Approval status: no approval needed for artifact preparation. Actual clearing of
  database state remains gated.

## D-006 — State machine terminal behavior

- Decision: allow escalation from each pre-FULFILMENT state; ESCALATED and FULFILMENT
  allow only same-state replay. Forward transitions require their full evidence.
- Context: the specification defines no human recovery or fulfilment completion flow.
- Reason: avoid inventing a return-to-automation path or weakening payment/stock guards.
- Alternatives: implicit recovery/reopening (requires a later explicit rule).
- Architecture impact: canonical MVP flow preserved, no new state.
- Approval status: Phase 2 semantic refinement; recovery requires future review.

# Phase 3 decisions — 2026-10-02

Phase 2 decisions above remain approved and unchanged. The owner explicitly approved
the debug-variable rename, psycopg[binary], and minimum local PostgreSQL setup.

## D-007 — Namespaced debug configuration

- Decision: only OGAFLOW_DEBUG controls the existing debug setting; default false.
- Context: DEBUG=release is inherited from the process launching the shell, including
  non-login execution. No assignment was found in checked shell startup files; its
  original source is unknown. Pydantic previously consumed the unprefixed variable.
- Reason: avoid host/application collision while preserving boolean validation.
- Alternatives: launch wrappers/unsetting DEBUG (special commands and hidden overrides),
  accepting arbitrary booleans (weakens validation).
- Architecture impact: environment variable contract only. Invalid OGAFLOW_DEBUG
  still fails. Development/tests need no manual DEBUG prefix. Future Vercel settings
  use OGAFLOW_DEBUG; no deployment performed.
- Approval status: explicitly approved by owner before implementation.

## D-008 — Minimal PostgreSQL driver

- Decision: psycopg[binary]==3.3.6 with short-lived synchronous connections and sync
  FastAPI tool routes. No global connection pool; 5s connection/lock limits and 10s
  statement limits bound ordinary failures.
- Context: approved persistence layer requires a Python driver, including local tests.
- Reason: minimal dependency and explicit SQL within repositories; supports Python 3.10.
- Alternatives: SQLAlchemy/Alembic (not needed, new approval required), SQLite (prohibited).
- Architecture impact: implements existing repository/database boundaries.
- Approval status: explicitly approved. Supabase/Vercel compatibility remains an
  integration target; neither service was connected or deployed.

## D-009 — Private project-local PostgreSQL

- Decision: PostgreSQL 16.15 source build/install/data/socket under ignored `.local/`;
  socket directory permissions 0700, no TCP listener or system service.
- Context: no PostgreSQL executables; Docker daemon unavailable. Homebrew proposed
  shared-library upgrades and was stopped before installation. Source SHA256 matched
  the official distribution checksum.
- Reason: real PostgreSQL verification without remote credentials or shared upgrades.
- Alternatives: Supabase credentials (unnecessary for local verification), Homebrew
  dependency upgrades (broader machine changes), simulated SQL (insufficient evidence).
- Architecture impact: local development tooling only; production target unchanged.
- Approval status: authorized minimum local environment. No new cloud infrastructure.

## D-010 — Atomic operations, locking and audit

- Decision: one outer transaction per tool; savepoint for attempted business work;
  key/run/order/payment/product locks and deterministic row order. Audit failure
  rolls back business changes. Domain rejection rolls back attempted work and commits
  a failed action plus escalation and permitted stop-state transitions.
- Context: retries/concurrency must not oversell stock or leave unrecorded effects.
- Reason: native PostgreSQL locks and existing schema suffice; no distributed lock system.
- Alternatives: in-memory locks (not persistent), external locks/queues (unapproved).
- Architecture impact: service coordinates; repository owns SQL and lock acquisition.
- Approval status: within approved Phase 3 scope; pure domain semantics unchanged.

## D-011 — Persistent retry records within agent_actions

- Decision: global idempotency key, request hash, stored safe result and original action
  ID. Replays reuse the row; new-key attempts recheck persistent business markers.
- Context: existing schema already includes a unique action key; no new entity needed.
- Reason: replay/conflict behavior is explainable and survives separate connections.
- Alternatives: separate idempotency table (unnecessary entity), agent-only deduplication
  (unsafe). Read retries return the original snapshot; fresh reads need a new key.
- Architecture impact: existing eight entities only. Confirmation leaves run RUNNING
  until future notification/finalization; no false full-workflow completion claim.
- Approval status: within approved scope.

## D-012 — Restricted tool API and explicit demo verification

- Decision: Pydantic DTOs reject extra fields; services generate audit/escalation
  details; no raw logging or verification-evidence endpoint. Business rejection is
  HTTP 200 with FAILED/reason/escalation; transport failures use 404/409/422/503.
- Context: agent integration is deferred, but contracts must be usable and safe.
- Reason: clear tool outcome distinct from transport failure; cannot submit business
  proof through API. Real verification adapter is unavailable by default. Demo mode
  reads only existing labelled seed evidence and is restricted to development/test.
- Alternatives: pretend to verify payments (prohibited); prematurely add real provider
  credentials/authentication (out of scope). Test adapters are explicitly synthetic.
- Architecture impact: no business SQL in API/services; no agent integration.
- Approval status: within approved scope. API remains local pending authentication.

## D-013 — Guarded deterministic demo reset

- Decision: a separate local-only CLI initializes/seeds/resets ogaflow_demo. Reset
  requires the exact database name confirmation and checks database, role, Unix
  socket connection and exact server data directory before truncating all eight
  demo tables and reseeding in one transaction. No remote DSN argument is accepted.
- Context: repeated demonstrations need actual reset, while prior offline scripts
  must remain useful and existing tests must be preserved.
- Reason: local destructive scope is explicit and mechanically restricted.
- Alternatives: arbitrary DATABASE_URL reset (unnecessary production-target risk),
  replacing the offline helper (breaks approved existing behavior).
- Architecture impact: local tooling only; SQL schema semantics unchanged.
- Approval status: authorized Phase 3 reset/setup scope; no production operation.

## 2026-10-02 — Phase 4A conditional approval

**Owner decision:** implement compatibility and safe boundary only. Retain one
reasoning agent, deterministic restricted tools, existing services/repositories,
PostgreSQL, integer kobo and runtime-owned identity. Use existing HTTPX, no Bimpe SDK.
No domain/schema/state-machine change and no Phase 4B mutation access.

**Implementation decisions:** expose only identify_customer/get_open_orders/get_order/
find_payments. Keep inventory inspection disabled because the existing check requires
verified payment and can escalate an awaiting-payment order. Enable boundary by an
explicit default-false flag; when enabled, disable every legacy business route to
prevent credential-based allowlist bypass. Separate callback token from Bimpe team key.

Use operator-only process-local binding and retained invocation tickets for local
verification. Unknown/restarted/expired context stops; no automatic reconstruction,
new mapping table or model-supplied runtime identity. One pending call, 12 logical
calls and original-plus-one retry. Preserve/validate complete envelopes and stop on
business failure regardless of HTTP 200. No schema or new dependency is necessary.

**Evidence:** local behavior VERIFIED by tests; platform registration/auth features
DOCUMENTED BUT UNTESTED; hosted reachability need INFERRED; actual trusted context,
delivery identity, envelope preservation and callback retry controls UNKNOWN.
See [design and credential/connectivity stop](agent-integration-design.md).

**Approval gate:** credentials/context required to continue live Phase 4A; connectivity
requires its own decision before exposure. All five live gates must pass, then stop
for explicit Phase 4B approval. No live tool registration, deployment or message sent.
