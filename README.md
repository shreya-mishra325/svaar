![Svaar](https://github.com/RohanOnKeys/cerebro/blob/main/assets/Copy%20of%20Svaar.gif?raw=true)

<h1 align="center">Svaar</h1>

<p align="center">
  <b>The incident agent that checks the facts and picks up the phone.</b>
</p>

**Current demo status:** the Render API/database passed public checks. Complete
chat enrollment, actual Bolna conversations and end-to-end delivery remain
unverified. See [Render deployment](docs/RENDER_DEPLOYMENT.md) and
[channel acceptance](docs/CASPIAN_CHANNELS.md). Only the user deploys.

---

## Incidents run on trust. Most status updates have not earned it.

When production breaks, your team chat fills up fast. "Build is green." "Fix is merged." "Should be good now." Half of it is right. Some of it is hopeful. Nobody has time to check, so the incident drags on while everyone assumes someone else has it covered.

**Svaar makes sure every update is true.** It joins your team chat, watches your CI, checks what people say against what actually happened, and when the proof is missing, it calls the engineer and asks.

## Built for

- **On-call engineers** who want fewer pings and clearer handoffs.
- **Incident leads** who need one honest picture of where things stand.
- **Platform teams** who want accountability without adding process.

## What Svaar does for your team

### Spots failures the moment they happen
Svaar watches your GitHub Actions workflows. When a run fails, it groups related failures into a single incident, assigns a clear owner and alerts them privately. No duplicate tickets, no noisy channel.

### Checks every claim against real evidence
When someone says "the build passed" or "the fix is merged," Svaar records it and checks it against signed events from GitHub. A claim is marked confirmed only when the evidence backs it up. Silence or missing data never counts against anyone.

### Calls to confirm when the proof is missing
If the evidence is not there yet, an incident lead can ask Svaar to check. Svaar phones the engineer who made the claim, asks a short, focused question and records their answer. Every call has one purpose and nothing more.

### Follows up so nothing falls through the cracks
If an owner does not acknowledge an alert in time, Svaar escalates with a call. Cooldowns and daily limits make sure nobody gets spammed.

### Turns competing constraints into a workable plan
Release windows, staffing and capacity often pull in different directions mid-incident. Svaar weighs them, proposes a plan, validates it against your rules, and lets you test the scenario before anything changes.

## How it works

```mermaid
flowchart LR
    CI["CI fails"] --> Incident["Svaar opens an incident"]
    Incident --> Alert["Owner alerted in chat"]
    Alert --> Claim["Someone posts an update"]
    Claim --> Check{"Evidence?"}
    Check -- "Yes" --> Confirmed["Claim confirmed"]
    Check -- "Not yet" --> Call["Svaar calls to verify"]
    Call --> Answer["Answer recorded"]
```

1. **Something breaks.** Svaar sees the failed CI run and opens an incident.
2. **The right person hears about it.** The owner gets a private alert in chat.
3. **Updates get checked.** Every status claim is matched against real evidence.
4. **Gaps get closed.** If the proof is missing, Svaar calls the engineer and asks.

### Architecture

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

Detailed implementation notes are preserved in
[the implementation history](docs/IMPLEMENTATION_HISTORY.md).
They describe earlier milestones; use [Render deployment](docs/RENDER_DEPLOYMENT.md)
and [channel acceptance](docs/CASPIAN_CHANNELS.md) for current setup and limitations.

## Safe by design

Svaar is built on one rule: **models propose, deterministic code enforces.**

- **AI suggests, rules decide.** The language model drafts replies and suggests actions. Every action is checked by plain, auditable code before anything happens.
- **Risky actions need a second yes.** Actions like rerunning or cancelling a workflow require the owner to confirm with a one-time code on a separate, verified channel.
- **Only verified people, only verified phones.** Teammates join with single-use invites and verify their own phone number. Ordinary missions require a verified phone; the initial phone-verification call is the scoped exception.
- **Fair by default.** An unanswered call, a busy line or missing data never marks someone as wrong.
- **Private by default.** Transcripts, phone numbers and messages are never written to logs.
- **Every action counts once.** Duplicate messages, webhooks and calls are detected and ignored, so nothing happens twice.

## Works with your stack

| | |
| --- | --- |
| **Chat** | Telegram; private Slack/Discord adapters implemented, live acceptance pending |
| **CI** | GitHub Actions |
| **Voice** | Phone calls powered by Bolna |
| **AI** | Any OpenAI-compatible model with tool calling |

## Getting started

1. **Connect your chat** and invite your team.
2. **Connect GitHub** so Svaar can watch your workflows.
3. **Verify phones** so Svaar knows who to call.

These steps describe the intended flow. Complete the live checks above before presenting it as end-to-end acceptance.

---

<p align="center">
  <b>Svaar</b>: fewer assumptions, faster incidents.
</p>
