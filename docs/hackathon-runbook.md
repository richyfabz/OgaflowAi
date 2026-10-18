# Hackathon Runbook — Preparation

## Competition gate

Phase 2/3 are pre-event preparation (2026-10-01/02). Preserve git history and disclose
this work. Record the briefing's rules on pre-existing code, fixtures, tests and
services; reuse only permitted artifacts. Never conceal preparation. The 120-minute
schedule is a target; a timed end-to-end rebuild has not been verified.

## Verified local foundation

Use Python 3.10. Follow README for dependency installation and local PostgreSQL build.
The approved minimal driver is psycopg[binary]; no ORM/migration framework is required.
Build PostgreSQL before any timed rehearsal if competition rules permit that setup.

```sh
.venv/bin/python scripts/local_postgres.py start
.venv/bin/python scripts/demo_database.py init
.venv/bin/python scripts/demo_database.py seed
.venv/bin/pytest -q
```

Initialize/seed once. If already initialized, use the guarded reset instead:

```sh
.venv/bin/python scripts/demo_database.py reset --confirm ogaflow_demo
```

Reset can only target the exact project-local cluster/demo database and runs in one
transaction. The reset program accepts no remote URL. Integration tests create/drop
only their own disposable schemas in this same private cluster.

## Configuration and API rehearsal

Use OGAFLOW_DEBUG, default false; never rely on host DEBUG. Invalid application
boolean values fail validation. Future Vercel environment variables must use
OGAFLOW_DEBUG; no production deployment is performed here.

```sh
export DATABASE_URL="$(.venv/bin/python scripts/demo_database.py dsn)"
export OGAFLOW_DEMO_MODE=true
.venv/bin/python -m uvicorn app.main:app --app-dir backend
```

Call POST /runs with DEMO-PHONE-001 and a fresh idempotency key. Use the returned
run ID for get_open_orders → find_payments → verify_payment → match_payment →
check_inventory → reserve_inventory → confirm_order. Inspect GET /runs/{run_id}.
Reuse the same key for retries; new keys represent new attempts.

Expected local result: OGA-1042 CONFIRMED; oil stock 12 → 9 once; persisted audit.
Amaka (DEMO-PHONE-002 / OGA-1051) produces AMOUNT_MISMATCH, persisted escalation and
unchanged stock. Notifications/agent actions here are service tool calls, not proof
of a connected BimpeAI agent or live payment/messaging integration.

Keep the API local because authentication is out of scope. Stop PostgreSQL with:

```sh
.venv/bin/python scripts/local_postgres.py stop
```

## Still required before competition integration

- Briefing permission to reuse prepared code/specifications.
- Dependency lock/clean installation and a timed rehearsal.
- BimpeAI/tool, voice and communication contract validation in a later phase.
- Approved credentials/paid services and Supabase/Vercel verification when needed.
- Notification deduplication/failure behavior and a complete end-to-end demo.

Phone → web voice → text must share one agent and backend. Do not present demo
payment evidence or test adapters as real provider verification.

## Intended 120-minute schedule

| Minutes | Work |
|---|---|
| 0–10 | Permitted agent/platform setup |
| 10–25 | Instructions and restricted tools |
| 25–45 | Business API integration |
| 45–60 | Golden success |
| 60–75 | Voice |
| 75–90 | Communication |
| 90–100 | Escalation |
| 100–110 | End-to-end and retry tests |
| 110–115 | Guarded demo reset |
| 115–120 | Stop coding; prepare presentation |

If briefing restrictions make this schedule unrealistic, adjust scope with the
owner. Phase 3 ends before BimpeAI integration.

## Phase 4A local compatibility checkpoint

Do not run a public endpoint. No Bimpe agent is connected. Local synthetic tests:

```sh
.venv/bin/python scripts/local_postgres.py status
.venv/bin/pytest -q backend/tests/integration/test_agent_boundary.py backend/tests/unit/test_agent_transport.py
.venv/bin/pytest -q
```

Tests create/drop private PostgreSQL test schemas, use synthetic bearer values and
in-process clients, and do not require Supabase/Bimpe credentials or start an HTTP
listener. Keep `OGAFLOW_DEBUG` as the application setting; no `DEBUG=false` prefix
is needed. Keep `OGAFLOW_AGENT_BOUNDARY_ENABLED=false` outside this harness for now.
Enabling the boundary blocks ALL legacy /runs and /tools endpoints.

Local operator context uses SessionRegistry.bind with DEMO-PHONE-001/CUS-001 (Tunde)
or DEMO-PHONE-002/CUS-002 (Amaka). Only trusted operator code may call bind/prepare.
Retain the returned Invocation for retry; never create another ticket for the same
logical call. There is no remote registration endpoint. Expiry is 15 minutes; revoke
a session when finished. Restart intentionally loses context; do not use multiple
workers, serverless hosting or attempt to resume an old conversation with new keys.

Only identify_customer/get_open_orders/get_order/find_payments are exposed. Payment
lookup cannot authorize matching/reservation/confirmation. Failures may create
existing escalation/audit records. No notifications are delivered.

Live verification is blocked on credentials and platform runtime evidence. Configure
BIMPEAI_API_KEY privately (Console → Team settings → API keys) and later a distinct
OGAFLOW_TOOL_TOKEN for callback bearer auth. No value belongs in logs, chat or source.
Exact functional permissions, next tests and conditional connectivity tradeoffs are
in [agent-integration-design.md](agent-integration-design.md). Do not open a tunnel,
public port or hosted service without the required decision. All five live gates
must pass before requesting Phase 4B approval; passing them does not enable mutations.
