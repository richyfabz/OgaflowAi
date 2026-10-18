# LagosMart Demo Fixtures

All records are synthetic, with a fixed 2026-10-01 08:00 UTC timestamp. Phone values
are `DEMO-PHONE-001` etc.; they are intentionally not dialable. Run/action/escalation
tables start empty so the seed never implies an agent has actually run.

| Scenario | Customer | Order | Fixture / expected domain result |
|---|---|---|---|
| Golden success | CUS-001, Tunde Adebayo | OGA-1042 | 3 Vegetable Oil cartons × NGN 28,000; PAY-88921 NGN 84,000 SUCCESS; TRF92839201; stock 12 |
| Golden failure | CUS-002, Amaka | OGA-1051 | PAY-88922 NGN 80,000 vs NGN 84,000; AMOUNT_MISMATCH |
| No payment | CUS-003, Bisi | OGA-1060 | NO_PAYMENT |
| Pending | CUS-004, Chidi | OGA-1061 | PAYMENT_PENDING |
| Failed | CUS-005, Dami | OGA-1062 | PAYMENT_FAILED |
| Ambiguous payment | CUS-006, Emeka | OGA-1063 | Two distinct references; AMBIGUOUS_PAYMENT |
| Short stock | CUS-007, Fola | OGA-1064 | Requires 3 rice cartons; only 2 available |
| Multiple open orders | CUS-008, Grace | OGA-1065 / OGA-1066 | Selection requires clarification/review |
| No open order | CUS-009, Hassan | None | Stop and review |

User story: “I paid for my order yesterday but I haven't received confirmation.”
The fixed timestamp is fixture data, not a live interpretation of “yesterday.”

Phase 2 rehearses payment verification guards, reservation requirements, confirmation
and escalation transitions in memory. Success tests explicitly simulate a committed
reservation snapshot. **No stock is actually decremented, notification sent,
escalation persisted, or agent action recorded.**

Later full demo target: stock 12 → 9 once, order CONFIRMED, one notification and
traceable actions. Failure target: Amaka remains unconfirmed with an open escalation.

## Repeatability and reset preparation

```sh
.venv/bin/python scripts/seed_demo.py
.venv/bin/python scripts/reset_demo.py --output /tmp/ogaflow-demo-fresh.sql
```

The first regenerates tracked seed SQL; the second exclusively writes a new local
artifact. It never clears data or uses credentials. Apply `database/schema.sql`,
then seed SQL to a **fresh isolated database** after database setup is authorized.
Seed insertion into an occupied fixture namespace fails transactionally; it does
not silently overwrite business records. Actual database reset remains unimplemented
and must respect the destructive-operation approval gate.

## Phase 3 update

The persisted workflow is now verified against PostgreSQL 16.15: golden order
confirmation decrements oil stock to 9, and retries preserve that quantity. The
mismatch scenario persists an escalation and failed action. Service-generated
runs/actions are visible through GET /runs/{run_id}; no BimpeAI agent is connected.
Notifications remain unimplemented.

The offline helpers above remain available. Actual guarded local reset is now:

```sh
.venv/bin/python scripts/demo_database.py reset --confirm ogaflow_demo
```

It restores the isolated demo database to original seed state. See README for the
private local PostgreSQL setup, initialization and seed commands. No production
reset or remote connection was used.
