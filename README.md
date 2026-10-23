![Svaar](https://github.com/RohanOnKeys/cerebro/blob/main/assets/Copy%20of%20Svaar.gif?raw=true)

# Svaar

Svaar is a voice-enabled agent for engineering incidents. It lives in team chat, watches CI, rebuilds what happened from recorded events, checks status claims against evidence, calls engineers by phone to verify them, and negotiates conflicting constraints into a plan that deterministic code has validated.

**Jev decides, deterministic code enforces, Bolna speaks.**

- **Jev** is a typed decision model. It answers named questions with a value and a confidence.
- **Deterministic code** validates, authorizes and acts. Nothing a model says runs a tool by itself.
- **Bolna** is the voice layer. It turns the caller's speech into text, hands it to Svaar, speaks Svaar's reply and reports the final transcript.

Svaar has one agent. Chat messages and phone calls reach the same tool loop, the same tool registry and the same approval gate.

This describes the target architecture. The current code implements shared infrastructure,
health probes, package boundaries, the voice turn-runner protocol, and the Phase 1 local
foundation: identity with single-use invites, the `actions` registry and dispatcher with
mission guard and execution audit, owner-bound confirmations, and P0 decision schemas with
confidence policy, heuristic fallback and decision audit. Phase 2 now includes the shared
transport-independent agent core, an OpenAI-compatible HTTP adapter, bounded chat/voice
profiles, registry-generated policy and audited voice usability/intent gates. Durable chat
history, inbound dedupe and an outbox worker now exist, verified with fake transports and real
PostgreSQL. The standalone Caspian adapter has read-only connection/poll acceptance; Groq smoke
results are user-reported. Live channel enrollment, verified provider activation, trusted
call resolution, live Jev wiring and incident features remain unfinished. Cerebro is an
architectural reference, not a deployed dependency.

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
    Decisions --> Jev["Jev"]
    Sources["GitHub, Jira"] --> Integrations["integrations"]
    Integrations --> Incidents

    classDef external stroke-dasharray: 4 3
    class Chat,Caspian,Caller,Bolna,Jev,Sources external
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
| `decisions` | Jev adapter, typed decisions, confidence policy, heuristic fallback, decision audit |
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

- `agent` and `voice` never import each other. `voice/contracts.py` defines the synchronous `TurnRunner` protocol. When implemented, application startup will inject the agent's structurally compatible implementation; no turn runner is wired today. Both packages may depend on `actions` and `identity`.
- Replay output never enters `events`. Observations and simulations stay in separate tables.

Every business tool call must pass through `actions`; neither a transport nor a model may
call a feature handler directly. The voice intent router and transcript-usability gate belong
to the future agent/decision path. The deterministic mission guard must not allow either
model to expand a call's mission or tool allowlist. These are feature requirements, not
implemented checks in this scaffold.

External SDKs and HTTP contracts belong behind adapters, never in deterministic business rules.

## Processes

| Process | Target responsibility / current status |
| --- | --- |
| `app` | FastAPI. Only probes are implemented; voice, webhook, incident and operator routes are future work |
| `gateway` | Opt-in chat polling, durable cursor, outbox and heartbeat wiring. Missing configuration prevents live startup; incident polling jobs remain pending |

Both are built from the same image. Only Bolna and GitHub (and the chat channel provider, if it delivers by webhook) need to reach the application. Expose only the voice and webhook routes through a tunnel. Keep `/docs` and every other route local.

No external service needs access yet. When routes exist, restrict tunnel ingress to the
implemented voice paths, GitHub webhook, and Caspian webhook only if the confirmed transport
requires one. No channel SDK or provider-specific dependency is installed before its contract
is verified. Caspian is the planned channel transport, with Telegram as the fallback.

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
uv run --locked uvicorn svaar.app:create_app --factory --reload --no-access-log
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

The reserved `gateway` service uses the same image, has no published ports, and waits for
migrations. It is behind the `gateway` profile so normal startup does not launch an unfinished
runtime. Check its infrastructure explicitly:

```sh
docker compose run --build --rm gateway --check
```

For local Python, use `uv run --locked python -m svaar.gateway --check` with PostgreSQL running.
The diagnostic checks settings and database connectivity, then exits. It does not listen to
channels, send messages, or run jobs. Without `--check`, startup exits with code 2 and a clear
runtime-unavailable error. Replace that refusal with real agent/jobs composition when the
features are ready, then enable the profile and add runtime-specific health checks. The API's
HTTP health check is deliberately disabled on the gateway, which is not an HTTP server.

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
| `SVAAR_LLM_BASE_URL`, `SVAAR_LLM_API_KEY`, `SVAAR_LLM_MODEL` | Set all three or leave all unset. Base URL must use HTTP(S) without credentials/query/fragment; the API key is secret |

When configured, application lifespan creates `app.state.agent_loop` without making a provider
request and closes inference/HTTP resources on shutdown. When unset, that state is `None`.
Compose passes model and shared decision/confirmation policy settings to app/gateway,
not migrations. The operator token and invite TTL remain app-only. No public chat/voice route
uses the loop yet. Jev remains unconfigured, so the composed voice gates conservatively ask
for clarification rather than accepting heuristic confidence as permission.

Jev development currently uses mocked HTTP responses. The standalone
`decisions.jev.VercelJevEngine` implements Vercel's TypeSafe-compatible HTTP shape
with explicit versioned model IDs, strict per-answer validation, bounded network
timeouts and no retries or model fallbacks. It is not connected to application
startup or environment settings; adding a key does not activate it. No Node SDK
or Vercel CLI setup is needed for this Python adapter.

Run its offline tests without a provider key:

```sh
uv run --locked pytest tests/test_jev.py -q
```

The database audit scenarios require `SVAAR_TEST_DATABASE_URL`; they skip when it
is unset. All provider responses in these tests are synthetic, not recorded Jev
outputs. Mocked success does not verify model accuracy, live access or latency.
Vercel was selected by the user, but live Jev testing is deferred because the
catalog shown by the user excludes Jev from free Gateway credits. This does not
change the current conservative fallback in the running application.
Contract references: [Vercel TypeSafe API](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe)
and [TypeSafe Choice](https://docs.typesafe.ai/primitives/choice).

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
Tickets must never enter model history, a spoken reply or logs. The loop does not implement
the call-ID `TurnRunner` contract yet because trusted call resolution belongs to the voice phase.

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

No live sends, billing operations, Bolna calls or Jev requests are part of these
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

### Planned feature settings

These variables are introduced with the feature that reads them and must be validated at
application construction when that feature is enabled. They are listed as commented examples
in `.env.example`, not active fields in the Settings class. Wire each feature's credentials
only to the processes that need them as the feature is implemented.

| Area | Variables |
| --- | --- |
| Channels | `SVAAR_CASPIAN_WEBHOOK_SECRET`, `SVAAR_TELEGRAM_BOT_TOKEN` |
| Jev | `SVAAR_JEV_BASE_URL`, `SVAAR_JEV_API_KEY`, `SVAAR_JEV_MODEL` |
| Bolna | `SVAAR_BOLNA_API_KEY`, `SVAAR_BOLNA_AGENT_ID`, `SVAAR_VOICE_TURN_MODE` (`llm_endpoint` or `function`), `SVAAR_VOICE_TURN_TOKEN`, `SVAAR_VOICE_STATUS_SECRET` |
| GitHub | `SVAAR_GITHUB_APP_ID`, `SVAAR_GITHUB_PRIVATE_KEY_B64`, `SVAAR_GITHUB_INSTALLATION_ID`, `SVAAR_GITHUB_WEBHOOK_SECRET` |
| Jira | `SVAAR_JIRA_BASE_URL`, `SVAAR_JIRA_EMAIL`, `SVAAR_JIRA_API_TOKEN`, `SVAAR_JIRA_DEFAULT_PROJECT_KEY` |

Keep real credentials out of source control and logs. Production must inject its own secrets, database URL and HTTPS and access boundary. Production disables docs and OpenAPI.

## Security model

The following controls are requirements for feature implementation. Operator bearer
authentication, invite-based identity, dispatcher enforcement and confirmations exist and are
tested locally. Voice, channel and webhook authentication and the transports that would invoke
the dispatcher do not exist yet; configuring a token alone does not enable or protect a feature.

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

Feature tests cover behavior and trust rules, not implementation details: the dispatcher never runs a risky tool unconfirmed, a confirmation runs at most once under concurrent attempts, invites are single-use, duplicates take effect once, and absent evidence never contradicts a claim. Every provider integration (Caspian, Telegram, Bolna, Jev, GitHub, Jira, the chat LLM) is mocked behind its adapter in tests.

Those feature tests are future acceptance requirements. Current tests cover infrastructure,
including gateway diagnostic cleanup and refusal to advertise an unimplemented listener.

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
or call placed automatically. Unconfigured Jev continues to request clarification.
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
