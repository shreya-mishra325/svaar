# Svaar checkpoints

Last reviewed: 2026-10-18 (Asia/Calcutta).

## Purpose and reading order

This is a shared implementation checkpoint, not a replacement for requirements.
At task start, read `rules.md`, `PLAN.md`, this file, and `anomaly.md`, then inspect the code
and local changes relevant to the task. Read `CEREBRO_CONTEXT.md` only when a
Cerebro reference pattern is relevant. Cerebro's source is not in this workspace.

`PLAN.md` defines the target; executable code and executed checks establish what
exists. A package, protocol, configuration comment, or planned route is not an
implemented feature. These documents are not automatically loaded agent context;
include them in the team's agent task instructions.

## Current architecture checkpoint

- Svaar is an independent FastAPI modular monolith for engineering incidents.
  It has no Cerebro runtime dependency. Commerce is no longer the target domain.
- One shared agent loop will serve chat and voice. All business tools must pass
  through `actions`, including authorization, mission/channel limits and risk tiers.
- `agent` and `voice` must not import each other. Application composition will
  inject a structural implementation of `voice.contracts.TurnRunner`.
- Jev decides, deterministic code enforces, Bolna speaks. Bolna's function-mode
  wrapper may expose only `ask_svaar`, not business tools.
- Observed events and simulated results remain separate. Missing evidence or a
  failed call cannot establish contradiction.

## Completed foundation

| Checkpoint | Evidence / implementation |
| --- | --- |
| Python package and locked environment | `pyproject.toml`, `uv.lock`, `src/svaar/` |
| Application lifecycle and configuration | `app.py`, `config.py`; no database connection on module import |
| Database/session lifecycle | `db.py`; explicit commit ownership, scoped sessions, pool disposal |
| Liveness and database readiness | `/health` and `/ready` in `api/health.py` |
| API/error/logging conventions | `/api/v1` composition, sanitized error envelope, structured logging |
| Empty migration baseline | `migrations/versions/0001_baseline.py`; no domain tables |
| Feature ownership packages | `agent`, `identity`, `actions`, plus existing feature packages |
| Shared voice boundary | Synchronous `TurnRunner` protocol in `voice/contracts.py`; no implementation injected |
| Container foundation | Same image for app/gateway, PostgreSQL volume, one-shot migrations |
| Gateway infrastructure diagnostic | `python -m svaar.gateway --check`; opt-in Compose service |
| Tests and CI definition | `tests/`, `.github/workflows/ci.yml`; remote CI has not been observed |

## Last executed validation

Recorded from the local scaffold update on 2026-10-18, including uncommitted work.
These results are historical evidence, not a guarantee about subsequent edits.

- 29 pytest tests passed with real PostgreSQL, including migrations and readiness.
- Ruff lint and formatting checks passed.
- Default and gateway-profile Compose configurations validated.
- Updated container image built; gateway infrastructure diagnostic exited successfully.
- The running app returned 200 for both `/health` and `/ready`.
- One upstream Starlette/httpx deprecation warning remains; see `anomaly.md`.
- No provider calls, chat connectivity, agent turns, or domain features were validated.

## Next implementation checkpoints

All are pending; ownership has not been assigned in this file. Follow PLAN.md for
the full schedule and acceptance tests rather than duplicating it here.

1. **Identity, actions, approvals:** scoped identities and invites, one validated
   dispatcher, enforced risk tiers, atomic confirmation decisions and execution audit.
2. **Shared agent and decision path:** verified transport contract, dedupe, memory,
   bounded tool loop, outbox, voice intent/usability decisions and mission guard.
3. **Voice and CI:** authenticated mission-bound calls, turn/status idempotency,
   GitHub signature/delivery handling, explicit repository mapping and incident events.
4. **Full incident loop:** evidence-backed claims, guarded escalation, deterministic
   resolution validation, isolated replay and exception draft.

The gateway listener, outbox sender and job loop are not implemented. Default
gateway startup exits with code 2 intentionally; `--check` is not channel readiness.
Feature variables in `.env.example` are comments, not active Settings fields.

## Handoff update rules

- Before claiming completion, identify the actual files and executed checks.
  Distinguish implemented, mocked, blocked and not run.
- Update the relevant checkpoint after a meaningful change. Record date, owner
  when known, scope, validation and remaining work. Do not invent ownership.
- Add unresolved failures, ambiguities or contract gaps to `anomaly.md` and refer
  to their IDs here when they affect the next task.
- Inspect existing local edits before changing shared files; do not overwrite a
  teammate's work or equate local completion with a merged/deployed feature.
- Keep secrets, transcripts, phone numbers and private payloads out of both files.
- Git/GitHub operations remain manual. Do not commit, push, change branches or
  edit Git configuration on the team's behalf.
