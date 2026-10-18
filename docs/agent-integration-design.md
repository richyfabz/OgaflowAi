# Agent integration design — Phase 4A

Updated 2026-10-02. Local boundary implemented; **live BimpeAI compatibility is
UNVERIFIED**. Phase 4B is not authorized. This document records the conditionally
approved design and the narrower implementation completed under that approval.

## Scope and architecture

One reasoning agent → deterministic adapter → restricted HTTP API → existing
OperationsService → repositories → PostgreSQL. There is no agent database access,
ORM, schema change, domain change or new dependency. HTTPX was already installed.

The ten approved logical capabilities remain the intended full design. Only these
four are issuable in Phase 4A:

| Capability | Model arguments | Phase 4A behavior |
| --- | --- | --- |
| identify_customer | `{}` | Uses operator-bound synthetic phone and expected customer; starts audited run |
| get_open_orders | `{}` | Retrieves the bound customer's sole open order |
| get_order | `order_id` | ID must have appeared in this attempt's get_open_orders result |
| find_payments | `{}` | Retrieves backend payment summaries, with integer kobo amounts |

verify_payment, match_payment, check_inventory, reserve_inventory, confirm_order
and create_escalation are disabled. Existing check_inventory requires verified
payment and can escalate an awaiting-payment order. It is unsuitable as a generic
Phase 4A inventory inspector; no replacement service/schema was introduced.

“Read-only” means no core business mutation through the enabled capabilities.
Identification and successful lookups persist runs/actions. Lookup failures can
persist existing audit/escalation effects and stop the run. Payment SUCCESS remains
a stored payment fact, not proof that an order has been matched or confirmed.

## Runtime boundary

`SessionRegistry.bind(phone=..., customer_id=...)` is a trusted **in-process operator
API**, with no HTTP counterpart. Demo operators bind Tunde/CUS-001 or Amaka/CUS-002.
It must never be wired directly to customer chat text. Bindings expire in 15 minutes;
explicit revoke removes their invocation records. Restart loses all handles and
fails closed. This is a local single-process harness, not durable conversation
mapping or a multi-worker deployment design.

`prepare(session, tool, arguments)` validates strict logical arguments, tool order,
observed order IDs and a 12-logical-call budget. It generates an opaque invocation
handle and retains the exact tool/arguments. One pending call is allowed per attempt.
Rejected preparation does not consume a call. Retries reuse the SAME returned ticket;
the runtime must not call prepare again to retry. The first identify invocation owns
the run; the agent never supplies phone/customer/run/key/authentication metadata.

The server maps a registered `X-OgaFlow-Invocation` header to that retained context,
checks exact tool/body equality, and derives the backend key as `agent:<handle>`.
No session/run/key field is accepted in logical tool arguments. Replay returns the
retained validated envelope with replayed=true. A lost result after backend commit
is recovered with persistent backend idempotency. Unknown handles, expiry, restart,
conflicts and revocation fail closed. Issuing fresh sessions is an operator action;
the model cannot reset its budget.

There is deliberately **no BimpeAI context-to-ticket binding yet**. Public docs do
not establish a trusted callback session/delivery context or a way to retain this
handle across actual platform callbacks. Do not place runtime identity into
model-generated tool parameters as a workaround. Determine this with owner access.
If recovery cannot use existing agent_run context safely, stop and propose the
smallest persistence change; no mapping table or field is currently approved.

## Authentication and bypass protection

`OGAFLOW_AGENT_BOUNDARY_ENABLED=false` by default. The agent route returns 404 when
disabled. When enabled, `OGAFLOW_TOOL_TOKEN` must be nonempty; otherwise return 503.
Callbacks require constant-time checked `Authorization: Bearer <token>` and a
registered invocation header. Missing/wrong credentials return 401.

When enabled, **all legacy /runs and /tools routes return 403**, including when the
caller has the valid callback token. This prevents bypass of the four-tool allowlist.
Health remains available. When disabled, Phase 3's legacy API is still unauthenticated
and is for local use only. No network exposure is authorized in either mode.

The callback token is separate from BIMPEAI_API_KEY and DATABASE_URL. It grants no
SQL access. Use a dedicated secret, never a database password or Bimpe team key.
No real credential was created or printed. Tests use explicitly synthetic values.

## Result and retry contract

All eight fields are required: run_id, action_id, status, data, reason_code,
human_review_required, replayed, next_action_allowed. Envelopes forbid extra fields,
coercion of booleans, unknown statuses and unsafe continuation. Per-tool data shapes
are validated, including strict integer kobo amounts and existing Order invariants.
Customer/run/order identity is checked against trusted context before returning
success. Backend business truth is not reconstructed from model prose.

HTTP 200 with status=FAILED remains a business failure, with reason code,
escalation ID, human_review_required=true and next_action_allowed=false. Malformed
results return a sanitized 502 and stop the attempt. The prompt also requires stop
on errors, review, missing data or denied continuation; server enforcement does not
depend on the prompt. Budget exhaustion and stopped runs deny continuation.

The local HTTPX transport sends an original request plus at most **one** retry on
transport errors or HTTP 503/504, reusing headers/body/ticket. No redirects; 10-second
HTTPX timeout. No retry on 200 business failure, malformed result, 401/403/409/422/429,
500 or 502. The receiving registry caps backend attempts at two per ticket and
serves completed replays without repeating the backend operation. Unknown backend
exceptions stop with sanitized 500; transient database/OS failures use 503. A new
invocation cannot proceed while an ambiguous call is pending.

**This proves only local adapter behavior.** It does not prove BimpeAI Custom API
callback retry behavior. Console SDK retries and Console request idempotency are
separate from tool delivery. No Bimpe retry defaults have been assumed.

Diagnostics record safe tool/status/run/action identifiers and fixed failure codes.
They omit invocation handles, authorization, phones, bodies and raw exceptions.
Existing agent_actions provides durable correlation after commit; database outages
cannot create durable audit entries in the unavailable database.

## Compatibility evidence

| Gate | Local evidence | BimpeAI runtime status |
| --- | --- | --- |
| Trusted session | VERIFIED: operator-bound synthetic customers, isolation, no identity arguments, expiry/restart rejection | UNKNOWN: trusted platform context forwarding |
| Invocation identity | VERIFIED: retained tickets, concurrent replay, lost-response recovery, backend key reuse | UNKNOWN: stable delivery identity or safe runtime ticket issuance |
| Tool authentication | VERIFIED: fail-closed token check and legacy bypass rejection | DOCUMENTED BUT UNTESTED: Custom API bearer configuration |
| Structured results | VERIFIED: real local HTTP envelope and strict validation; HTTP 200 FAILED stops | UNKNOWN: full envelope preserved in actual reasoning context |
| Retry ownership | VERIFIED: at most two local attempts, same ticket, no independent model retry | UNKNOWN: actual Custom API callback retries and controls |

DOCUMENTED BUT UNTESTED: [Custom API integration configuration](https://docs.bimpe.ai/docs/api/agents/configureCustomApi/)
supports base URL and bearer auth. [Tool registration](https://docs.bimpe.ai/docs/api/agents/createTool/)
describes URL/body/header templates and response mapping. These registration
features do not prove trusted runtime variable injection, callback retries or
preservation of structured business failures.

INFERRED: a hosted callback would need a reachable endpoint; loopback alone normally
cannot satisfy it. Exact Bimpe execution origin/private connectivity remains UNKNOWN.
No tunnel, public port, Vercel project or other host was provisioned.

## Credentials and next verification step

VERIFIED locally: BIMPEAI_API_KEY, legacy BIMPE_API_KEY and OGAFLOW_TOOL_TOKEN are
absent from environment/project .env at this checkpoint. No authenticated Bimpe
request, agent creation, tool registration or conversation has occurred.

Owner action:

1. Obtain a team API key in Bimpe Console → Team settings → API keys. Configure
   `BIMPEAI_API_KEY` in the local untracked `.env` or private shell environment, not
   chat, a committed file or a tool parameter. See [Bimpe authentication](https://docs.bimpe.ai/docs/getting-started/authentication/).
2. Supply the intended team/workflow/agent IDs, if already created. Initial access
   needs read permissions for the selected agent/workflow/integrations/tools and
   test conversation traces. Subsequent controlled setup needs permissions to
   manage that test agent's Custom API integration/tools and send/read test-channel
   messages. Exact scope strings must be confirmed in that workspace; do not infer
   them from generic documentation examples or request blanket admin access.
3. Configure a separate dedicated `OGAFLOW_TOOL_TOKEN` privately when live callbacks
   are ready. Later configure the same secret in Bimpe's Custom API bearer auth.
   Keep the boundary disabled outside the local harness pending connectivity approval.

After access: inspect the selected agent/configuration and available trusted runtime
context; establish the actual callback execution/network requirement. Stop for a
connectivity decision before any hosted setup. With approved connectivity, test
Tunde/Amaka isolation, duplicate/lost callback delivery identity, correct/wrong/missing
auth, complete success and HTTP 200 FAILED envelopes, then record actual callback
retry counts under timeouts/503/429. Never enable business mutations during these tests.

### Connectivity choices, if required — none implemented

| Option | Security and operational tradeoff | Hackathon time tradeoff |
| --- | --- | --- |
| Continue local harness | No public exposure; cannot pass live platform gates | Fastest, but live integration remains blocked |
| Temporary protected HTTPS tunnel | Synthetic data only; enabled boundary/token and retained runtime identity required; revoke token/close tunnel afterward | Usually shortest setup, but laptop uptime and ephemeral URL are fragile; compatibility still must be proved |
| Approved isolated hosted test service | Stable HTTPS and managed secrets; requires approved DB/network/context recovery design; process-local registry is unsuitable for serverless/multiple workers | More setup/rehearsal; not a production deployment |

These are conditional options, not an authorization request to choose hosting before
runtime requirements are known. An unsupported trusted context must be resolved
before exposing even a protected endpoint.

## Stop and Phase 4B

All five **live** gates remain UNVERIFIED. Stop at missing credentials/context and
unapproved connectivity. Once five gates pass, stop again for explicit Phase 4B
approval. Proposed Phase 4B: enable separately approved mutation tools in the same
single-agent architecture, test synthetic end-to-end business success/failure and
replay, and produce a notification-ready outcome. No notification delivery, voice,
SMS, WhatsApp, frontend, real banking or production deployment is included.
