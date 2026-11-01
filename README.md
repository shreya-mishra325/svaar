![Svaar](https://github.com/RohanOnKeys/cerebro/blob/main/assets/Copy%20of%20Svaar.gif?raw=true)

# Svaar

Public deployment target: [one Free Render web service and Free Postgres](docs/RENDER_DEPLOYMENT.md).
The private Compose deployment remains a fallback; no Cloudflare setup is required for Render.

Svaar is a voice-enabled agent for engineering incidents. It lives in team chat, watches CI, rebuilds what happened from recorded events, checks status claims against evidence, calls engineers by phone to verify them, and negotiates conflicting constraints into a plan that deterministic code has validated.

**Models propose, deterministic code enforces, Bolna speaks.**

- **Models** propose. The chat LLM drafts replies and tool calls; typed decisions come from deterministic heuristics or an optional structured classifier on the same chat model.
- **Deterministic code** validates, authorizes and acts. Nothing a model says runs a tool by itself.
- **Bolna** is the voice layer. It turns the caller's speech into text, hands it to Svaar, speaks Svaar's reply and reports the final transcript.

Svaar has one agent. Chat messages and phone calls reach the same tool loop, the same tool registry and the same approval gate.

Current implementation includes the shared chat/voice agent, identity and confirmation
gates, signed CI observations, incidents/claims/evidence, guarded jobs, negotiation,
isolated replay and authenticated Bolna turn/status routes. Most provider-domain
flows are tested offline; this does not establish live acceptance.

For the current private deployment and verified limits, read
[DEPLOYMENT.md](docs/DEPLOYMENT.md) and [DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md).
The local demo API/database/restricted origin are verified; public HTTPS and the
complete Telegram/GitHub/voice demo remain pending. Cerebro is a reference only.

## How it works

```mermaid
flowchart TD
    Chat["Chat channels"] <--> Caspian["Caspian SDK"]
    Caspian <--> Agent["agent"]
    Agent --> Actions["actions"]
    Caller["Engineer on a call"] <--> Bolna["Bolna"]
    Bolna -- "caller text per turn" --> Voice["voice"]
    Voice -- "reply text" --> Bolna
    Voice -. "turn runner" .-> Agent
    Actions --> Incidents["incidents"]
    Actions --> Approvals["approvals"]
    Actions --> Resolution["resolution"]
    Actions --> Replay["replay"]
    Incidents --> Decisions["decisions"]
    Sources["GitHub, Jira"] --> Integrations["integrations"]
    Integrations --> Incidents

    classDef external stroke-dasharray: 4 3
    class Chat,Caspian,Caller,Bolna,Sources external
```

Dashed boxes are outside Svaar.

Every tool call, from chat or from a call, goes through one path in `actions`: role and organization check, argument validation, risk tier, and for risky actions a confirmation that the owner must give with a one-time code on a different verified channel. Calls Svaar places are bounded missions that expose only the tools the mission needs.

## Modules

Svaar is a FastAPI modular monolith. Each package owns its tables, models and routes.

| Package | Responsibility |
| --- | --- |
| `agent` | Channel transports, inbound dedupe, conversation memory, LLM adapter, tool loop, prompts, outbox sender |
| `identity` | Organizations, principals, roles, channel bindings (including verified phones), invites |
| `actions` | Tool registry, argument validation, authorization, risk tiers, dispatcher, execution records |
| `incidents` | Observed events, timelines, claims, evidence, failure fingerprints |
| `decisions` | Decision engine interface, typed decisions, confidence policy, heuristic engine and fallback, decision audit |
| `voice` | Bolna client, call missions, turn routes, status webhook, voice authentication |
| `resolution` | Constraints, negotiation agents, deterministic validator, exception draft |
| `replay` | Isolated simulation, separate from observed events and live side effects |
| `approvals` | Confirmations and confirmation decisions |
| `integrations` | GitHub App and webhook, Jira |
| `jobs` | Guarded polling loop for acknowledgement deadlines, outbox retries and stale confirmations |
| `web` | Future operator interface |
| `api` | Router composition, infrastructure probes and error conventions |

`app.py` composes modules and owns startup and shutdown. `config.py`, `db.py` and `logging.py` provide shared infrastructure. Feature modules may depend on these utilities; shared utilities must not import feature modules. Do not import the application from domain code.

Two boundaries matter most:

- `agent` and `voice` never import each other. `voice/contracts.py` defines the synchronous `TurnRunner` protocol. Application startup injects the agent's structurally compatible executor through the protocol. Both packages may depend on `actions` and `identity`.
- Replay output never enters `events`. Observations and simulations stay in separate tables.

Every business tool call must pass through `actions`; neither a transport nor a model may
call a feature handler directly. The voice intent router and transcript-usability gate run in the shared agent/decision path. The deterministic mission guard must not allow either
model to expand a call's mission or tool allowlist. These controls are implemented and tested; provider acceptance remains separate.

External SDKs and HTTP contracts belong behind adapters, never in deterministic business rules.

## Processes

The app, chat gateway, CI worker and restricted provider ingress use the same
application image and PostgreSQL database. The gateway persists its cursor and
heartbeat; the CI worker leases durable jobs and records a process heartbeat.
Call placement remains explicit through the guarded operator dispatch CLI.

Use compose.yaml for development. For the isolated hardened demo use
compose.demo.yaml as described in [DEPLOYMENT.md](docs/DEPLOYMENT.md).
Only the restricted ingress belongs behind the named tunnel; operator routes
and PostgreSQL remain private. A temporary Quick Tunnel is unsuitable for the
custom LLM because it does not support SSE.

## Local configuration

Use one private .env for all local commands. .env.example is a blank template;
never overwrite an already configured .env with it. Legacy demo/render/control/
enrollment/test dotenv files are archived outside the repository. Settings read
.env automatically; do not layer multiple --env-file arguments.

The current demo .env targets Render's external PostgreSQL URL with required TLS.
Ordinary host API/gateway/migration commands therefore use that database. The
fresh local installation steps below assume a local database URL; do not run them
against the demo by accident. SVAAR_LOCAL_DATABASE_URL preserves the earlier local
URL as a reference. Docker Compose constructs a separate internal DB URL.
Private fallback credentials use SVAAR_DEMO_* in the same .env. See
[Render deployment](docs/RENDER_DEPLOYMENT.md) for dashboard fields; keep its internal
DB URL unchanged and do not upload the whole private file. Tests require their own
disposable database via SVAAR_TEST_DATABASE_URL.

## Install and run locally

Requires Python 3.11+, Docker with Compose, and uv 0.11.29. Dependencies live in `pyproject.toml`; `uv.lock` fixes resolved versions for development, containers and CI.

```sh
python -m pip install uv==0.11.29
uv sync --locked
```

Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell or `cp .env.example .env` in a POSIX shell). The example credentials are for local development only.

```sh
docker compose up -d --wait db
uv run --locked alembic upgrade head
uv run --locked uvicorn svaar.app:create_app --factory --reload --no-access-log --no-proxy-headers
```

Visit `http://127.0.0.1:8000/health`, `/ready` and `/docs`.

`/health` reports process liveness without touching the database. `/ready` executes `SELECT 1`: 200 when PostgreSQL answers, or a sanitized 503 when it does not. It is a connectivity probe, not a schema-version or external-provider readiness check. Startup is lazy so a database outage does not prevent liveness checks. SQL connection and query timeouts default to three seconds; DNS, OS and connection-pool behavior can add time to that budget.

## Run everything in containers

```sh
docker compose up --build --wait app
docker compose logs app
docker compose down
```

Compose starts PostgreSQL, waits for its health check, runs migrations as a one-shot service,
then starts the unprivileged `app`. PostgreSQL persists in the `postgres_data` volume. `down`
preserves data. Do not delete the volume unless its data is disposable.

The gateway is an opt-in implemented runtime, not a placeholder. Its --check
mode tests only database infrastructure. Starting it normally can process existing
incoming messages and send replies; get authorization before a live startup.
Its --status mode checks a fresh persisted heartbeat. The ci profile starts
the read-only log worker only after its App configuration is ready.

```sh
docker compose run --build --rm gateway --check
```

Only localhost ports 8000 and 5433 are published. `.env` and `plans/` are excluded from the image build context, not from the repository. Docker image tags are versioned but not digest-pinned.

Compose constructs its internal database URL from `POSTGRES_*` and uses host `db`, port 5432; the host application's URL uses localhost:5433. Changing `SVAAR_DATABASE_URL` alone does not change Compose's internal database. The provided local passwords use URL-safe characters; percent-encode reserved characters in custom connection URLs. Existing PostgreSQL volumes retain their original users and passwords when environment values change.

## Configuration

Settings read environment variables before optional `.env` values. Invalid settings fail application construction; importing modules does not require credentials or create connections. Secrets have no defaults.

### Infrastructure

| Variable | Default / requirement |
| --- | --- |
| `SVAAR_DATABASE_URL` | Required complete `postgresql://` or `postgresql+psycopg://` URL |
| `SVAAR_ENVIRONMENT` | `development`; also `test` or `production` |
| `SVAAR_LOG_LEVEL` | `INFO`; DEBUG, WARNING, ERROR, CRITICAL also supported |
| `SVAAR_DATABASE_TIMEOUT_SECONDS` | `3`, integer from 1 to 30 |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local Compose initialization only |
| `SVAAR_TEST_DATABASE_URL` | Optional dedicated database for PostgreSQL tests |

For a local database using a different published port, align the port in the
private `.env` URL with `docker compose port db 5432`; do not change shared
Compose defaults for another developer. The migrated Mac currently uses 5434.
Use a separate disposable database for tests. When its URL is stored in the local
`.env`, load it explicitly so PostgreSQL tests do not silently skip:

```sh
uv run --locked --env-file .env pytest -p no:cacheprovider -q
```

That URL must name the dedicated test database, never the development database:
database fixtures truncate domain tables. Restart Uvicorn after editing `.env`;
Python file reload does not ensure new environment values have been loaded.

### Active feature settings

| Variable | Default / requirement |
| --- | --- |
| `SVAAR_OPERATOR_TOKEN` | Unset; at least 32 characters. Unset makes operator routes return 503. Compose passes it to `app` only |
| `SVAAR_INVITE_TTL_HOURS` | `72`, from 1 to 720 |
| `SVAAR_CONFIRMATION_TTL_SECONDS` | `600`, from 60 to 3600 |
| `SVAAR_CONFIRMATION_MAX_ATTEMPTS` | `5`; wrong codes beyond this lock the owner's pending confirmations |
| `SVAAR_ALLOW_SAME_CHANNEL_CONFIRMATION` | `false`; enable only for a demo without a second verified channel |
| `SVAAR_POLICY_HIGH`, `SVAAR_POLICY_LOW` | `0.85` and `0.55`; low must be below high. Placeholders until tuned on labelled transcripts |
| `SVAAR_ESCALATION_JOBS_ENABLED` | `false`; gateway-only local escalation intent preparation, no dialing |
| `SVAAR_ESCALATION_AFTER_SECONDS` | `600`; acknowledgement grace after confirmed owner-alert delivery, 60 to 86400 |
| `SVAAR_ESCALATION_COOLDOWN_SECONDS` | `3600`; minimum interval between intents for one recipient, 60 to 86400 |
| `SVAAR_ESCALATION_BATCH_SIZE` | `10`; bounded jobs per gateway cycle, 1 to 50 |
| `SVAAR_CLASSIFIER_ENABLED` | `false`; optional typed classifier reusing the configured chat model |
| `SVAAR_LLM_BASE_URL`, `SVAAR_LLM_API_KEY`, `SVAAR_LLM_MODEL` | Set all three or leave all unset. Base URL must use HTTP(S) without credentials/query/fragment; the API key is secret |

When configured, application lifespan creates `app.state.agent_loop` without making a provider
request and closes inference/HTTP resources on shutdown. When unset, that state is `None`.
Compose passes model and shared decision/confirmation policy settings to app/gateway,
not migrations. The operator token and invite TTL remain app-only. Configured authenticated voice routes use the same loop; live acceptance remains pending. By default SVAAR_CLASSIFIER_ENABLED=false keeps conservative
heuristic-only decisions, so composed voice gates request clarification.

Jev was removed on 2026-10-27, including its adapter and provider-specific tests.
The optional structured classifier is implemented using the existing chat model.
Set SVAAR_CLASSIFIER_ENABLED=true locally and restart the relevant processes to
enable it; the three SVAAR_LLM_* settings must already be configured. No extra
provider key is used. Compose forwards this switch only to app/gateway.

The voice gate performs a local conservative speech precheck, then at most one
classifier request containing usability and intent together. Each slot is
validated/audited independently. Invalid or missing slots fall back with confidence
zero and defer; heuristic confidence never authorizes execution. Six-digit code
candidates can reach the classifier but still require exact code comparison in
actions. Short unclear speech never consumes a verification attempt.

Classifier inference shares the voice deadline, has no retries/tools, and cannot
dispatch actions. A late classifier result cannot reach the reply model or tools.
New decision rows use source=model or fallback; old provider audit rows are kept
unchanged. Confidence is an uncalibrated score, not evidence. Real model acceptance
and threshold tuning remain unverified; all classifier tests use fake inference.

The HTTP contract follows the provider's documented
[OpenAI compatibility](https://console.groq.com/docs/openai) and
[tool-use format](https://console.groq.com/docs/tool-use/overview). Model-specific behavior
must still be checked against the selected account. After setting the three model variables,
an operator can manually run this probe; it sends three real model requests and executes no tools:

```sh
uv run --locked python -m svaar.agent.smoke
```

It requires native tool calls with exact arguments and prints only success/latency metadata
or a sanitized failure. The measured median is full non-streaming response time in seconds,
not first-token latency. Do not treat JSON-mode fallback as proof of native tool support.

The selected Groq model is `openai/gpt-oss-20b`, using
`https://api.groq.com/openai/v1`. On 2026-10-20 the user reported a successful live
probe: three native tool-call requests, median full-response time 0.516 seconds.
This verifies that probe only, not full agent/voice latency or all tool schemas.
See [Groq's model documentation](https://console.groq.com/docs/model/openai/gpt-oss-20b).
Model selection stays in local `SVAAR_LLM_MODEL`; no provider model is hardcoded.

`AgentLoop.run` accepts a server-resolved `ToolContext`, a caller-owned session and already
scoped history. It never invokes handlers directly. The caller must persist/dedupe the turn
and enqueue replies, confirmation tickets and fallback notifications through the outbox coordinator.
Tickets must never enter model history, a spoken reply or logs. The voice executor and reference runner compose the call-ID protocol with trusted persisted call context.

Model waits are bounded by one absolute turn deadline; late inference can never execute tools,
and abandoned requests continue occupying bounded inference capacity until they finish.
Tool handlers remain synchronous, outside those workers. They receive the remaining absolute
monotonic budget as `call.context.deadline` and must use bounded database/provider timeouts.
A running external effect cannot safely be cancelled. End-to-end tool latency and unknown
outcomes still need adapter-specific validation; see plans/anomaly.md A-009.

### Durable chat processing

Migration 0003 adds conversations, ordered messages, inbound_messages and
outbox_messages. ChatRuntime accepts only transport-authenticated senders and uses
the existing invite/identity services and shared AgentLoop. Application lifespan
exposes it as app.state.chat_runtime when the LLM is configured; no route or
listener calls it automatically. The Caspian adapter trusts private sender addresses under the approved MVP policy.

A fake authenticated sender can redeem `/join CODE`, ask `whoami` through the real
action dispatcher, and receive replies through a fake outbox transport. Duplicate
message IDs do not rerun tools. Route IDs are connection-scoped; thread ownership
and organization are checked before history is loaded. Invite commands and
confirmation codes/tickets are excluded from subsequent model history.

PostgreSQL session advisory locks serialize a sender/thread even if a dispatcher
commits mid-turn. A dedicated lock connection is held for the turn; this uses one
additional pooled connection per concurrent turn. The database connection timeout
bounds lock-connection checkout; a busy conversation returns a retryable busy
outcome rather than waiting indefinitely.

Received inbound records can resume before model/tool execution. The processing
marker commits before invoking the agent. A crash or unexpected failure after that
point requires reconciliation, even if no side effect can later be proven.
Processing state, safe history and outbox replies commit together after the turn.
This deliberately favors avoiding repeated effects over automatic recovery.

OutboxSender claims rows with FOR UPDATE SKIP LOCKED and commits sending before
network I/O. It rechecks the verified recipient, retries only explicit known-safe
rejections with bounded exponential backoff, and never retries uncertain outcomes.
Caspian 429 rejections can retry; other 4xx rejections are permanent. Queued receipts
are reconciled by GET using their delivery IDs. A crash leaving sending is treated
as uncertain; those rows require operator review rather than automatic resend.

No live sends, billing operations or Bolna calls are part of these
checks. Operator reconciliation UI and voice/call memory remain pending. Gateway wiring
and durable cursors are described below; live channel acceptance is separate.

### Gateway wiring and health

Migration 0004 adds gateway_cursors in the same PostgreSQL database. This small
table is necessary to resume a project event stream across restarts and record
runtime health; a conversation row alone cannot represent a project cursor.

GatewayWorker connects polling -> ChatRuntime -> OutboxSender -> receipt reads.
A PostgreSQL advisory lock gives one worker ownership of a stream page. Cursor
advancement occurs after processing has durably completed; replay after a crash
passes through inbound dedupe. Busy or untrusted messages do not advance the
cursor. Poll failures use bounded backoff and never bypass action gates.

Normal startup requires SVAAR_CHANNEL_TRANSPORT=caspian, complete LLM/Caspian
configuration and an active matching Caspian connection. The approved MVP policy
uses the private sender address returned by the authenticated Caspian API for
identity binding. A separate stable sender-ID contract is not required. Invites,
organization/role checks and confirmations remain enforced. Missing keys can be
supplied later without introducing fake defaults.
SIGTERM/SIGINT request shutdown; all composed provider/database resources close.

```sh
uv run --locked python -m svaar.gateway --check
uv run --locked python -m svaar.gateway --status
```

--check verifies database infrastructure only. --status makes no provider calls
and succeeds only for a fresh ready/processing heartbeat; absent, blocked, errored,
stopped or stale workers fail it. A heartbeat expires after 60 seconds. Compose
uses --status for gateway health, independently of the API readiness probe.

SVAAR_GATEWAY_POLL_SECONDS defaults to 2 and SVAAR_GATEWAY_BATCH_SIZE to 10;
both are bounded settings passed only to gateway. Fake-transport/PostgreSQL tests
verify composition, cleanup, persisted cursor restart, deduped crash replay,
stream exclusion, rejected sender pages, shutdown and stale health. No live
listener, model request or outbound delivery was started during these checks.

### Caspian Telegram adapter

The selected first channel is Telegram through Caspian hosted polling.
The standalone adapter reads the deployed v0.1.0 HTTP API with existing httpx;
the current upstream SDK is a 1.0 rewrite, so its constructors are not assumed
compatible with the hosted REST API.

Set all four local fields to run the read-only probe:
`SVAAR_CASPIAN_BASE_URL=https://api.trycaspianai.com`,
`SVAAR_CASPIAN_API_KEY`, `SVAAR_CASPIAN_TELEGRAM_CONNECTION_ID` and
`SVAAR_CASPIAN_TELEGRAM_ADDRESS`. The address identifies the bot, not a human.
Partial credentials do not start any feature. Compose forwards these fields only
to gateway. The direct Telegram bot token is not used by this hosted adapter.

```sh
uv run --locked python -m svaar.agent.caspian_smoke
```

The probe checks an existing active connection, address/capabilities and one
polling page; it sends no message, provisions nothing and persists no cursor.
A read-only project event request returned 200 on 2026-10-23. The saved local
connection ID/address were initially absent at that check. After the user saved them,
the read-only probe passed connection/address/capability and polling checks. It
sampled zero eligible private text messages. Sender identity and outbound delivery
remain unverified; no live messages were sent.

Polling uses ordered `after_seq` events. Only fresh private text from the selected
connection becomes input; edits, groups, generated messages and other connections
are excluded. GatewayWorker persists processing results before advancing the stream cursor. The adapter itself supplies no durable
dedupe, memory or outbox.

Outbound POSTs are never automatically retried. A queued receipt means provider
acceptance, not final delivery; follow up using its message ID. Timeouts, server
errors and invalid receipts are uncertain outcomes for reconciliation.

**MVP identity policy (user decision, 2026-10-23):** trust Caspian private-chat
sender.address without requiring a separate stable-ID contract. The adapter marks
these validated private messages authenticated; invites still determine enrollment
and roles. Official source prefers mutable Telegram usernames, so changes or
reassignment can affect existing bindings. This is an accepted MVP limitation,
not evidence of an immutable identity guarantee.

Contracts: [deployed OpenAPI](https://api.trycaspianai.com/openapi.json) and
[official Telegram provider](https://github.com/TryCaspian/caspian-sdk/blob/718a96d6d04cb76c7ccce942d2532fd4adbfd545/server/src/comm_gateway/providers/telegram.py).
HTTP tests use synthetic payloads; no live outbound acceptance is claimed.

### Integration configuration

Bolna turn/status, Caspian polling, GitHub App/webhook and shared model settings
are active optional configuration. See .env.example and the deployment guide
for names and per-process scopes. Jira and direct Telegram transport are still
unimplemented optional integrations. Configured credentials are not proof of
live delivery, calling or provider acceptance.

## Security model

The following controls are requirements for feature implementation. Operator bearer
authentication, invite-based identity, dispatcher enforcement and confirmations exist and are
tested locally. Voice, channel and webhook authentication exist; configuring credentials alone does not establish live end-to-end acceptance.

- **Separate credentials.** The operator token only opens operator routes. Voice turns, the voice status webhook, the GitHub webhook and any channel webhook each have their own credential. GitHub deliveries are verified by HMAC and deduplicated by delivery ID. The Bolna status webhook accepts only Bolna's addresses plus a shared secret.
- **Verified identity.** People join with single-use, expiring invites. No organization is created from chat. Ordinary missions call only verified phones. The `phone_verify` mission is the narrow exception: it may dial only the pending number bound to that principal's verification challenge and may only verify that challenge. A caller cannot establish identity by asserting it during a call.
- **One gate.** No code path calls a tool handler outside `actions`. Risky tools need a confirmation with a one-time code, compared exactly in code, executed once, and authorized again at execution time.
- **Trust rules.** Missing evidence, unanswered calls, busy lines and failed calls never mark a claim contradicted.
- **Idempotency.** Chat messages, GitHub deliveries, Bolna webhooks and voice turns are deduplicated by unique database keys, and handlers are safe to replay.

Logs are JSON with timestamp, level, logger, event message and optional exception type. Infrastructure errors never log raw SQL, exception text, request bodies, headers or connection URLs. Access logging is disabled in the supplied run commands, and HTTP and SQL client diagnostic logs are suppressed. This is not a general secret scrubber: new code must use fixed event names and never pass transcripts, phone numbers, message text, tokens or payloads into log messages or response headers.

## Endpoints and transactions

Infrastructure probes are unversioned. Add each feature's `APIRouter` in its own package, then include it in `api/router.py`; all business endpoints inherit `/api/v1`. Add only implemented endpoints. Use Pydantic request and response models and explicit status codes.

Synchronous SQL handlers and dependencies use `def` so FastAPI runs them in its thread pool. Never call blocking SQL directly inside an async endpoint.

Errors use `{"error":{"code":"...","message":"..."}}`. Validation failures add `details` containing only locations and error types, not rejected input. HTTP exceptions retain status and headers but use a generic status phrase; raw `detail` is intentionally not reflected. Unexpected errors return generic 500 responses. Use the common error response model when documenting additional endpoint errors.

Use `Depends(get_session)` from `svaar.db` for a request-scoped SQLAlchemy session. The caller owns the transaction and commits successful writes explicitly. Session context exit closes the session and rolls back uncommitted work. Never share a session between requests or jobs. External side effects, including phone calls and chat messages, are not atomic with a database commit: record intent in the database first, perform the side effect, then record the result, and make every step safe to replay.

## Migrations

```sh
uv run --locked alembic current
uv run --locked alembic upgrade head
uv run --locked alembic check
uv run --locked alembic revision --autogenerate -m "describe schema change"
uv run --locked alembic upgrade head --sql
```

No `create_all` runs at startup. Models inherit `svaar.db.Base`, live in their owning package and use `timestamptz` columns. Import each package's models in `migrations/env.py` before autogenerating. Review generated SQL and format and lint new revisions. Check and unique constraints must have explicit names to use the shared naming convention. Cross-package references use plain identifiers, not imported models.

Coordinate migration heads across teammates; resolve concurrent heads deliberately before merging. Run migrations once per deployment, before starting application workers. For an existing Compose deployment, rerun the migration service explicitly before recreating the services:

```sh
docker compose build
docker compose run --rm migrate
docker compose up -d app
```

## Quality and tests

```sh
uv run --locked ruff format .
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

Default tests need no running database: they exercise lifecycle cleanup, liveness, mocked readiness success and failure, a closed local database port, settings, sessions, safe errors and JSON logging. PostgreSQL tests skip unless `SVAAR_TEST_DATABASE_URL` is set. That database must be dedicated and disposable: tests run Alembic upgrades and checks and inspect the schema. For local testing, create a separate database in the development container:

```sh
docker compose exec db createdb -U svaar svaar_test
```

Then set the variable in your shell and run pytest. PowerShell:

```powershell
$env:SVAAR_TEST_DATABASE_URL = 'postgresql+psycopg://svaar:svaar_dev_only@localhost:5433/svaar_test'
uv run --locked pytest
```

POSIX shell:

```sh
SVAAR_TEST_DATABASE_URL=postgresql+psycopg://svaar:svaar_dev_only@localhost:5433/svaar_test uv run --locked pytest
```

Feature tests cover behavior and trust rules, not implementation details: the dispatcher never runs a risky tool unconfirmed, a confirmation runs at most once under concurrent attempts, invites are single-use, duplicates take effect once, and absent evidence never contradicts a claim. Every provider integration (Caspian, Telegram, Bolna, GitHub, Jira, the chat LLM) is mocked behind its adapter in tests.

The suite includes infrastructure and domain trust-boundary tests. Live provider acceptance remains separately tracked in plans/checkpoints.md.

CI installs the locked environment, checks formatting and lint, runs migrations, the gateway
infrastructure diagnostic and tests against PostgreSQL, and validates default and gateway-profile
Compose configuration. Container build and startup should also be checked locally.

## Team conventions

- Work within the owning module; coordinate shared config, API composition, dependencies, new packages and migrations.
- Keep provider integrations behind adapters and mock them in tests.
- Preserve the boundary between observations and simulations.
- Use type hints, standard docstrings, Ruff and precise commit messages. No em dashes and no emoji in code, comments or documents.
- Refresh `uv.lock` with `uv lock` after approved dependency changes.
- Work on feature branches. Check for redundant routes, folders and naming drift before merging.
- Git operations and submission-time document cleanup are performed manually by the team.

## Implementation history

Earlier notes below describe the scope when each feature was introduced. Their
pending-work statements are historical; use the deployment guide and latest
checkpoints for current implementation and live acceptance.

### Internal shared voice runner

Application composition exposes app.state.voice_turn_runner when the LLM is
configured. VoiceRuntime owns persistence and calls the injected VoiceAgentExecutor;
agent and voice implementations never import each other. Both chat and voice use
the same AgentLoop, registry and action gates. No Bolna route or real call is enabled.

Migration 0005 adds ordinary voice_calls and voice_turns. Internal calls must be
active and tied to the intended organization, principal and still-verified phone
binding. The internal phone_verify challenge exception is described below; live code delivery remains pending.
The runtime accepts a server-resolved internal call ID, text and stable zero-based
turn_index. Missing/gapped indices or changed duplicate payloads refuse execution;
completed retries reuse their saved reply. Text alone is never a retry key.
A per-call advisory lock survives action commits. Processing/unknown outcomes
require review and never repeat tools automatically.

History is isolated per call and limited to six previous turns; confirmation
inputs and unusable speech are excluded from later user history. Existing voice
usability, intent, mission and timeout behavior runs through the shared agent.
The runner is tested with real PostgreSQL and fake providers. Before live use,
verify Bolna authentication, call-reference mapping and stable turn indices, add
the phone challenge and wire fallback/confirmation notifications. The inherited
fallback mentions messaging, but notification delivery is not implemented here.
See plans/anomaly.md A-013. Run alembic upgrade head before using the new schema.

### Bolna outbound adapter and internal call lifecycle

BolnaClient implements documented call placement and execution lookup using
existing synchronous httpx. Optional SVAAR_BOLNA_API_KEY and
SVAAR_BOLNA_AGENT_ID settings are required by explicit from_settings construction.
No client, call service, call job or network request starts automatically; these
credentials are not yet forwarded by Compose. No provider SDK is required.

CallService works on an existing server-owned pending ordinary call. Before
placement it checks organization, principal and verified phone ownership. It
commits placing before the single POST, stores only a hash of the generated
private call reference, and records queued acceptance with the execution ID.
Queued is not proof of an answered call. Explicit rejection is failed; ambiguous
placement is unknown. Neither state is automatically redialed. A crash leaving
placing requires review. Provider auto-retries are explicitly disabled.

Execution reads validate the receipt's execution and agent IDs. Progress cannot
regress or reopen a final call. call-disconnected blocks further turns while
waiting for the final result; completed and hard-failure terminal statuses close
the call. These statuses do not establish or contradict an incident claim.
This adapter does not persist transcripts or provider extraction payloads.

Migration 0006 adds placement/receipt state. Apply migrations before internal use;
development migrations were not applied by these checks. Downgrade requires new
placement states to be reconciled rather than resetting them to pending.
Phone verification, account readiness, authenticated turn/status routes,
call-reference/turn-index delivery and fallback notification delivery remain
pending. No production entrypoint invokes CallService; future business callers
must retain action authorization and mission-specific scheduling/limits.

Contracts checked on 2026-10-23:
[call placement](https://www.bolna.ai/docs/api-reference/calls/make),
[execution lookup](https://www.bolna.ai/docs/api-reference/executions/get_execution)
and [provider retry configuration](https://www.bolna.ai/docs/outbound/auto-retry).
Tests use synthetic HTTP and fake providers; no live Bolna call is claimed.

### Internal phone verification challenge

Phone challenges are owned by identity. Internal issuance requires an enrolled
principal with a verified non-phone channel and returns a six-digit code once
for private chat delivery. Only a salted scrypt hash is stored. Challenges expire
after ten minutes, lock after three failed comparisons and enforce a one-minute
resend cooldown per principal and target. Reissue cancels prior pending challenges.
Pending numbers do not create or reserve phone bindings.

Migration 0007 adds phone_challenges and an explicit pending-challenge call
context. create_phone_verification_call creates only an internal intent, without
dialing. CallService may dial that exact pending number only for phone_verify.
Ordinary missions still require a verified phone binding. Verification calls offer
only verify_phone_code through the shared actions dispatcher and usability/intent
gates. The challenge comes from trusted context; the code comparison uses the
caller transcript, never a model-reconstructed code. Six ASCII digits must match
exactly after removing spaces/hyphens; number words are not guessed.

A successful comparison creates/verifies only that principal's number. The runner
closes finished verification calls and returns saved replies on indexed retries.
Verification text and replies never enter later model history. Core behavior is
tested with fake inference/providers and real PostgreSQL.

The live flow is still incomplete: no chat issuance command/private code delivery,
provider turn/status endpoint or real verification call is enabled. Bolna reference
and retry-index delivery must be verified before exposing a route. No code is sent
or call placed automatically. Without a configured classifier, voice gates continue to request clarification.
See plans/anomaly.md A-015; development migrations still need applying.

### Request phone verification in private chat

After invite enrollment, the private command is:

```text
/verify_phone +<your E.164 number>
```

The configured gateway handles this identity-enrollment command without calling
the model. Challenge creation, pending call intent, private code outbox and inbound
dedupe commit together. The six-digit code is delivered through the existing
outbox, with expiry/supersession and recipient checks before sending. Codes and
phone-registration commands never enter conversation history or model prompts.
Identity stores a salted code hash; the private delivery outbox holds the code
needed for delivery. Unknown sends are not blindly retried.

The reply explicitly states that the verification call must be started separately.
This prepares a pending intent; it does not enable a dialer, verify the phone,
place a real call or claim a code was delivered before its receipt. Application
and gateway composition inject call preparation without imports between agent
and voice implementations.

An offline integration test covers enrollment, private code delivery, fake Bolna
placement/status and exact spoken-code verification through the shared action
gate. No live messaging or calling was performed. Authenticated Bolna routes,
verified reference/index delivery and authorized real acceptance remain pending.

Development database is migrated through 0008; the isolated test DB passed its
migration round trip/drift checks. This supersedes earlier unapplied-migration
notes. Restart running application/gateway processes to load the new code.
Migration downgrade refuses unresolved private-code deliveries.

### Voice failure follow-ups

Application composition injects enqueue_voice_fallback into the voice runner.
Unavailable/tool-limited turns and unexpected failures queue one generic private
chat follow-up per call/turn through the existing outbox. Processing/unknown
retries can queue the notification without repeating tools. Notifications contain
no caller transcript, phone or secret code.

Routing requires exactly one existing scoped conversation with a verified binding.
Missing/ambiguous routes or notification failure produce a spoken request to
continue in chat. A queued follow-up is described as queued, never delivered.
Recipient verification, bounded safe rejection retries and uncertain-send handling
remain enforced by OutboxSender. Confirmation-ticket delivery and real voice
latency/acceptance remain pending.

### GitHub workflow ingress

Implemented endpoints:

| Endpoint | Authentication | Behavior |
| --- | --- | --- |
| POST /api/v1/repo-mappings | Operator token | Bind numeric repository and installation IDs to an existing org; overwrites refused |
| POST /api/v1/webhooks/github | Raw-body HMAC | Persist validated, explicitly mapped workflow_run observations |

Set SVAAR_GITHUB_WEBHOOK_SECRET locally to a high-entropy value of at least
32 characters. It is optional and forwarded only to the app container; absent
configuration returns 503. GitHub App credentials are separate and its outbound
REST client is not implemented. No token or new provider account is needed to
run the synthetic tests.

The handler verifies the exact request bytes before JSON parsing and caps bodies
at 1 MiB. It rejects invalid signatures, ambiguous JSON and inconsistent typed
workflow states. Mapped repository and installation IDs are required; sender names
never establish scope. Synchronous database work runs off the async request loop.

Malformed JSON returns 400, unsupported events return 200 with handled=false,
unmapped repositories return 404, and conflicting delivery reuse returns 409.
Delivery IDs and stable run-transition keys dedupe separately. Normalized
observations and receipt metadata commit atomically. Events retain source delivery
provenance and occurrence time; raw webhook bodies and sender personal fields are
not persisted. PostgreSQL rejects updates/deletes to events.

Migrations 0009/0010 add notification dedupe and GitHub observations/receipts.
Development DB is at 0010 with clean drift checks. Tests use an isolated database
and synthetic HMAC requests, with no live GitHub, Bolna or Caspian calls/messages.

Incident grouping, fingerprints, incident-scoped timeline/get_timeline and owner
alerts remain pending. Current facts are org/repository scoped, before incident
association. No CI action or automatic rerun exists. No tunnel is configured; any
future tunnel must expose only the implemented webhook path, keeping operator
routes and docs private.

Contracts:
[signature validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries),
[workflow_run payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads#workflow_run)
and [delivery handling](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks).


### Read-only Bolna account readiness

After saving SVAAR_BOLNA_API_KEY and SVAAR_BOLNA_AGENT_ID locally, run:

```sh
uv run --locked python -m svaar.voice.smoke
```

This makes two authenticated GET requests to Bolna's account and configured-agent
endpoints. It prints only readiness flags, never balances, prompts or credentials.
A successful exit requires positive credit, available concurrency, a processed
agent and a conversation task. It places no calls and changes no configuration.
The account/agent checks passed on October 24, 2026. Turn delivery remains
unverified: this command cannot establish a working Svaar bridge, webhook,
telephone connection or end-to-end voice flow.


### Bolna status receipt endpoint

POST /api/v1/voice/status is implemented for minimal execution lifecycle receipts.
Set a separate random SVAAR_VOICE_STATUS_SECRET of at least 32 characters locally.
Blank disables ingress with 503. In Bolna's webhook configuration, the custom
X-Svaar-Voice-Status-Secret header must match this value. No hosted configuration
has been changed automatically.

The endpoint also requires the actual peer to be one of Bolna's documented IPs:
13.203.39.153, 13.126.9.249 or 13.202.133.53. Run Uvicorn with
--no-proxy-headers, as the image does. Forwarded headers are ignored by the handler.
The normal app rejects tunneled peers. For local Cloudflare delivery, use only
the dedicated restricted listener described below.

Only an execution already recorded on a Svaar call, with a matching provider
agent, is accepted. Migration 0011 adds atomic execution/status dedupe metadata.
Stale progress and later callbacks cannot reopen a terminal call. Unknown status
labels are recorded and ignored. Request bodies are bounded to 1 MiB; transcripts
and extractions are discarded, not logged or retained.

This endpoint records transport closure only. Completed-call classification,
claim/evidence updates, operator balance alerts, transcript retention and the
authenticated conversation-turn bridge remain pending. No real callback
delivery or telephone call has been verified.

Contract: https://www.bolna.ai/docs/post-call/polling-call-status-webhooks


### Failed-call private follow-ups

Authenticated no-answer, busy, failed, canceled, stopped and error receipts now
queue one generic private chat notification per call through the existing outbox.
The callback and notification commit together; enqueue exceptions roll back both
for safe provider redelivery. A missing or ambiguous verified private conversation
queues nothing. Outbox delivery still rechecks the recipient binding.

This does not send directly, verify a phone, infer claim status or redial.
Completed calls and balance-low do not use this failure notifier. Operator
balance alerts remain pending. Real callback and notification delivery are still
unverified; offline tests use synthetic provider data and isolated PostgreSQL.


### Internal voice reference resolution

ReferencedTurnRunner resolves a private placement reference by its stored hash,
requires provider execution/agent receipts and delegates to the existing guarded
runner. The authenticated transport must supply a stable zero-based turn index.
The resolver accepts no asserted caller, organization or mission.

This is an internal boundary, not an exposed Bolna endpoint. The provider's
delivery of the reference and retry identity remains unverified. Do not substitute
model-generated counters or utterance hashes for transport retry identifiers.
A public HTTPS ingress and verified proxy/IP handling are also still pending.


### Local Cloudflare status tunnel

The dedicated create_status_ingress factory exposes only the exact POST
/api/v1/voice/status route. It has no docs, health, operator, GitHub or turn routes
and starts no model runtime. It reuses the same database, callback processing and
outbox composition; this is a restricted entry point for the modular monolith,
not a new independently deployed business service.

Prerequisites: cloudflared installed, local database migrated, and a separate
SVAAR_VOICE_STATUS_SECRET saved locally. The factory refuses startup without it.
From the project directory, run in terminal 1:

```sh
uv run --locked uvicorn svaar.app:create_status_ingress --factory --host 127.0.0.1 --port 8001 --no-access-log --no-proxy-headers
```

In terminal 2, when ready to expose that restricted listener:

```sh
cloudflared tunnel --url http://127.0.0.1:8001
```

Keep both terminals running. The printed HTTPS URL is temporary. Do not point
this tunnel at the main app on port 8000. Do not enable proxy headers or bind the
restricted listener to 0.0.0.0. Stop either process with Ctrl+C when finished.
No automatic tunnel launch or provider configuration is part of application startup.

This listener trusts the local Mac and its cloudflared process. It accepts only
a direct 127.0.0.1 peer, exactly one CF-Connecting-IP header matching a documented
Bolna IP, and the independent callback secret. It ignores X-Forwarded-For.
A local process that knows the secret can impersonate the connector: local host
trust is explicit. Do not insert other proxies or Workers into this setup.
The standard application continues to ignore Cloudflare client-IP headers.

Cloudflare documents CF-Connecting-IP as the client address delivered to the
origin. This trust applies only to traffic delivered by your local cloudflared
connector, not arbitrary headers on public/direct requests:
https://developers.cloudflare.com/fundamentals/reference/http-headers/

Once the tunnel runs, the intended Bolna webhook URL is:
https://YOUR-TUNNEL-HOST/api/v1/voice/status
Its custom X-Svaar-Voice-Status-Secret header must match the saved local secret.
Configure the hosted agent manually only when ready. A browser request cannot
test acceptance because its source is not a Bolna IP. Unknown executions, including
dashboard samples without a stored Svaar call receipt, deliberately return 404.
Public delivery and real source-header behavior remain unverified until tested.
The conversation-turn bridge remains separate and incomplete.


### Standalone read-only GitHub App adapter

Phase 4 now has GithubAppClient.for_repository(session, settings, org_id,
repository_id). It requires an explicit same-org repo_mappings entry and uses
that entry's installation ID, with no deployment-wide installation fallback.

Optional SVAAR_GITHUB_APP_ID and SVAAR_GITHUB_PRIVATE_KEY_B64 must be configured
together. The key is base64-encoded unencrypted PEM RSA, at least 2048 bits.
It is separate from the existing GitHub webhook HMAC secret. Leave both blank
until the team provisions an App; no credentials are needed for mocked tests.

PyJWT with cryptography support signs a nine-minute RS256 JWT, including the
documented clock-skew allowance. Token exchange requests only the selected
repository and Actions/metadata read permissions. The client caches the token
until five minutes before expiry, serializes concurrent refreshes and bounds HTTP
timeouts and response size. It follows no redirects, inherits no HTTP proxies,
performs no automatic retries and exposes sanitized errors.

repository_name and workflow_run perform reads and verify response IDs. They do
not create observed events, infer recovery or execute business tools. No workflow
rerun, dispatch or cancel is exposed. Client construction makes no requests.
Callers must close the client. The adapter remains standalone: it is not wired
into startup, the gateway or model tools; App secrets are not newly forwarded
through Compose. Runtime lifecycle/deadline composition remains future work.

Verified scope: official contracts and mocked HTTP with synthetic RSA keys.
No live authentication or installation provisioning was attempted. Workflow
logs/archive retrieval and normalized log-tail fingerprinting remain pending.

References:
https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app
https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app
https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run


### Workflow-log signatures (standalone)

GithubAppClient.workflow_log_signature(run_id) now verifies a completed failed
run, requests GitHub's short-lived log redirect, and downloads the ZIP using a
separate credential-free client. Accepted storage locations are HTTPS on
results-receiver.actions.githubusercontent.com or an Azure blob storage account
host matching the documented blob.core.windows.net family. Arbitrary hosts,
userinfo, nonstandard ports and further redirects are rejected. API credentials,
headers and cookies are not forwarded.

The 8 MiB archive is processed in memory with 100-member/16 MiB expanded limits.
Unsafe paths, links, encrypted or non-text files, excessive compression and empty
or invalid logs are rejected. No archive is extracted to disk. The signature
hashes versioned normalized file tails, not raw log text or filenames.
Ordinary numeric error codes remain meaningful; timestamps, paths, PIDs and ANSI
formatting are normalized. Only digest and file-count metadata return.

The scoped failure_fingerprint helper includes org, repository, workflow and
branch. It does not change current incident grouping, create observed evidence
or infer recovery. Runtime composition, run-attempt provenance, durable signature
storage and grouping integration are pending. Missing logs produce an explicit
failure rather than a fabricated empty fingerprint. No live download was tested.

Contracts:
https://docs.github.com/en/rest/actions/workflow-runs#download-workflow-run-logs
https://docs.github.com/en/actions/reference/runners/github-hosted-runners


### Attempt-bound log provenance

The explicit internal integrations.log_enrichment.enrich_event operation reads
one same-org signed failed-workflow observation, verifies an App response against
its run ID, attempt, commit SHA, workflow ID and branch, and downloads that
attempt's logs. Provider I/O occurs after the read transaction has closed.
There is no automatic startup, webhook, gateway, job or model-tool invocation.

Migration 0015 adds workflow_log_signatures: only digests, scoped fingerprint,
algorithm, file count, observation reference and run/installation metadata are
stored. A unique per-org/repository/run/attempt/algorithm key and advisory lock
serialize writes. Matching reprocessing returns duplicate. A changed digest
returns conflict and preserves the original; raw logs and signed URLs are not
stored. PostgreSQL blocks updates and deletes of signature records.

The repository mapping is rechecked before commit; changed or missing mappings
cannot receive a record. Unavailable or invalid logs create no signature.
Unsupported/successful/incomplete observations are refused before provider I/O.
This is enrichment metadata, not a claim verdict or production recovery signal.
Existing incident membership and broad workflow grouping remain unchanged until
runtime enrichment and log-based grouping are wired together.


### Explicit repository and incident ownership

POST /api/v1/repo-mappings accepts an optional owner_principal_id. It must name
an existing principal in the mapping's organization. Roles are not used to guess
an owner; a developer can own a repository.

An operator can configure an existing mapping through:
PUT /api/v1/repo-mappings/{repository_id}/owner

```json
{
  "org_id": "<organization UUID>",
  "owner_principal_id": "<principal UUID>",
  "assign_unowned_incidents": false
}
```

This operator-only route changes the default for future incidents. Each newly
opened incident snapshots the configured same-org owner. Mapping changes do not
transfer already-owned incidents. To assign the selected owner to existing open
unowned incidents explicitly, set assign_unowned_incidents=true. Assigned,
acknowledged and resolved incidents are untouched. Owner assignment and its
idempotent outbox alert commit together; repeats cannot queue another alert.

Alerts target only the incident owner through the existing verified private route.
Missing owners or missing/ambiguous private routes queue nothing; there is no
role-based broadcast fallback. Acknowledgement records the acknowledging caller
and does not transfer ownership. Timeline/tool summaries expose the owner ID.
No call or escalation is started by this configuration.

Migration 0016 adds nullable owner references without guessing existing owners.
Its downgrade refuses to discard configured ownership. Explicit reassignment of
an already-owned incident and general transfer/audit tooling are not implemented.
Claims and guarded escalation remain subsequent work. Live owner configuration,
chat delivery and calls have not been verified by these synthetic tests.


### Claims and deterministic workflow evidence

The initial claims core registers record_claim and check_claim as tier-1 chat
tools, and list_claims as a chat/voice read tool subject to mission gates.
All calls pass through actions. Author and organization come from trusted caller
context; source correlation deduplicates one claim per author/message. AgentLoop
replaces model-proposed statement text with the original caller message.
Source/content conflicts do not overwrite the original assertion.

Supported structured claim kinds are workflow_succeeded (exact run/attempt,
optional commit SHA) and fix_merged. A positive workflow assertion such as
"The build passed." can become confirmed only from matching completed-success
observations linked to that incident and accepted signed-delivery receipts.
Any run number present in the supported statement must match the target.
The matcher deliberately accepts only a narrow positive assertion grammar;
questions, negatives, compound/unrecognized wording and model-kind mismatches
stay unverified. A model's selected label alone never establishes truth.

Evidence is stored separately with event provenance, stance and rule version,
deduplicated per claim/event and protected by a PostgreSQL append-only trigger.
Missing facts and observed failed workflows produce no contradictory evidence.
Successful CI never proves a fix was merged: merge claims remain unverified
until merge-event or verified call-answer evidence is implemented. Current rules
do not generate contradicting evidence. Mixed future evidence defers to unverified.

GET /api/v1/incidents/{incident_id}/claims is an operator-authenticated read-only
view. It returns assertions, statuses and evidence references; GET does not refresh
statuses or call a provider. check_claim explicitly refreshes after new evidence.
Migration 0017 adds claims/evidence and refuses downgrade while claims exist.

This is a scoped core, not the complete claim workflow. Dedicated automatic
claim detection, merge-event ingestion, record_claim_answer, completed-call
classification/retention, verification authorization and guarded escalation jobs
remain pending. No claim operation places a call, mutates CI or infers recovery.

### Guarded escalation preparation

Migration 0018 adds durable escalation jobs and an incident binding on call intents.
The optional gateway worker prepares at most one pending escalation intent per
open incident with an explicit owner, a confirmed delivered owner alert and exactly
one verified phone. The acknowledgement grace begins at the outbox's confirmed
delivery time. Queued or unknown delivery cannot start it. Acknowledgement before
preparation cancels the job; missing phones defer it. Recipient cooldown and row
claiming prevent concurrent duplicate preparation. Individual preparation failures
roll back independently and retry after 60 seconds.

Set SVAAR_ESCALATION_JOBS_ENABLED=true locally and restart the gateway to enable
preparation after applying migrations. Defaults remain disabled. This worker has
no provider client and never dials. Prepared incident-bound escalation intents are
refused by the default CallService unless a composition-supplied authorization
guard exists. Live placement, readiness, final incident/recipient checks at dispatch,
delivery acceptance and reconciliation still need the voice integration milestone.
Bound voice tools cannot select another incident. Preparation does not classify
call answers, refresh claims or establish any observed evidence.

### Non-voice implementation update, 2026-10-28

Standing release/staffing/capacity constraints now have an operator-only,
revision-checked store. The agent can negotiate against trusted rules, export
tracked JSON drafts, request isolated replay of a proposed scenario, and request
tier-2 draft approval. Policy changes require a new negotiation. Draft approval
does not waive constraints or execute a deployment.

Optional leased CI work composes the existing read-only App/log adapter with
log-based incident grouping and atomic owner-outbox alerts. A separate process
in the same application/image keeps slow log reads out of chat polling.
list_ci_runs/explain_ci_failure expose scoped accepted observations and hash
provenance, with root cause/category explicitly unknown.

Confirmed rerun/cancel use a separate default-disabled writer. Its durable,
attempt-level intent prevents duplicate effects across confirmations and retains
accepted/rejected/uncertain outcomes. Ordinary log/read tokens stay read-only.
No workflow dispatch tool or automatic workflow rerun is implemented.

| Setting | Default |
| --- | --- |
| SVAAR_GITHUB_ENRICHMENT_ENABLED | false; enabled API defers grouping to CI jobs |
| SVAAR_CI_BATCH_SIZE | 5; between 1 and 20 |
| SVAAR_CI_POLL_SECONDS | 5; between 1 and 60 |
| SVAAR_GITHUB_ACTIONS_ENABLED | false; explicit opt-in for confirmed rerun/cancel |

Apply migrations through 0021 before using these features. Configuration alone
does not establish live access. See [the non-voice rehearsal guide](docs/NONVOICE_REHEARSAL.md)
for the offline test command, operator routes, opt-in setup and remaining work.
This update supersedes earlier standalone-only log/policy notes; their dated test
counts remain historical. PLAN.md/CEREBRO_CONTEXT.md and the private .env are unchanged.


### Claim verification calls

A lead or admin can ask Svaar in chat to verify an unverified claim. verify_claim
rechecks recorded evidence and prepares one pending claim_check call to the claim's
author; it needs owner confirmation when the author is not the incident owner. Nothing
is dialed automatically. During that call the only tool is record_claim_answer, which
stores the caller's exact words.

Set SVAAR_CLAIM_CHECK_JOBS_ENABLED=true and restart the gateway to finalize answers.
After the provider reports the call completed, one audited claim_answer decision labels
the answer. Only a confident model label of confirmed or denied becomes evidence;
unsure, wrong person, callback, fallback and low-confidence answers stay unverified, and
failed or unanswered calls discard the answer. Answer text is deleted once finalized.

A fix_merged claim that names a pull request is confirmed by a signed pull_request
merge event in the incident's repository, merged no earlier than the incident opened.
Subscribe the GitHub webhook to pull_request events for this; unmerged closes are
ignored. When the classifier is enabled, chat messages with status words get one
claim_detection request; a detection only suggests record_claim.

### Escalation advice and dispatch guards

With the classifier and escalation jobs enabled, the gateway asks for a CI failure
category and an escalation step once the acknowledgement grace has elapsed. A
confident flaky, chat_nudge or wait answer sends at most one private note and delays
the call once by one grace period; anything else keeps the deterministic schedule.

create_call_service composes CallService with dispatch-time rechecks of the incident
owner and claim author, an optional readiness probe and
SVAAR_VOICE_DAILY_CALL_LIMIT (default 3) placements per person in any 24 hours.
No route, job or model tool places calls yet.


### Manual incidents

POST /api/v1/incidents with the operator token opens an incident for a mapped
repository:

```json
{"org_id": "<organization UUID>", "repository_id": 101, "workflow_id": 55,
 "workflow_name": "Deploy", "head_branch": "main"}
```

owner_principal_id is optional and defaults to the repository mapping's owner. A later
CI failure for the same workflow and branch joins this incident; a second active
incident for them returns 409. The owner receives the usual private alert.


### Bolna voice turn route

Svaar can act as the Bolna agent's custom LLM. Set these locally, then restart:

```sh
SVAAR_VOICE_TURN_MODE=llm_endpoint
SVAAR_VOICE_TURN_TOKEN=<random 32+ characters, separate from every other secret>
```

The SVAAR_LLM_* settings must already be configured. Only the selected mode's route is
mounted: /api/v1/voice/llm/chat/completions (and /api/v1/voice/llm/models) for
llm_endpoint, or /api/v1/voice/turn for function. The restricted tunnel listener
(create_status_ingress on port 8001) serves the status webhook and this route only.

In Bolna, add a custom LLM with URL https://YOUR-TUNNEL-HOST/api/v1/voice/llm, model
svaar and the turn token as its key, then select it for the agent. Add this line to the
agent prompt so each call's private reference reaches Svaar; Svaar never speaks it:

```text
svaar_call_ref: {{call_ref}}
```

Svaar puts call_ref in user_data when it places a call. Requests without exactly one
reference are refused without running the agent. To place a prepared call:

```sh
uv run --locked python -m svaar.dispatch --list
uv run --locked python -m svaar.dispatch --place CALL_ID --org ORG_ID
```

--place dials a real phone after checking Bolna readiness, the incident or claim, and
SVAAR_VOICE_DAILY_CALL_LIMIT. Use it only with explicit authorization for that call.
Whether Bolna delivers the prompt reference and stable history is unverified until the
first real call (plans/anomaly.md A-028).


Additional Caspian channels: see [channel setup and acceptance status](docs/CASPIAN_CHANNELS.md).
