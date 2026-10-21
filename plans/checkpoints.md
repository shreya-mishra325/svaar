# Svaar phase checkpoints

Last reviewed: 2026-10-21 (Asia/Calcutta).

## How to use this checklist

Read `rules.md`, `PLAN.md`, this file and `anomaly.md` before starting a task.
PLAN.md defines requirements; this file tracks implementation phase by phase.
Inspect current code and local edits before relying on a checkbox. Include this
reading order in agent tasks; these documents are not automatically loaded.

- `[x]` means implemented and verified for the stated scope, not merely scaffolded.
- `[ ]` means incomplete, unverified or blocked. Reference blockers by anomaly ID.
- Tick individual deliverables as they pass. Tick a phase-complete box only after
  every required deliverable and its exit check pass.
- Optional items follow PLAN.md's cut order. If deferred, leave them unticked and
  record the team's decision; an omission is not implemented work.
- Dates below are plan targets, not evidence of completion. Independent tasks may
  proceed in parallel where dependencies and ownership boundaries permit.
- At phase closure record date, owner if known, changed files, executed checks and
  results, integration status and remaining limitations under that phase.

Current position: Phase 0 is complete for local infrastructure. Phase 1 is in
progress: its local identity, action gate, confirmation and decision-policy work is
verified. Phase 2 has a tested shared agent core and a standalone mocked Jev
adapter, but no transport, durable chat runtime or live voice composition. The
2026-10-20 Groq native-tool probe is user-reported historical evidence, not a
fresh Mac provider check. Phase 1 and Phase 2 remain incomplete.

## Phase 0: Engineering foundation

- [x] Phase complete: local scaffold and shared infrastructure.
- [x] Python package, dependency lock, settings and structured logging.
- [x] FastAPI lifecycle, health/readiness probes and API error conventions.
- [x] SQLAlchemy sessions, explicit transactions and empty Alembic baseline.
- [x] PostgreSQL persistence, one-shot migrations and unprivileged app image.
- [x] Feature ownership packages, including agent, identity and actions.
- [x] Synchronous voice TurnRunner protocol, without a fake implementation.
- [x] Opt-in gateway service and infrastructure diagnostic, without a fake listener.
- [x] Infrastructure tests, CI definition and development documentation.

Exit check: local startup, database connectivity, migrations, tests, lint/format
and container configuration work without any provider dependency.

Evidence recorded on 2026-10-18: 29 tests passed against real PostgreSQL; Ruff
checks passed; default and gateway-profile Compose validated; updated image built;
gateway diagnostic succeeded; live health and readiness returned 200. Relevant
files: src/svaar/, tests/, migrations/, compose.yaml, Dockerfile, README.md and
.github/workflows/ci.yml. This is historical local evidence, not remote CI or
production verification. Owner: not assigned in this document.

Limits: gateway listener/outbox/jobs remain absent (A-001); operator, policy and
LLM settings are active but other provider settings remain planned (A-003).
The upstream test-client warning remains (A-004).

Mac verification on 2026-10-21: installed pinned uv 0.11.29 and locked Python
dependencies with Python 3.12.15; frontend npm ci and production build passed.
Local development PostgreSQL uses port 5434 and revision 0002. API health/readiness
returned 200. A separate svaar_test database now exists; all 195 tests passed with
no skips against it. Migration drift check, Ruff lint and format checks passed.
A local operator token was generated without displaying it; a fresh application
accepted authentication and rejected an empty create body with 422, while missing
authentication returned 401. No organization or invite was created by that check.
The already-running API must restart to pick up the new token. Credentials remain
private and no provider requests were made. See A-010.

## Phase 1: Contract checks, identity and action safety

Target: Oct 18 to 19. Prerequisite: Phase 0.

- [ ] Phase complete.
- [ ] Verify Caspian auth, inbound mode, stable IDs, sender trust, outbound delivery
  and channels; record the Caspian/Telegram transport decision.
- [ ] Verify Bolna account readiness, turn mode, call-reference delivery and one
  explicitly authorized outbound test call.
- [ ] Select Jev gateway/model and verify its actual request/response contract.
  Vercel selected; versioned-model live acceptance is pending. User approved
  mock-only development after observing that Jev is excluded from free credits.
  No purchase was made by the agent.
- [x] Implement scoped identities, expiring single-use invites and trusted bindings.
- [x] Implement the actions registry/dispatcher, argument validation, role/org/channel
  checks, configured risk tiers and execution audit.
- [x] Implement owner-bound atomic confirmations, expiry, execution authorization
  and an explicit uncertain-provider-outcome policy.
- [ ] Implement typed Jev adapter, confidence policy, fallback and decision audit.
  Policy, per-question fallback, audit and the standalone Vercel adapter have
  offline coverage. Live verification and runtime settings/composition remain
  pending (A-002); mocked success does not complete this deliverable.
- [x] Define P0 intent/usability schemas and deterministic mission-guard interface.
- [ ] Introduce validated feature settings with process-specific credential wiring.
  Operator, invite, confirmation and policy settings are active; provider settings
  arrive with their adapters (A-003).

Exit check: unconfirmed tier-2 tools never execute; concurrent confirmations cannot
create duplicate local execution attempts; authorization is rechecked; invalid or
unavailable Jev responses fall back safely; mission limits are enforced. Required
quality checks pass. Contract blockers: A-002; execution ambiguity: A-006.

Evidence recorded on 2026-10-20 (partial; phase not complete). Owner: not assigned
in this document. Local checks only, not remote CI or provider verification:

- `ruff format --check` and `ruff check` passed; `alembic upgrade head`,
  `alembic check`, downgrade to 0001 and re-upgrade passed against PostgreSQL 16.
- `pytest`: 112 passed against real PostgreSQL (29 existing, 83 new), with the
  A-004 warning still present.
- Exit-check items covered by tests: tier-2 tools create a confirmation and never
  run unconfirmed; four concurrent confirmations execute once; role is rechecked at
  execution; wrong, expired, same-channel, other-owner and "yes" confirmations are
  refused; wrong codes lock at the limit; invalid, missing, duplicate and
  unavailable decision answers fall back per question and are audited; voice
  mission allowlists are enforced.
- Container smoke: `docker compose up --build app` migrated to 0002; operator
  routes created an org and invite with the token and returned 401 without it.
- Changed files: src/svaar/config.py, src/svaar/api/{auth,router}.py,
  src/svaar/identity/, src/svaar/actions/, src/svaar/approvals/,
  src/svaar/decisions/, migrations/env.py, migrations/versions/0002_phase1_foundation.py,
  tests/, compose.yaml, .env.example, README.md.

Remaining: provider contract checks and live Jev acceptance (A-002), provider settings,
phone binding challenge (Phase 3), reconciliation for unknown outcomes (A-006), and
team review of the design choices in A-007.

## Phase 2: Shared chat and voice agent runtime

Target: Oct 20 to 21. Prerequisites: identity/action gate and selected transport.

- [ ] Phase complete.
- [ ] Implement transport protocol and the chosen authenticated chat adapter.
  On 2026-10-21 the user explicitly kept the transport decision pending. Do not
  silently select Telegram or enable Caspian; provider-independent work can proceed.
- [ ] Implement durable inbound dedupe, retryable failures and thread/call memory.
- [x] Verify chat LLM native tool calling; implement the bounded adapter.
  User-reported Groq openai/gpt-oss-20b probe on 2026-10-20: three requests,
  native_tool_calls=true, median full non-streaming response 0.516 seconds.
  No first-token or full voice-latency claim. Mac credentials remain unset (A-010).
- [ ] Implement chat/voice profiles, pre-execution round/call limits and deadlines.
  Core profiles, limits and absolute inference deadlines are implemented/tested.
  Full synchronous provider-handler latency remains an acceptance item (A-009).
- [x] Generate registry-based tool policy; dispatch every tool through actions.
- [ ] Implement durable outbox sending with receipt/failure state.
- [ ] Implement and inject TurnRunner without agent/voice implementation imports.
  AgentLoop exists and API composition is optional; trusted call-ID resolution
  and the run_turn binding are not implemented.
- [ ] Integrate transcript usability, intent routing and deterministic mission limits.
  Core gates and mission checks have mocked coverage. Live Jev, call binding and
  transport wiring remain pending; unconfigured voice gates request clarification.
- [ ] Replace gateway refusal with real runtime composition, shutdown and runtime
  health reporting; API readiness is not listener health.

Exit check: invite enrollment, whoami and a read tool work in chat; a resent message
has one effect; unusable/ambiguous speech cannot invoke tools; deadlines and limits
hold. Required quality checks pass. Track A-001 and A-002.

Evidence on 2026-10-21: all 195 existing tests passed on Mac with isolated
PostgreSQL, including agent-loop and Jev HTTP/policy/audit scenarios. Shared
implementation: agent/{llm,loop,profiles,prompts,inference,smoke}.py and
decisions/jev.py. Jev uses synthetic HTTP responses only. No provider was called.
Only whoami is registered as a business tool; confirm_action is dispatcher-owned.
No chat listener, durable inbound/memory/outbox storage or job runtime exists.

## Phase 3: Mission-bound voice transport

Target: Oct 22 to 23. Prerequisite: shared runner and identity/action boundaries.

- [ ] Phase complete.
- [ ] Implement outbound call intent/state and authenticated Bolna adapter.
- [ ] Implement only the selected turn route with per-call reference binding.
- [ ] Persist/idempotently reuse replies and deduplicate status callbacks.
- [ ] Implement the narrow phone_verify challenge before ordinary call missions.
- [ ] Enforce separate voice credentials, status secret and trustworthy IP checks.
- [ ] Implement fixed timeout/error replies, outbox fallback and transcript retention.
- [ ] Restrict tunnel ingress to implemented external routes; keep operator/docs local.

Exit check: an authorized real call verifies the intended phone; a spoken question
reaches the shared agent; retries do not repeat effects; completed is processed
once. Failed calls cannot create contradictory evidence. Required checks pass.

Evidence: Pending. Contract blocker: A-002.

## Phase 4: CI ingestion and incident timeline

Target: Oct 24 to 25. Prerequisites: scoped identity, chat delivery and incident storage.

- [ ] Phase complete.
- [ ] Implement GitHub App client and explicit repository-to-organization mapping.
- [ ] Verify raw-body HMAC, validate payloads and deduplicate delivery IDs.
- [ ] Persist append-only observed events with provenance and stable external IDs.
- [ ] Implement failure fingerprints and an ordered incident timeline.
- [ ] Deliver owner alerts through the outbox; do not automatically rerun workflows.

Exit check: a failing demo workflow produces one scoped incident/chat alert and
its ordered timeline is available through chat and voice. Signature, unmapped-repo
and duplicate-delivery tests pass alongside required quality checks.

Evidence: Pending.

## Phase 5: Evidence-backed claims and guarded escalation

Target: Oct 26 to 27. Prerequisites: events, outbox and verified voice calls.

- [ ] Phase complete.
- [ ] Detect claims and perform deterministic evidence lookup with provenance.
- [ ] Implement claim_check/escalation missions and incident acknowledgement.
- [ ] Classify usable final answers; derive status from persisted evidence.
- [ ] Preserve unverified for missing evidence, unusable speech and failed calls.
- [ ] Implement guarded polling, row claiming and durable escalation intent/state.
- [ ] Add independently validated CI category and adaptive escalation decisions.
- [ ] Record per-question audit and evaluate labelled examples; batch only if the
  verified gateway contract supports it.

Exit check: an overdue unacknowledged incident triggers one authorized call under
concurrent workers; one job failure does not stop others; missing/failed calls never
contradict claims; deterministic code enforces timing, recipients and call limits.
Required quality checks pass.

Evidence: Pending.

## Phase 6: Validated resolution and cross-channel confirmation

Target: Oct 28. Prerequisites: action gate, confirmations, claims and scoped adapters.

- [ ] Phase complete.
- [ ] Implement release-freeze, on-call staffing and deploy/CI capacity constraints.
- [ ] Implement bounded proposal/revision rounds and deterministic validation.
- [ ] Implement confirmation calls with exact nonce and owner/channel/expiry checks.
- [ ] Implement a gated CI action with durable outcomes and no blind risky retries.
- [ ] Optional: Jira read/create adapter, with creation gated as tier 2.
- [ ] Optional: Jev proposal pre-screening, outside the critical voice path.

Exit check: validator rejects a proposal and accepts a valid revision; a risky CI
action waits for owner confirmation across verified channels; duplicate confirmation
attempts do not repeat it. Required checks pass. Address A-006.

Evidence: Pending.

## Phase 7: Isolated replay and exception draft

Target: Oct 29. Prerequisite: timeline and validator-approved proposal.

- [ ] Phase complete.
- [ ] Replay one corrected failed-pipeline sequence in isolated state.
- [ ] Use fake/recorded adapters only; results are explicitly simulated.
- [ ] Prove replay cannot write observed events or call GitHub, Jira or Bolna.
- [ ] Optional: export an exception draft with tier-2 approval.

Exit check: corrected sequence produces labelled simulation with no live effects.
Replay cannot establish production recovery. Required quality checks pass.

Evidence: Pending.

## Phase 8: Integration rehearsal and demo recording

Target: Oct 30. Prerequisite: required incident, claims, decision and voice loop.

- [ ] Phase complete.
- [ ] Run the full alert, call, timeline, claim, negotiation, simulated replay and
  confirmed-action demonstration.
- [ ] Complete at least five real end-to-end calls with authorized participants.
- [ ] Verify duplicate/reordered delivery, provider failures and deadlines.
- [ ] Measure turn latency and time to first audio; confirm units and report medians.
- [ ] Rehearse and record a clean demonstration under three minutes.
- [ ] Show decision/tool audit; label all mocked or simulated behavior.
- [ ] Record team-approved optional cuts and remaining limitations honestly.

Exit check: reproducible recording and evidence-backed metrics exist; required
quality checks pass; no unresolved critical trust-rule failure remains.

Evidence: Pending.

## Phase 9: Submission

Target: Oct 31, morning; exact cutoff must be confirmed by the team.

- [ ] Phase complete.
- [ ] Confirm cutoff and prepare write-up, recording and run instructions.
- [ ] Reconcile checklist/anomaly status against actual code and final checks.
- [ ] Team manually reviews secrets, repository contents and submission-time docs.
- [ ] Team submits and records confirmation; agents do not publish or push.

Exit check: team has evidence of successful submission before the cutoff.

Evidence: Pending.
