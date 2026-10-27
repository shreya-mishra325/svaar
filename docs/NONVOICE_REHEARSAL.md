# Non-voice rehearsal and handoff

Verified locally on 2026-10-28. This guide covers implemented non-voice behavior,
not live provider acceptance or project completion. Models propose, deterministic
code enforces, Bolna speaks.

## Reproduce the offline slice

Use a dedicated disposable PostgreSQL test database. The test fixtures truncate
domain tables. Set SVAAR_TEST_DATABASE_URL locally to that database and load it
explicitly; do not point it at the development database.

```sh
uv run --locked --env-file .env pytest -p no:cacheprovider -q tests/test_nonvoice_rehearsal.py tests/test_ci_jobs.py tests/test_resolution_tools.py tests/test_ci_actions.py tests/test_github_actions.py
```

The fixtures create fake organizations, engineers and workflow observations.
No real GitHub, Caspian, LLM, Jira or Bolna account is needed. The combined rehearsal
checks a failed workflow, fake log enrichment, one private owner alert in the
outbox, timeline/acknowledgement, a claim checked against an observed success,
a rejected/revised/accepted plan, labelled replay, and tracked-draft approval
through a simulated confirmation context. Queued alerts are not live delivery;
the simulated context is not a real voice call.

The agent-facing integration uses these dispatcher tools:

1. list_ci_runs and explain_ci_failure return accepted webhook observations and
   available log fingerprint provenance. They do not fetch current REST state.
   Root cause/category remain unknown; a hash is not a diagnosis.
2. start_negotiation takes incident_id and a concrete Proposal. It loads saved
   operator constraints; the model cannot set policy or invent approval names.
3. request_replay takes incident_id, negotiation_id and an explicit Scenario.
   It requires a current accepted plan and uses fake adapters. Scenario steps are
   proposed input, not proof of what the production pipeline did.
4. approve_exception takes draft_id and creates a nonce confirmation. Approval
   records a local document decision only; it neither waives policy nor deploys.
5. Optional rerun_workflow/cancel_run require a separate owner confirmation and
   exact incident, repository, installation, run and attempt identifiers.

## Configure trusted standing constraints

Operator-only endpoints:

- GET /api/v1/orgs/{org_id}/constraints
- PUT /api/v1/orgs/{org_id}/constraints
- POST /api/v1/negotiations/{negotiation_id}/exception-draft
- GET /api/v1/exception-drafts/{draft_id}

PUT accepts {"expected_revision": 0, "constraints": {...}} for the first complete
release/staffing/capacity set. For updates, use the current returned revision;
a stale replacement receives 409. All three agent rule sets update atomically.
Missing policy never becomes permissive defaults. No model tool can edit it.

Negotiations retain the snapshot and revision. A policy change before draft
approval or replay requires a new negotiation. Draft content and completed
approval records are immutable. Existing operator POST /negotiations with
request-supplied constraints remains available for experiments, but those
legacy snapshots cannot authorize the new agent replay or tracked draft path.

Use the synthetic freeze, staffing and deploy-slot conflict in the rehearsal
fixture as an example. The team must supply its actual rules and engineer labels.
Constraint revisions are planning snapshots, not live calendar reservations.

## Opt in to runtime CI log grouping

Defaults remain disabled. No private .env was edited.

- Apply migrations with uv run --locked alembic upgrade head.
- Set SVAAR_GITHUB_ENRICHMENT_ENABLED=true in the API and CI worker environments.
- Configure the paired GitHub App ID/base64 RSA private key and explicit repo,
  installation, organization and owner mapping. Keep secrets local.
- Run uv run --locked python -m svaar.jobs for polling, or add --once for one batch.
- Alternatively, use docker compose --profile ci up -d --build app ci-worker.
  This is an explicit startup command for the team, not something run during tests.

The CI worker is a process in the same modular monolith/image. Log downloads run
separately so they cannot stall chat polling. It needs no Redis, queue broker or
additional dependency. It has no heartbeat health claim; inspect process logs
and persisted job state rather than treating container startup as live readiness.

When enabled, signed ingress atomically records observations and jobs without
network I/O. Jobs claim rows with SKIP LOCKED and five-minute lease tokens.
Stale workers cannot finalize a replacement claim. Provider reads occur outside
database transactions; mapping and source scope are rechecked before grouping.
Log-read failures retry after 60 and 120 seconds, then use explicit coarse
workflow/branch grouping. Missing logs never produce a shared empty signature.
Grouping/alert errors roll back together and await lease reclamation.

Matching attempt signatures group repeat failures; different signatures split
incidents. Existing observations and memberships are not rewritten or backfilled.
Earlier unlinked progress facts for the same attempt may gain membership. A
successful run joins an existing incident only with a matching run or one
unambiguous active workflow/branch incident. Ambiguous successes remain observable
without picking a cause. Success never automatically resolves an incident.

Enable and run the worker when enabling webhook deferral. Otherwise jobs persist
pending and alerts wait. This feature needs real App/log acceptance before the
team treats it as a verified production integration.

## Confirmed CI mutations

SVAAR_GITHUB_ACTIONS_ENABLED=false by default. When explicitly enabled with the
paired App credentials, app/gateway compose rerun_workflow and cancel_run. Ordinary
read/log clients continue to request read-only tokens; the dedicated writer needs
Actions write permission. No writer is constructed or invoked from replay.

Every request goes through the action gate. The private nonce message includes
the exact requested action/target. Execution rechecks owner role, confirmed
arguments, signed incident/run evidence and the current mapping. The writer checks
the live repository/run identity, attempt, SHA and status before its single POST.

A unique durable intent is committed before provider I/O. Its business key spans
organization, repository, action, run and attempt, protecting different owners or
fresh nonces from repeating the same effect. Outcomes:

- accepted: GitHub acknowledged the request; HTTP status and safe request ID are
  recorded. This is not proof that a workflow ran, succeeded or recovered.
- rejected: explicit refusal/preflight failure. No automatic retry.
- unknown or placing after a crash: outcome requires operator review. No new nonce
  can bypass the intent. Receipt persistence failure is also treated as uncertain.

Operator-only GET /api/v1/ci-actions/{intent_id} or
GET /api/v1/ci-actions/by-confirmation/{confirmation_id} exposes review metadata.
Compare it with the actual GitHub run/attempt and provider request ID. There is no
automatic reset or reconciliation mutation endpoint; do not delete records to
force retries. Live acceptance remains pending. dispatch_workflow is not
implemented.

Verified HTTP contracts: [workflow rerun](https://docs.github.com/en/rest/actions/workflow-runs#re-run-a-workflow)
and [workflow cancel](https://docs.github.com/en/rest/actions/workflow-runs#cancel-a-workflow-run).
Tests use synthetic keys and mocked HTTP only.

## Remaining work and teammate boundary

The teammate owns Bolna turn/status wiring and real calls. These changes do not
alter voice routes/runtime or hosted agents. Confirmation tests simulate trusted
contexts; they do not prove a phone bridge or identity verification.

Remaining non-voice requirements include automatic claim detection, merge-event
evidence, CI category/adaptive escalation decisions and labelled evaluation,
manual incident creation, workflow dispatch, and the final live demo/recording.
Jira remains an optional unimplemented integration. Call-derived evidence,
claim_check/confirmation mission wiring and actual escalation dispatch must be
coordinated with the voice owner. Existing voice mission allowlists are preserved:
request_replay declares voice support but no current mission permits it.
