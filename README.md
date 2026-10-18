# Svaar

Independent FastAPI modular monolith for voice incident resolution.
**Jev decides, deterministic code enforces, Bolna speaks.**
Cerebro remains separately deployed; this foundation contains no Cerebro code or integration.

## Scope and modules

Only shared engineering infrastructure is implemented. Feature packages contain responsibility
docstrings, not placeholder routes, domain models, or algorithms.

| Package | Responsibility |
| --- | --- |
| `incidents` | Incident workflows, observed events, timelines, claims and evidence |
| `decisions` | Jev adapters, typed decisions, confidence policies and fallbacks |
| `voice` | Bolna calls, callbacks and bounded voice tools |
| `resolution` | Negotiation and deterministic constraint validation |
| `replay` | Isolated simulation, separate from observed events and live side effects |
| `approvals` | Human approval and authorization boundaries |
| `integrations` | Replaceable Cerebro and commerce adapters |
| `web` | Future operator interface |
| `jobs` | Future background processing; no scheduler or executor yet |
| `api` | Router composition, infrastructure probes and error conventions |

`app.py` composes modules and owns startup/shutdown. `config.py`, `db.py`, and `logging.py`
provide shared infrastructure. Feature modules may depend on these utilities; shared utilities
must not import feature modules. Do not import the application from domain code. External SDKs
and HTTP contracts belong behind adapters, never in deterministic business rules.

## Install and run locally

Requires Python 3.11+, Docker with Compose, and uv 0.11.29. Dependencies live in
`pyproject.toml`; `uv.lock` fixes resolved versions for development, containers, and CI.

```sh
python -m pip install uv==0.11.29
uv sync --locked
```

Copy `.env.example` to `.env` (`Copy-Item .env.example .env` in PowerShell or
`cp .env.example .env` in a POSIX shell). The example credentials are for local development only.

```sh
docker compose up -d --wait db
uv run --locked alembic upgrade head
uv run --locked uvicorn svaar.app:create_app --factory --reload --no-access-log
```

Visit `http://127.0.0.1:8000/health`, `/ready`, and `/docs`.
`/health` reports process liveness without touching the database. `/ready` executes `SELECT 1`:
200 when PostgreSQL answers, or a sanitized 503 when it does not. It is a connectivity probe,
not a schema-version or external-provider readiness check. Startup is lazy so a database outage
does not prevent liveness checks. SQL connection/query timeouts default to three seconds;
DNS, OS, and connection-pool behavior can add time to that budget.

## Run everything in containers

```sh
docker compose up --build --wait app
docker compose logs app
docker compose down
```

Compose starts PostgreSQL, waits for its health check, runs the baseline migration as a one-shot
service, then starts the unprivileged application. PostgreSQL persists in the `postgres_data`
volume. `down` preserves data. Do not delete the volume unless its data is disposable.
Only localhost ports 8000 and 5433 are published. `.env` and `plans/` are excluded from image
build context, not from the repository. Docker image tags are versioned but not digest-pinned.

Compose constructs its internal database URL from `POSTGRES_*` and uses host `db`, port 5432;
the host application's URL uses localhost:5433. Changing `SVAAR_DATABASE_URL` alone does not
change Compose's internal database. The provided local passwords use URL-safe characters;
percent-encode reserved characters in custom connection URLs. Existing PostgreSQL volumes
retain their original users/passwords when environment values change.

## Configuration

Settings read environment variables before optional `.env` values. Invalid settings fail
application construction; importing modules does not require credentials or create connections.

| Variable | Default / requirement |
| --- | --- |
| `SVAAR_DATABASE_URL` | Required complete `postgresql://` or `postgresql+psycopg://` URL |
| `SVAAR_ENVIRONMENT` | `development`; also `test` or `production` |
| `SVAAR_LOG_LEVEL` | `INFO`; DEBUG, WARNING, ERROR, CRITICAL also supported |
| `SVAAR_DATABASE_TIMEOUT_SECONDS` | `3`, integer from 1 to 30 |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Local Compose initialization only |
| `SVAAR_TEST_DATABASE_URL` | Optional dedicated database for PostgreSQL tests |

Keep real credentials out of source control and logs. Production must inject its own secrets,
database URL, and HTTPS/access boundary. Authentication is intentionally not implemented;
this foundation is not an authenticated public application. Production disables docs/OpenAPI.

Logs are JSON with timestamp, level, logger, event message, and optional exception type.
Infrastructure errors never log raw SQL, exception text, request bodies, headers, or connection
URLs. Access logging is disabled in supplied run commands; HTTP/SQL client diagnostic logs are
suppressed. This is not a general secret scrubber: new code must use fixed event names and
never pass sensitive payloads into log messages or response headers.

## Endpoints and transactions

Infrastructure probes remain unversioned. Add each feature's `APIRouter` in its own package,
then include it in `api/router.py`; all business endpoints inherit `/api/v1`. No business
endpoints are registered yet. Use Pydantic request/response models and explicit status codes.
Synchronous SQL handlers/dependencies use `def` so FastAPI runs them in its thread pool.
Never call blocking SQL directly inside an async endpoint.

Errors use `{"error":{"code":"...","message":"..."}}`. Validation failures add `details`
containing only locations and error types, not rejected input. HTTP exceptions retain status
and headers but use a generic status phrase; raw `detail` is intentionally not reflected.
Unexpected errors return generic 500 responses. Use the common error response model when
documenting additional endpoint errors.

Use `Depends(get_session)` from `svaar.db` for a request-scoped SQLAlchemy session. The caller
owns the transaction and commits successful writes explicitly. Session context exit closes the
session and rolls back uncommitted work. Never share a session between requests or jobs.
External side effects must not be assumed atomic with a database commit.

## Migrations

```sh
uv run --locked alembic current
uv run --locked alembic upgrade head
uv run --locked alembic check
uv run --locked alembic revision --autogenerate -m "describe schema change"
uv run --locked alembic upgrade head --sql
```

The empty `0001` baseline creates only Alembic's version table. No `create_all` runs at startup.
Future models inherit `svaar.db.Base`; import their modules in `migrations/env.py` before
autogenerating. Review generated SQL and format/lint new revisions. Check constraints must
have explicit names to use the shared naming convention. Coordinate migration heads across
teammates; resolve concurrent heads deliberately before merging. Run migrations once per
deployment, before starting application workers. For an existing Compose deployment, rerun
the migration service explicitly before recreating the app:

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

Default tests need no running database: they exercise lifecycle cleanup, liveness, mocked
readiness success/failure, a closed local database port, settings, sessions, safe errors,
and JSON logging. PostgreSQL tests skip unless `SVAAR_TEST_DATABASE_URL` is set. That database
must be dedicated and disposable: tests run Alembic upgrades/checks and inspect the schema.
For local testing, create a separate database in the development container:

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

CI installs the locked environment, checks formatting/lint, runs migrations and tests against
PostgreSQL, and validates Compose. Container build/startup should also be checked locally.

## Team conventions

Work within the owning module; coordinate shared config, API composition, dependencies, and
migrations. Keep new provider integrations behind adapters and mock them in tests. Add only
implemented endpoints; preserve the boundary between observations and simulations. Tests should
verify behavior and trust rules, not just implementation details. Use type hints, standard
docstrings, Ruff, and precise commit messages. Refresh `uv.lock` with `uv lock` after approved
dependency changes. The shared `plans/` directory stays in the repository unchanged; it is not
ignored. Git operations and submission-time document cleanup are performed manually by the team.
