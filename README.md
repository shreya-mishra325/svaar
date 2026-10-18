![Svaar](https://github.com/RohanOnKeys/cerebro/blob/main/assets/Abstract%20Color%20Composition%20Photo%20on%20Lummi.jpg)

# Svaar

Svaar is a voice-enabled agent for engineering incidents. It lives in team chat, watches CI, rebuilds what happened from recorded events, checks status claims against evidence, calls engineers by phone to verify them, and negotiates conflicting constraints into a plan that deterministic code has validated.

**Jev decides, deterministic code enforces, Bolna speaks.**

- **Jev** is a typed decision model. It answers named questions with a value and a confidence.
- **Deterministic code** validates, authorizes and acts. Nothing a model says runs a tool by itself.
- **Bolna** is the voice layer. It turns the caller's speech into text, hands it to Svaar, speaks Svaar's reply and reports the final transcript.

Svaar has one agent. Chat messages and phone calls reach the same tool loop, the same tool registry and the same approval gate.

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

- `agent` and `voice` never import each other. `voice` defines a turn-runner protocol and application startup injects the agent's implementation.
- Replay output never enters `events`. Observations and simulations stay in separate tables.

External SDKs and HTTP contracts belong behind adapters, never in deterministic business rules.

## Processes

| Process | Runs |
| --- | --- |
| `app` | FastAPI: probes, voice turn routes, status webhook, GitHub webhook, incident and operator routes |
| `gateway` | Chat channel listener, outbox sender, guarded polling loop |

Both are built from the same image. Only Bolna and GitHub (and the chat channel provider, if it delivers by webhook) need to reach the application. Expose only the voice and webhook routes through a tunnel. Keep `/docs` and every other route local.

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
docker compose up --build --wait app gateway
docker compose logs app gateway
docker compose down
```

Compose starts PostgreSQL, waits for its health check, runs migrations as a one-shot service, then starts the unprivileged `app` and `gateway` containers. PostgreSQL persists in the `postgres_data` volume. `down` preserves data. Do not delete the volume unless its data is disposable.

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

### Features

These variables are introduced with the feature that reads them and are validated when that feature is enabled.

| Area | Variables |
| --- | --- |
| Operator | `SVAAR_OPERATOR_TOKEN` |
| Chat LLM | `SVAAR_LLM_BASE_URL`, `SVAAR_LLM_API_KEY`, `SVAAR_LLM_MODEL` |
| Channels | `SVAAR_CHANNEL_TRANSPORT` (`caspian` or `telegram`), `SVAAR_CASPIAN_API_KEY`, `SVAAR_CASPIAN_BASE_URL`, `SVAAR_CASPIAN_WEBHOOK_SECRET`, `SVAAR_TELEGRAM_BOT_TOKEN` |
| Jev | `SVAAR_JEV_BASE_URL`, `SVAAR_JEV_API_KEY`, `SVAAR_JEV_MODEL`, `SVAAR_POLICY_HIGH`, `SVAAR_POLICY_LOW` |
| Bolna | `SVAAR_BOLNA_API_KEY`, `SVAAR_BOLNA_AGENT_ID`, `SVAAR_VOICE_TURN_MODE` (`llm_endpoint` or `function`), `SVAAR_VOICE_TURN_TOKEN`, `SVAAR_VOICE_STATUS_SECRET` |
| GitHub | `SVAAR_GITHUB_APP_ID`, `SVAAR_GITHUB_PRIVATE_KEY_B64`, `SVAAR_GITHUB_INSTALLATION_ID`, `SVAAR_GITHUB_WEBHOOK_SECRET` |
| Jira | `SVAAR_JIRA_BASE_URL`, `SVAAR_JIRA_EMAIL`, `SVAAR_JIRA_API_TOKEN`, `SVAAR_JIRA_DEFAULT_PROJECT_KEY` |

Keep real credentials out of source control and logs. Production must inject its own secrets, database URL and HTTPS and access boundary. Production disables docs and OpenAPI.

## Security model

- **Separate credentials.** The operator token only opens operator routes. Voice turns, the voice status webhook, the GitHub webhook and any channel webhook each have their own credential. GitHub deliveries are verified by HMAC and deduplicated by delivery ID. The Bolna status webhook accepts only Bolna's addresses plus a shared secret.
- **Verified identity.** People join with single-use, expiring invites. No organization is created from chat. A phone number is verified by a code read aloud on a call, and only verified phones are ever called. The person on a call is identified by the number Svaar dialled, never by anything said on the call.
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
docker compose up -d app gateway
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

CI installs the locked environment, checks formatting and lint, runs migrations and tests against PostgreSQL, and validates Compose. Container build and startup should also be checked locally.

## Team conventions

- Work within the owning module; coordinate shared config, API composition, dependencies, new packages and migrations.
- Keep provider integrations behind adapters and mock them in tests.
- Preserve the boundary between observations and simulations.
- Use type hints, standard docstrings, Ruff and precise commit messages. No em dashes and no emoji in code, comments or documents.
- Refresh `uv.lock` with `uv lock` after approved dependency changes.
- Work on feature branches. Check for redundant routes, folders and naming drift before merging.
- Git operations and submission-time document cleanup are performed manually by the team.
