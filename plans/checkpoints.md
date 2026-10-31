# Svaar phase checkpoints

Last reviewed: 2026-10-31 (Asia/Calcutta).

## How to use this checklist

Read rules.md, PLAN.md, this file and anomaly.md before starting work.
The incoming main version of PLAN.md is authoritative per the user's Oct 26
instruction. The working file was verified byte-for-byte identical to it; neither
branch had a different PLAN.md in this merge. Checkpoints record progress and
cannot waive plan requirements. Phase numbers, targets and exit criteria
are unchanged. A target date is not evidence of completion.

Every phase separates three kinds of progress:

- **Implementation:** the stated code or artifact exists for the exact scope shown.
- **Offline verification:** the stated checks passed with isolated state and fake
  providers. This does not establish live account access, calls or delivery.
- **Live acceptance:** the required real integration or final user flow was verified.
  Credentials saved locally are configuration, not live acceptance.

[x] applies only to that specific item. Keep partially implemented items split,
rather than hiding missing software inside a live-provider blocker. Phase complete
requires every mandatory implementation, verification and acceptance item plus the
original exit check. Optional cuts stay unticked with a recorded team decision.
Never infer completion from scaffolding, a mock, a date or a configured key.

Record dated evidence, files, results, integration status and limitations. Preserve
earlier evidence in the history below; its old remaining-work notes are historical.
Agents never stage, commit, push or change Git state. Live messages/calls require
explicit authorization covering the action and target.

## Current position

Latest deployment verification: **784 tests passed without skips on 2026-10-31**,
using a new disposable PostgreSQL instance. Ruff lint/format, Docker image build
and isolated demo Compose validation passed. The new svaar-demo database is at
0026 with clean drift checks and verified volume persistence after restarting
db/app/ingress. Those three private services are healthy; the API binds only
127.0.0.1:18000. Existing development data was not modified. Earlier 779-test and
development database checks remain historical evidence. Existing warning: A-004.

Read-only provider checks passed: Caspian connection/poll, Bolna account/agent,
and Groq native-tool inference (host and actual image). No messages or calls.
Public tunnel, actual gateway processing/delivery, GitHub delivery and Bolna
turn/status acceptance remain unverified. The named-tunnel target is superseded by the user's Render Free decision.
A Free database in Singapore is user-reported; web-service publication, credentials
and deployment approval are pending (A-030).

| Phase | Implementation | Offline verification | Live acceptance |
| --- | --- | --- | --- |
| 0: Foundation | Complete | Passed | Required local startup verified |
| 1: Contracts and safety | Safety core done; provider composition partial | Core and adapter mocks passed | Provider checks incomplete |
| 2: Shared runtime | Chat/gateway/voice core and authenticated turn binding done | Core and persistence checks passed | Complete chat/voice flow pending |
| 3: Voice transport | Calls, challenges, status receipts, turn route and operator dispatch done | Implemented scope passed | Real verification call pending |
| 4: CI and timeline | Ingress, leased log grouping, CI read tools, ownership, owner outbox and manual creation implemented | Ingress checks passed | Real incident/alert/timeline pending |
| 5: Claims and escalation | Claims, merge evidence, claim_check answers, detection, escalation advice and dispatch guards done; live dispatch and tuning pending | Passed | Pending |
| 6: Resolution and confirmation | Standing constraints, agent negotiation and confirmed rerun/cancel implemented; dispatch pending | Implemented domain scope passed | Pending |
| 7: Replay | Agent replay bound to accepted plan; tracked draft export/approval implemented | Isolation and approval tests passed | Required simulation demonstration pending |
| 8: Rehearsal | Non-voice fixture and guide implemented | Mocked non-voice slice passed; full rehearsal pending | Calls, timing and recording pending |
| 9: Submission | Not started | Final review pending | Team submission pending |

Configuration note, 2026-10-24: the user reports adding SVAAR_BOLNA_API_KEY.
The latest saved-file check confirms both the API key and agent ID are present.
Settings validation and BolnaClient construction/cleanup passed without any HTTP
request. No value was displayed. Configuration is ready for explicit adapter
use. Authenticated GET account and agent checks subsequently passed on Oct 24:
wallet positive, capacity available, configured agent processed with a conversation
task. No call was placed; turn delivery remains unverified (A-014).

Voice integration handoff: the user assigned remaining Bolna wiring to a teammate.
The configured tunnel/webhook returned HTTP 401 initially, then HTTP 422 after
configuration changes. Payload validation remains unresolved; do not mark
callback processing, the conversation bridge or real-call acceptance complete.

Next demo-critical step: live acceptance. Configure the Bolna agent for the turn route
(README, Bolna voice turn route) and place one explicitly authorized call. Owner alerts, claims,
claim_check answers, escalation preparation and confirmed CI actions are implemented
offline; all of their live acceptance remains incomplete.
The optional classifier is implemented but disabled by default until explicitly
enabled and accepted live. Voice bridge/reference/retry wiring stays with the teammate. No separate stable sender-ID contract is required for
Caspian under the approved MVP address policy (A-011).

## Phase 0: Engineering foundation

Prerequisite: none.

- [x] Phase complete: required local foundation scope.

### Implementation

- [x] Python package/lock, settings, logging and modular ownership boundaries.
- [x] FastAPI lifecycle, health/readiness and sanitized API errors.
- [x] Synchronous SQLAlchemy sessions, PostgreSQL and Alembic baseline.
- [x] Compose migration flow, unprivileged app image and opt-in gateway diagnostic.
- [x] TurnRunner protocol, infrastructure tests, CI definition and run documentation.

### Offline verification

- [x] Infrastructure tests, lint/format, migrations and Compose configuration passed.
- [x] Mac locked dependency installation and frontend production build verified.

### Live acceptance

- [x] Required local database/container startup and health/readiness verified.
- No external provider acceptance is required for Phase 0. This does not establish
  a running chat listener, deployed production app or remote CI success.

Exit check: local startup, database connectivity, migrations, tests, lint/format
and container configuration work without any provider dependency.

Evidence: historical Oct 18 and Oct 21 checks retained below; later migrations
and runtime work supersede their old scaffold-only limitations.

## Phase 1: Contract checks, identity and action safety

Target: Oct 18 to 19. Prerequisite: Phase 0.

- [ ] Phase complete.

### Implementation

- [x] Scoped organizations/principals, expiring single-use invites and trusted bindings.
- [x] Registry/dispatcher, validated arguments, org/role/channel checks and execution audit.
- [x] Owner-bound atomic confirmations, expiry and durable uncertain execution states.
- [x] Typed decision engine interface, confidence policy, per-question fallback and audit.
  Jev adapter/provider tests removed; optional existing-chat-model classifier
  implemented and composed behind an explicit opt-in switch (A-022).
- [x] P0 usability/intent schemas and deterministic mission allowlists.
- [x] Implemented feature settings: operator, LLM, Caspian, Bolna adapter and GitHub HMAC.
- [x] Voice route credentials: SVAAR_VOICE_TURN_MODE and a separate 32+ character
  SVAAR_VOICE_TURN_TOKEN, validated with the LLM settings. Jev runtime settings were
  dropped with the plan change on 2026-10-27 (A-022).
- [ ] Operator reconciliation path for uncertain external execution (A-006).
- [ ] Close outstanding implementation-design decisions recorded in A-007.

### Offline verification

- [x] Unconfirmed tier-2 actions do not execute; concurrent confirmations run once locally.
- [x] Owner/channel/expiry/role rechecks and invalid-argument cases pass.
- [x] Missing/invalid/unavailable decision answers fall back independently and are audited.
- [x] Mission limits cannot be expanded by model/intent output.
- [x] Implemented standalone provider contracts have mocked HTTP tests.
- [ ] Full provider composition and real-adapter uncertain-outcome recovery checks.

### Live acceptance

- [x] Caspian Telegram selected; authenticated connection/poll reads passed on Oct 23.
- [x] Caspian sender-address policy explicitly accepted by the user (A-011);
  this is an MVP decision, not proof of immutable usernames.
- [ ] Caspian outbound delivery and full enrollment/read-tool exchange.
- [x] Verify Bolna account access, positive wallet, available concurrency and processed agent.
- [ ] Choose and verify Bolna turn mode and bridge configuration.
- [ ] Verify Bolna call-reference delivery and one explicitly authorized outbound call.
- Removed by plan change on 2026-10-27: live Jev model/gateway verification. There is no
  decision-model provider left to verify (A-022).

Exit check: unconfirmed tier-2 tools never execute; concurrent confirmations cannot
create duplicate local execution attempts; authorization is rechecked; invalid or
unavailable decision answers fall back safely; mission limits are enforced. Required
quality checks pass. Contract blockers: A-002; execution ambiguity: A-006.

## Phase 2: Shared chat and voice agent runtime

Target: Oct 20 to 21. Prerequisites: identity/action gate and selected transport.

- [ ] Phase complete.

### Implementation

- [x] ChannelTransport and Caspian private Telegram adapter under approved MVP policy.
- [x] Durable inbound dedupe, resumable received work and conservative uncertain states.
- [x] Scoped chat/call history and exclusion of invites/codes from later model history.
- [x] Bounded OpenAI-compatible adapter, chat/voice profiles and pre-execution limits.
- [x] Registry-generated tool policy; business tools dispatch through actions.
- [x] Durable outbox with receipts, safe rejection backoff and no blind uncertain retries.
- [x] Internal TurnRunner injection sharing AgentLoop without agent/voice cross-imports.
- [x] Usability/intent gates and deterministic mission checks in the shared voice path.
- [x] Heuristic-first speech precheck and at most one grouped classifier request
  per voice turn, bounded by the existing deadline, with per-slot fallback/audit.
- [x] Gateway polling, persistent cursor, stream ownership, shutdown and heartbeat health.
- [x] Authenticated voice call-reference and retry-index mapping: the llm_endpoint
  index is the count of earlier caller messages in replayed history (A-013, A-028).
- [ ] Live verification that Bolna delivers the reference and stable history (A-028).
- [ ] Voice confirmation ticket delivery and operator recovery tooling (A-006/A-013).
- [ ] Bound/verify remaining synchronous provider handlers for the full voice budget (A-009).

### Offline verification

- [x] Real PostgreSQL enrollment -> whoami -> outbox -> duplicate handling passes.
- [x] Isolation, concurrent workers, durable cursor restart and crash boundaries pass.
- [x] Private-code chat delivery -> fake call -> exact voice verification passes.
- [x] Unusable/ambiguous speech cannot run tools; limits and late inference checks pass.
- [x] Classifier malformed/duplicate/partial/low-confidence answers, delayed results,
  credential reuse, no-tool requests and historical audit preservation tests pass.
- [x] Gateway composition, resource cleanup and stale heartbeat checks pass.
- [ ] Full provider-handler and end-to-end voice latency validation.

### Live acceptance

- [x] User-reported Groq native-tool probes passed on Oct 20 and Oct 21.
  Mac median was 0.5919 seconds for the full non-streaming response, not first token.
- [ ] Real private enrollment, whoami and an additional read tool work through chat.
- [ ] A real redelivery produces one effect and verified outbound delivery.
- [ ] A trusted real voice turn reaches the same agent and action gate.
- [ ] Live voice usability/intent routing and complete turn latency pass.

Exit check: invite enrollment, whoami and a read tool work in chat; a resent message
has one effect; unusable/ambiguous speech cannot invoke tools; deadlines and limits
hold. Required quality checks pass. Track A-001 and A-002.

## Phase 3: Mission-bound voice transport

Target: Oct 22 to 23. Prerequisite: shared runner and identity/action boundaries.

- [ ] Phase complete.

### Implementation

- [x] Bolna placement/execution adapter with sanitized errors and provider retries disabled.
- [x] Durable ordinary-call intents, receipt scope checks and uncertain-placement policy.
- [x] Internal mission-bound runner, per-call history and idempotent indexed replies.
- [x] Pending phone challenge, exact-code action, expiry/attempt/cooldown safeguards.
- [x] Private /verify_phone issuance, atomic code outbox and pending verification intent.
- [x] Narrow pending-number exception only for phone_verify; ordinary calls require
  verified phones and verification offers only verify_phone_code.
- [x] Durable private fallback follow-ups, dedupe and honest unroutable fallback (A-016).
- [x] Failed/unanswered status receipts queue one verified private outbox follow-up
  per call, atomically with the receipt; absent/ambiguous routes queue nothing.
- [x] Internal hashed call-reference resolver delegates to the guarded indexed runner.
- [x] Authenticated turn route: POST /voice/llm/chat/completions streams OpenAI deltas
  (llm_endpoint) or POST /voice/turn (function); only the configured mode is mounted.
- [ ] Verify provider delivery of reference/retry identity on a real call (A-028).
- [x] Implement status receipt authentication, direct peer-IP checks and durable dedupe.
- [x] Restricted Cloudflare loopback status listener with scoped edge-header checks.
- [ ] Verify real Cloudflare ingress and implement operator balance alerts.
- [ ] Match failed/no-answer/busy terminal call state to PLAN.md section 10 (A-021).
- [ ] Classify completed transcripts, persist evidence and apply retention policy.
- [x] Explicit operator placement (python -m svaar.dispatch) with readiness, incident/claim
  rechecks and per-recipient limits; nothing dials automatically.
- [ ] Automatic call scheduling from prepared intents (not implemented by design yet).
- [ ] Implement transcript retention and voice confirmation-ticket notification delivery.
- [x] Implement a status-only tunnel entry point with operator/docs routes absent.
- [x] User launched the restricted tunnel and configured the hosted status webhook.
- [ ] Teammate handoff: resolve the dashboard sample HTTP 422 and verify accepted
  callback processing against a stored Svaar execution (A-014). Likely cause: the
  dashboard sample carries placeholder IDs; a real execution should validate (A-028).

### Offline verification

- [x] Placement acceptance/rejection/unknown outcomes and no duplicate redial pass.
- [x] Receipt IDs, state progression, final closure and stale-progress rejection pass.
- [x] Exact/leading-zero codes, ownership, expiry, attempts, cooldown and concurrency pass.
- [x] Duplicate/conflicting turns, interrupted execution and no secret-history replay pass.
- [x] Private code delivery withholding, transaction rollback and safe downgrade checks pass.
- [x] Failure follow-up routing, dedupe, recipient revocation and missing-route cases pass.
- [x] Status route authentication, peer-IP rejection, concurrent dedupe, replay/reordering
  and transaction rollback tests.
- [x] Provider turn-route authentication, mounting, fail-closed reference and retry tests.
- [ ] General per-turn transcript retention limit and tests (claim answers are purged).
- [ ] Production call scheduler/readiness and notification timing tests.

### Live acceptance

- [x] Verify Bolna account access/capacity and configured agent processing through GETs.
- [ ] Verify hosted bridge configuration and telephony delivery in an authorized call.
- [ ] Confirm chosen turn mode, call-reference delivery and stable retry identifiers.
- [ ] Explicitly authorized call reaches the intended number and verifies it by code.
- [ ] Spoken request is answered through Svaar; duplicate completed callback applies once.
- [ ] Real timeout/failure produces the intended spoken reply/private follow-up.
- [ ] Verify actual turn latency and restricted ingress.

Exit check: an authorized real call verifies the intended phone; a spoken question
reaches the shared agent; retries do not repeat effects; completed is processed
once. Failed calls cannot create contradictory evidence. Required checks pass.

## Phase 4: CI ingestion and incident timeline

Target: Oct 24 to 25. Prerequisites: scoped identity, chat delivery and incident storage.

- [ ] Phase complete.

### Implementation

- [x] Explicit repository/installation-to-org mapping and operator-only creation route.
- [x] Raw-body HMAC ingress with bounded input, payload validation and delivery-ID dedupe.
- [x] Atomic normalized workflow observations/receipts with stable run-transition keys.
- [x] Append-only observations with source provenance and occurrence timestamps.
- [x] Standalone GitHub App RS256/token adapter and scoped repository/run reads.
- [x] Compose the App client into the opt-in CI worker with bounded adapter lifecycle;
  confirmed rerun/cancel use a separate writer and execution deadlines (A-027).
- [x] Standalone failed-workflow log download with credential-isolated storage request
  and bounded in-memory ZIP processing.
- [x] Incident aggregate/linkage and repository/workflow/branch grouping.
- [x] Versioned normalized log-tail signatures and org/repo/workflow/branch fingerprint helper.
- [x] Explicit attempt-bound enrichment with append-only digest/provenance storage
  and provider I/O outside database transactions.
- [x] Opt-in leased CI enrichment and log-based grouping without rewriting observed
  facts or existing membership; bounded retry/coarse fallback (A-026).
- [x] Organization-scoped ordered timeline and get_timeline/list_incidents actions.
- [x] Explicit same-org repository owner and per-incident owner snapshot (A-018).
- [x] Idempotent private alerts to that owner only; no missing-owner broadcast fallback.
- [ ] Configure a real owner and verify actual alert delivery.
- [x] Operator POST /incidents manual-creation route: mapped repository, same-org owner,
  automatic-grouping fingerprint, 409 on an active duplicate, owner alert queued.
- [x] Signed observation -> guarded CI job -> incident -> owner outbox preparation,
  without automatic workflow reruns; real provider/delivery acceptance remains below.
- [x] list_ci_runs/explain_ci_failure read scoped accepted observations and available
  log provenance; root cause/category remain unknown.

### Offline verification

- [x] Synthetic HMAC, malformed/oversized/ambiguous input and mapped-scope checks pass.
- [x] Duplicate/conflicting/concurrent deliveries and atomic rollback checks pass.
- [x] Unmapped repos/installations are rejected; operator mappings cannot be overwritten.
- [x] PostgreSQL rejects observation updates/deletes; source time survives arrival reordering.
- [x] Mocked App JWT/token/REST contracts, cache refresh/concurrency and org isolation.
- [x] Synthetic workflow-log download, archive limits, credential isolation and
  normalized/scoped signature tests.
- [ ] Live App/log retrieval acceptance.
- [x] Implemented grouping/linkage, occurrence-order and scoped timeline/action tests.
- [x] Explicit owner routing, scoped provisioning, backfill, atomic rollback and
  concurrency tests.
- [x] Runtime log grouping, distinct/repeated signatures, lease reclamation, stale
  tokens, mapping changes, retries and atomic grouping/outbox rollback tests.
- [ ] Workflow failure -> one incident -> one owner alert -> chat/voice timeline slice.

### Live acceptance

- [ ] Configure a real GitHub App/webhook secret, installation and explicit repo mapping.
- [ ] One real failed demo workflow creates the intended scoped incident and chat alert.
- [ ] Real redelivery does not repeat the incident/alert.
- [ ] Its ordered timeline is available in chat and on an authorized voice call.

Exit check: a failing demo workflow produces one scoped incident/chat alert and
its ordered timeline is available through chat and voice. Signature, unmapped-repo
and duplicate-delivery tests pass alongside required quality checks.

## Phase 5: Evidence-backed claims and guarded escalation

Target: Oct 26 to 27. Prerequisites: events, outbox and verified voice calls.

- [ ] Phase complete.

Claims, workflow and merge evidence, claim_check call answers and claim detection are
implemented and verified offline. Guarded local escalation preparation is implemented.
Live dialing and every live acceptance item remain pending (A-024, A-025).

### Implementation

- [x] Scoped authored claims, source dedupe and deterministic exact workflow-success
  evidence lookup with append-only provenance.
- [x] Dispatcher-owned recording/checking/listing and operator read-only claims route.
- [x] Signed merged pull_request observations and exact fix_merged evidence: the claim's
  pull request, the incident's repository and a merge no earlier than the incident (A-025).
- [x] Optional audited claim-detection slot; a detection only suggests record_claim and
  never records a claim or sets status (A-025).
- [x] Incident acknowledgement action is registered through the dispatcher.
- [x] claim_check handlers: verify_claim prepares one bound pending intent for the claim
  author (tier 2 when the author is not the incident owner); record_claim_answer is
  offered only inside that call and stores the caller's exact words (A-025).
- [x] Completed-call answers are classified once by the claim-answer slot; only a
  confident model confirmed/denied becomes evidence, and status is derived from it.
- [x] Missing evidence, unusable speech, fallback/low-confidence answers and failed or
  unanswered calls stay unverified; answer text is purged once finalized. A failed
  claim_check call also notifies its requester once (PLAN.md section 10).
- [x] Guarded preparation jobs, row claiming, durable incident-bound intents,
  confirmed-delivery grace and per-recipient preparation cooldown (A-024).
- [x] Dispatch-time recheck of incident ownership/open state and claim status, a
  readiness gate and a per-recipient 24-hour call limit, composed by
  create_call_service (offline; A-027).
- [ ] Live dispatch: placement is operator-run only (python -m svaar.dispatch --place);
  live readiness, limits and placement remain unverified (A-024, A-027).
- [x] CI failure category and adaptive escalation asked together once per job, each
  validated and audited separately; advice can delay one grace period, never hasten.
- [ ] Labelled evaluation set and threshold tuning for these slots (plan section 9).
- [ ] Use batching only if the actual gateway contract verifies support. Not applicable
  since the 2026-10-27 plan change removed that gateway (A-022); left unticked.

### Offline verification

- [x] Initial workflow claim confirmation, absent/failed evidence, merge ambiguity,
  statement/target mismatches, dedupe, org isolation and immutable evidence tests pass.
- [x] Call-derived evidence transitions, merge evidence and automatic detection tests.
- [x] Wrong-person, unsure, callback, fallback and failed/unanswered-call cases remain
  unverified; failed calls discard answers without evidence.
- [x] Concurrent preparation produces one intent; one failed job rolls back without
  stopping another recipient's job.
- [x] Timing, recipient authorization, call limits and per-question decision audit pass.

### Live acceptance

- [ ] An overdue unacknowledged incident triggers one explicitly authorized call.
- [ ] A real usable answer produces evidence with provenance.
- [ ] Missing/failed calls do not contradict claims; acknowledgement suppresses escalation.

Exit check: an overdue unacknowledged incident triggers one authorized call under
concurrent workers; one job failure does not stop others; missing/failed calls never
contradict claims; deterministic code enforces timing, recipients and call limits.
Required quality checks pass.

## Phase 6: Validated resolution and cross-channel confirmation

Target: Oct 28. Prerequisites: action gate, confirmations, claims and scoped adapters.

- [ ] Phase complete.

The agent uses saved constraints for negotiation and isolated replay. Confirmed
rerun/cancel and tracked draft approval pass offline domain tests; real cross-channel
CI acceptance and workflow dispatch remain pending.

### Implementation

- [x] Request-supplied release-freeze, staffing and deploy/CI constraints (A-019).
- [x] Bounded deterministic revisions, persisted rounds and operator validation routes.
- [x] Standing per-agent constraints store with atomic operator updates, revision
  conflict checks and historical negotiation snapshots (A-019).
- [x] start_negotiation uses operator-saved constraints and refuses invented approvals.
- [ ] Confirmation-call domain flow with exact owner/channel/nonce/expiry checks.
- [x] Opt-in tier-2 rerun_workflow/cancel_run with durable attempt-level intent,
  receipt recording, scope/role rechecks and no blind risky retry (A-027).
- [ ] dispatch_workflow tool and adapter.
- [ ] Optional: Jira read/create adapter, creation gated as tier 2.
- Removed by plan change on 2026-10-27: optional Jev proposal pre-screening (A-022).

### Offline verification

- [x] Reject invalid proposals and accept a valid revision in offline tests.
- [x] Mocked CI mutation waits for valid owner confirmation; duplicate/concurrent
  confirmations and new nonces cannot repeat the same target attempt.
- [x] Rejection, timeout and crash states persist; no uncertain mutation is retried.
  Operator receipt inspection is implemented (A-006/A-027).
- [ ] Live reconciliation acceptance and reviewed reconciliation/reset tooling.
- [ ] Optional implemented integrations have scoped adapter/action tests.

### Live acceptance

- [ ] Demonstrate rejected proposal -> valid revision -> validator approval.
- [ ] Authorized real CI action waits for cross-channel confirmation.
- [ ] Duplicate confirmation does not repeat the action; provider receipt is checked.

Exit check: validator rejects a proposal and accepts a valid revision; a risky CI
action waits for owner confirmation across verified channels; duplicate confirmation
attempts do not repeat it. Required checks pass. Address A-006.

## Phase 7: Isolated replay and exception draft

Target: Oct 29. Prerequisite: timeline and validator-approved proposal.

- [ ] Phase complete.

### Implementation

- [x] Operator-supplied corrected pipeline scenario replayed in isolated state.
- [x] Pure in-memory replay with persisted explicitly simulated results.
- [x] Replay isolation and simulated-only database constraint implemented.
- [x] Optional tracked JSON exception draft export with owner-bound tier-2 approval;
  approval changes a local document only and never waives hard constraints.

### Offline verification

- [x] Corrected operator-supplied sequence produces labelled simulation in tests.
- [x] Agent replay requires the same incident's current validator-accepted plan;
  the offline non-voice rehearsal exercises the connection.
- [x] Replay isolation tests reject observed writes/live provider access for current scope.
- [x] Draft export/approval tests cover owner/channel/nonce, role revocation, foreign
  scope, policy changes and immutable draft content.

### Live acceptance

- [ ] Demonstrate the required isolated replay in the integrated demo.
- No live provider action is required or permitted by replay. Simulation never
  establishes production recovery.

Exit check: corrected sequence produces labelled simulation with no live effects.
Replay cannot establish production recovery. Required quality checks pass.

## Phase 8: Integration rehearsal and demo recording

Target: Oct 30. Prerequisite: required incident, claims, decision and voice loop.

- [ ] Phase complete.

### Implementation

- [ ] Complete the alert/call/timeline/claim/negotiation/replay/confirmed-action demo path.
- [x] Reproducible non-voice fixture and run guide in docs/NONVOICE_REHEARSAL.md.
- [ ] Real demo data, integrated run instructions and recording script.
- [ ] Instrument timing and audit display; record units and optional cuts honestly.

### Offline verification

- [ ] Full scenario rehearsal passes with isolated fixtures/adapters.
- [ ] Integrated duplicate/reordering/provider-failure/deadline checks pass.
- [ ] Required quality checks and observed/simulated separation pass.

### Live acceptance

- [ ] At least five real end-to-end calls with authorized participants.
- [ ] Measure turn latency and time to first audio; verify units and report medians.
- [ ] Rehearse and record a clean complete demonstration under three minutes.
- [ ] Show decision/tool audit and clearly label mocked/simulated behavior.
- [ ] Record team-approved optional cuts and remaining limitations.

Exit check: reproducible recording and evidence-backed metrics exist; required
quality checks pass; no unresolved critical trust-rule failure remains.

## Phase 9: Submission

Target: Oct 31, morning; exact cutoff must be confirmed by the team.

- [ ] Phase complete.

### Implementation

- [ ] Confirm exact cutoff and prepare write-up, recording and run instructions.
- [ ] Reconcile checklist/anomalies with the actual final code.
- [ ] Prepare the team's final repository/secrets/submission review.

### Offline verification

- [ ] Final required checks pass; instructions reproduce the demonstrated build.
- [ ] Team reviews secrets, repository contents and submission-time documents.
- [ ] Recording/write-up accurately distinguish live, mocked and simulated behavior.

### Live acceptance

- [ ] Team submits before the confirmed cutoff.
- [ ] Team records successful submission confirmation.
- Agents do not publish, commit or push on the team's behalf.

Exit check: team has evidence of successful submission before the cutoff.

## Historical evidence through 2026-10-23

The records below preserve earlier results and decisions. They are not the current
checklist: old statements about missing code, ports, migrations or credentials may
have been superseded by later entries and the current phase sections above.

<details>
<summary>Expand dated implementation and verification history</summary>

#### Phase 0: retained dated evidence

Evidence recorded on 2026-10-18: 29 tests passed against real PostgreSQL; Ruff
checks passed; default and gateway-profile Compose validated; updated image built;
gateway diagnostic succeeded; live health and readiness returned 200. Relevant
files: src/svaar/, tests/, migrations/, compose.yaml, Dockerfile, README.md and
.github/workflows/ci.yml. This is historical local evidence, not remote CI or
production verification. Owner: not assigned in this document.

Limits: gateway listener/jobs remain absent and outbox is not running (A-001); operator, policy and
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

#### Phase 1: retained dated evidence

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

#### Phase 2: retained dated evidence

Evidence on 2026-10-21: all 195 existing tests passed on Mac with isolated
PostgreSQL, including agent-loop and Jev HTTP/policy/audit scenarios. Shared
implementation: agent/{llm,loop,profiles,prompts,inference,smoke}.py and
decisions/jev.py. Jev uses synthetic HTTP responses only. No provider was called.
Only whoami is registered as a business tool; confirm_action is dispatcher-owned.
At that checkpoint no chat listener, durable inbound/memory/outbox storage or job runtime existed.

Evidence on 2026-10-23: Caspian public OpenAPI fetched successfully (deployed
version 0.1.0); authenticated GET /v1/events returned 200 with an array and the
documented event/data/message envelope. Only field names/counts were printed.
Configured Telegram connection ID/address were missing from the saved .env, so
no connection-specific acceptance is claimed. Public source at commit
718a96d6d04cb76c7ccce942d2532fd4adbfd545 prefers a mutable username for sender
address, so sender_authenticated remains false. No messages were sent.
Implemented: agent/{transport,caspian,caspian_smoke}.py, optional Caspian settings,
gateway-only Compose credentials, offline tests and operator documentation.
Final validation: 226 tests passed against isolated PostgreSQL, Ruff lint/format,
migration drift and gateway-profile Compose checks passed; A-004 remains. Initial
database tests failed while Docker was stopped, then passed after Docker started.
At that adapter checkpoint no schema change or durable runtime was introduced.

Subsequent evidence on 2026-10-23: user authorized continuing available,
provider-independent work. Added agent/{models,runtime,outbox}.py and migration
0003; API composition exposes an optional ChatRuntime without starting a listener.
Fake authenticated enrollment -> whoami -> durable delivery and duplicate handling
are covered through the real dispatcher. Tests cover conversation/org isolation,
locks surviving dispatcher commits, ordered history, invite/nonce exclusion,
post-execution crashes, concurrent sends, recipient revocation, safe rejection
retries/backoff and receipt reconciliation. All 246 tests passed with real isolated
PostgreSQL and fake provider adapters. Ruff lint/format passed. Test DB downgrade
0003 -> 0002 -> 0003 and migration drift check passed; development DB upgraded to
0003 with clean drift check. Database verification used port 5434 explicitly while
the local editor configuration was being updated. No .env values were changed.
The saved connection fields later passed Caspian's read-only smoke: connection
and polling true, identity/outbound false, messages_sent=0. A-011 is now an accepted MVP limitation.
Jev remains mocked; Bolna and incident/claim/negotiation/replay work remain pending.
Phase 2 is not complete: durable polling cursor/worker startup, trusted live sender
identity and voice binding remain required.

Further evidence on 2026-10-23: wired GatewayWorker polling, cursor persistence,
stream ownership, ChatRuntime/outbox/receipt processing and bounded failure backoff.
Added gateway_cursors via migration 0004 for stream position and heartbeat. CLI
--check remains infrastructure-only; --status reports fresh ready/processing vs
not-started/stale/blocked/error/stopped. Opt-in Compose health now uses --status.
Originally normal startup required a separate verified sender-ID contract.
The subsequent user decision below removes that gate; complete channel and
provider configuration is still required. API/voice behavior is unchanged.
All 256 tests passed against isolated PostgreSQL (10 new gateway checks); lint,
format and Compose validation passed. Test migration 0004 -> 0003 -> 0004 and
drift checks passed; development DB is 0004. The A-004 warning remains. No live
gateway process, outbound messages, model requests or calls were started.
Remaining Phase 2 acceptance: live channel flow under the approved address policy,
Bolna call-reference/turn-index mapping, real handler latency and operator recovery.

#### Phase 3: retained dated evidence

Evidence on 2026-10-23 (partial, Phase 3 remains incomplete):
Verified public Bolna call, execution and auto-retry documentation. Implemented
voice/{provider,bolna,calls}.py and migration 0006; active optional
SVAAR_BOLNA_API_KEY / SVAAR_BOLNA_AGENT_ID settings are blank in .env.example.
Client construction makes no request. Existing local credentials were not read.

A pending ordinary call must already have server-owned organization, principal,
mission and verified phone binding. Placement rechecks those before committing
placing; concurrent/repeated invocations cannot send another POST for that intent.
High-entropy references are passed in user_data; only their hashes are stored.
Explicit rejection becomes failed; timeout, invalid acceptance, server failure or
unexpected placement error becomes unknown. Interrupted placing requires review.
Provider auto-retries are disabled. No automatic local placement retries exist.

Read-only execution reconciliation validates execution and agent IDs. Stale
progress cannot reopen an answered/final call. call-disconnected blocks turns
while awaiting completion; terminal status closes the call. No claim/evidence
state is derived here. Transcript and extraction payloads are not persisted by
this minimal receipt adapter.

Verification: 321 tests passed (45 new), Ruff lint/format passed, migration drift
check and test-only 0006 -> 0005 -> 0006 round trip passed. The initial migration
test caught an Alembic naming-convention double prefix; corrected with op.f and
the complete suite then passed. Existing A-004 warning remains. Development
migration was not applied. No live authenticated Bolna request, message or call
was made. No new dependency or service was added.

Remaining: account readiness, phone_verify challenge, authenticated turn/status
routes, verified call-reference/turn-index delivery, callback dedupe, notification
outbox and real authorized call. CallService is internal only; no action handler,
API, application lifespan or job starts it. Contract blockers: A-002 and A-014.

#### Phase 4: retained dated evidence

Evidence on 2026-10-23 (partial): migrations 0009 and 0010 add outbox notification
dedupe plus repo_mappings, webhook_deliveries and events. HMAC is checked over exact
bounded bytes before JSON parsing; database work is offloaded from the async
handler. Only mapped repository/installation pairs create normalized observations.
Delivery IDs and stable run-transition keys prevent repeated effects. Conflicts
return 409, malformed JSON 400, unsupported events 200/handled=false; unmapped
repositories are rejected/logged without payload data. PostgreSQL blocks updates
and deletes of observed events. Raw sender payloads/transcripts are not stored.

Verification: 396 tests passed (37 new), Ruff lint/format and Compose config passed.
Isolated test DB round trip 0010 -> 0008 -> 0010 and drift checks passed.
Development DB upgraded to 0010 with clean drift check. Existing Starlette warning
remains. No live provider calls, messages, GitHub requests or tunnel were started.

Remaining Phase 4 work: GitHub App client, failure fingerprinting, incident
aggregation/linkage, scoped timeline and get_timeline, owner alerts and live
repository acceptance. See A-017 for schema extensions and the minimal ingress
scope. No automatic workflow reruns exist.

#### Additional dated updates

##### Approved MVP sender policy, 2026-10-23

The user explicitly removed the separate verified stable sender-ID contract
requirement. This supersedes earlier A-011 startup/enrollment blocker statements
in this document. Caspian's authenticated API supplies the private sender address;
the adapter now marks eligible private messages sender_authenticated=true.
Invite enrollment, organization/role checks, confirmation gates, private-message
filtering and generic rejection of unauthenticated transport input remain enforced.
Mutable username changes or reassignment can affect bindings; this is an accepted
MVP limitation, not a verified immutable-ID guarantee. No live gateway, messages
or calls were started for this change. Live channel acceptance remains pending.

##### Phase 2 internal voice runner evidence, 2026-10-23

Implemented voice/{models,runtime}.py, agent/voice_runner.py, migration 0005,
TurnRunner contract extension and application lifecycle injection. Agent and voice
implementations do not import each other; application composition joins them.
Ordinary active calls resolve their organization, principal, mission and verified
phone binding from server-owned rows. No call creation/activation endpoint exists.
The pending phone_verify challenge is deliberately not accepted by this runtime.

Stable zero-based turn_index is required for execution. Retries reuse the saved
reply; changed payloads, missing/gapped indices and unknown/closed/unverified calls
are refused. Session advisory locks survive dispatcher commits. Processing/unknown
turns never replay after a crash; unknown turns block later work pending review.
History is scoped to the call and bounded to six completed turns, with codes and
unusable speech excluded from later input history.

Verification: 276 tests passed against isolated PostgreSQL (20 new voice tests);
Ruff lint and formatting passed. Migration drift and test-only 0005 -> 0004 ->
0005 round trip passed. Existing Starlette warning remains. Docker Desktop and
the project database were started for verification. Current Compose published
port is 5433; process-local test configuration used that actual port. No .env
values were edited. Development database migration 0005 was not applied.

Still pending: Bolna authentication/reference/index delivery, phone challenge,
provider callbacks, chat notification delivery for fallback/confirmation, real
handler latency and live chat/voice acceptance. The inherited fixed fallback
mentions messaging, but this internal runner does not yet enqueue such a message.
No provider requests, messages or calls were made. Phase 2 remains incomplete.

##### Phase 3 internal phone verification evidence, 2026-10-23

Implemented identity/{phones,phone_tools}.py and PhoneChallenge storage, registered
verify_phone_code through actions, added a server-resolved challenge identifier
to ToolContext, and extended internal call placement/runtime for phone_verify.
Migration 0007 enforces mutually exclusive contexts: ordinary calls require a
verified-binding reference; verification calls require a challenge and no binding.

Issuance is internal and requires an existing verified non-phone identity.
Codes are six ASCII digits, stored only as salted scrypt hashes, with ten-minute
expiry, three mismatch attempts and one-minute resend cooldown per principal and
target. New challenges cancel prior pending challenges for that principal.
Pending numbers do not create or reserve a globally owned phone binding.
Exact matching creates/verifies only the intended principal's phone binding.
Model proposals cannot replace the raw caller transcript or select the challenge.

Only phone_verify can dial the pending number; its sole offered tool is
verify_phone_code. Ordinary missions still require verified phones. Usability and
intent gates remain enforced. The internal call closes on verification/lockout;
saved indexed replies remain reusable without repeating tools. Verification
utterances and replies are not replayed as later model history.

Verification: 344 tests passed (23 new), with real isolated PostgreSQL and fake
models/providers; Ruff lint/format and test-only 0007 -> 0006 -> 0007 migration
round trip/drift checks passed. Existing Starlette warning remains. Development
migrations were not applied. No new dependencies, .env edits, live provider
requests, messages or calls. Prior ordinary-call-only notes are historical and
superseded for this narrow verification exception.

Remaining: private chat code delivery and issuance wiring, authenticated provider
turn/status routes, verified call-reference/turn-index delivery, callback dedupe,
fallback notifications and authorized live acceptance. No Bolna route or tunnel
was added based on assumed payload fields. Phase 3 remains incomplete.

##### Phase 3 private challenge delivery evidence, 2026-10-23

Added the private identity-enrollment command /verify_phone <E.164 number> to
ChatRuntime, alongside /join. It requires transport-authenticated enrollment,
bypasses inference/history and creates the challenge, pending verification call,
secret outbox message and processed inbound marker in one transaction.
Duplicate messages do not reissue codes. Invalid input/cooldown failures produce
safe durable replies without creating extra challenges or call intents.

Agent receives an injected preparation callback; it never imports voice.
Application and gateway composition supply the callback. It creates only a pending
call intent, never a provider request or automatic dial. Replies explicitly say
the call must be started separately and the phone remains unverified.

Migration 0008 links code outbox entries to their challenges. Sender rechecks
recipient ownership and active challenge immediately before POST. Expired,
canceled, locked, verified or superseded code deliveries are withheld. The salted
hash remains in identity storage; the delivery code exists in the private outbox
only, never conversation history or model requests. Unknown sends never retry.
Downgrade refuses unresolved code deliveries rather than dropping their guards.

Verification: 359 tests passed (15 new chat/phone integration tests), Ruff
lint/format passed, test-only 0008 -> 0007 -> 0008 round trip and drift checks
passed. Tests cover enrollment -> code outbox -> fake call placement/receipt ->
shared-loop exact voice verification, duplicates, rollback, invalid/untrusted
input, cooldown, stale-code withholding and downgrade refusal. The existing
Starlette warning remains. Development database was upgraded through 0008 with
a clean migration drift check, superseding earlier unapplied-migration notes.
Actual Compose host port remains 5433; no .env values were edited.

No live messages, calls, provider requests, gateway process or tunnel were started.
Remaining: authenticated Bolna turn/status routes and call-reference/index contract,
callback dedupe, call scheduling/readiness, live Jev or approved voice-gate design,
fallback/confirmation notifications and explicitly authorized real acceptance.
Phase 3 remains incomplete.

</details>


### Oct 24: GET-only Bolna readiness

Added BolnaClient.readiness and python -m svaar.voice.smoke. The command makes
only GET /user/me and GET /v2/agent/{id}, verifies the configured agent identity,
and prints readiness flags without balances, identities, prompts or credentials.
Live checks passed: wallet positive, concurrency available, agent processed and a
conversation task present. calls_placed=0 and turn_delivery_verified=false.
The current hosted configuration has no ask_svaar bridge or call_ref template.
No hosted configuration was changed. Authenticated turn/status endpoints,
stable retry binding and end-to-end call acceptance remain pending.

Verification: 35 Bolna adapter tests and the full 406-test PostgreSQL suite passed;
Ruff lint/format and alembic check passed. The initial full-suite attempt failed
because PostgreSQL was stopped; starting the existing db service resolved it.
No schema migration or Git mutation was performed.


### Oct 24: authenticated status receipts

Implemented POST /api/v1/voice/status using a separate 32-character minimum
header secret and the three documented Bolna peer IPs. Unknown executions or
mismatched agents are rejected. Payloads are bounded; duplicate JSON keys are
rejected. Migration 0011 stores only receipt metadata, unique execution/status,
and a payload hash. Call locking makes concurrent duplicates atomic with status
updates. Shared lifecycle handling rejects stale progress and cannot reopen a
terminal call. No transcript/extraction is retained and no claim is inferred.

The image disables proxy headers. An arbitrary tunnel cannot satisfy peer-IP
checks; reviewed trusted ingress and real callback delivery remain pending.
No hosted agent mutation, real callback, message or call was performed.
Failure notifications, transcript retention/classification and the authenticated
conversation bridge remain incomplete. This is transport receipt handling only.

Verification: full PostgreSQL suite 417 passed with the existing A-004 warning;
Ruff lint/format, Compose config, migration downgrade/upgrade/check on svaar_test,
and upgrade/check on local svaar passed. Both databases are at 0011.


### Oct 24: failed-call outbox wiring

Application composition injects agent.enqueue_call_failure into voice status
processing without cross-importing agent/voice implementations. A newly applied
no-answer/busy/failed/canceled/stopped/error receipt queues one generic private
follow-up using the existing verified-route and outbox ordinal locks. Duplicate
or stale terminal statuses cannot enqueue another. Completed and balance-low
receipts do not invoke this notifier. No claim, identity or evidence is changed.
An enqueue exception rolls back receipt, call status and outbox together; a false
result means no safe route, so the receipt commits without a notification.
No new schema, dependencies, provider mutations or live sends were needed.

Verification: full suite 430 passed; after adding the final HTTP composition
test, all 35 status/notification tests passed. Ruff lint/format and alembic check
passed. Existing A-004 warning remains. Live callback/outbox delivery, operator
balance alerts, conversation bridge and trusted ingress remain pending.


### Oct 24: internal call-reference boundary

Added ReferencedTurnRunner, which accepts a private placement reference, validates
bounded text and an explicit stable index, resolves only a stored reference hash
with execution/agent receipts, and delegates to the existing guarded TurnRunner.
No asserted phone, organization or principal is accepted. No provider HTTP route,
model-derived index, automatic activation or new schema was added.

Real PostgreSQL integration confirms duplicate reuse, conflicting retry rejection,
identical utterances at new indices and closed-call replay/new-turn restrictions.
Full suite: 451 passed; Ruff lint/format and alembic check passed. A-004 remains.

Bolna function/schema documentation establishes parameters and auth headers, but
does not establish a stable transport retry identifier. Provider delivery of the
private reference and index remains unverified (A-013/A-014). Public HTTPS ingress
and its trusted source-IP handling are still required. This internal boundary is
not a working Bolna bridge and does not complete Phase 3.


### Oct 24: restricted Cloudflare origin implementation

create_status_ingress exposes only POST /api/v1/voice/status, without docs,
health, operator, GitHub or turn routes. It reuses application lifecycle and
outbox composition but skips model initialization. Missing status secret fails
startup. The standard application remains on direct peer-IP checks.

The dedicated listener trusts the local Mac and cloudflared connector, requires
a 127.0.0.1 peer and one CF-Connecting-IP header from the documented Bolna allowlist,
plus the callback secret. Uvicorn must bind 127.0.0.1 with --no-proxy-headers.
Local processes holding the secret are trusted; arbitrary proxies/Workers are
outside this deployment. README contains explicit port 8001 startup instructions.
cloudflared is installed locally. No tunnel was started or hosted agent changed.

Twenty-five synthetic ingress tests passed, covering route isolation, missing
secret, nonlocal peers, malformed/duplicate/spoofed headers and normal-app
separation. Real Cloudflare header delivery and Bolna callbacks remain unverified.

Final verification: 476 tests passed against isolated PostgreSQL; Ruff lint/format
and alembic check passed. Existing A-004 warning remains. No schema change,
live provider request, public tunnel, message, call or Git mutation was made.


### Oct 24: live tunnel attempt and teammate handoff

User-provided evidence: a temporary Cloudflare URL was generated, the hosted
Bolna status webhook and custom secret header were configured, and Send test
returned HTTP 401 initially, then HTTP 422 after configuration changes.
The screenshot showed Svaar's unauthorized envelope for the initial response.
The subsequent 422 is consistent with passing authentication/source checks and
failing payload validation in the implemented handler; its response body and
payload were not inspected, so the exact cause is unverified.

This establishes a user-reported live ingress attempt, not accepted receipt
processing. No successful callback transaction, real call, phone verification,
conversation turn or live outbox delivery was established. No new tests were run
for this documentation-only update; the latest implementation check remains
476 tests passed.

The user asked to stop troubleshooting this wiring and handed it to a teammate
(name unspecified). Remaining handoff:
- Inspect a sanitized dashboard test payload/error to identify the 422 cause.
- Confirm callback execution/agent identity matches a stored Svaar call receipt;
  unknown sample executions deliberately return 404.
- Verify accepted receipt persistence and duplicate delivery behavior live.
- Finish the authenticated conversation bridge with verified private reference
  and stable retry identity, then perform an explicitly authorized end-to-end call.
- Maintain restricted ingress, separate secrets and all existing action gates.

The tunnel URL is temporary; verify it is current before further provider tests.
Secret values are intentionally omitted. Prior implementation-only statements
that no tunnel/hosted configuration had been changed describe agent actions at
that earlier point; this later user configuration supersedes current setup status.
Phase 3 and all unverified live acceptance items remain incomplete.


### Oct 26: main-branch integration and migration collision

Retained the phase-wise tracking layout and both branches' voice, incidents,
negotiation and replay implementations. Main's prior evidence reports 411 tests
for incidents and 436 for negotiation, plus one authorized outbound Bolna call
on Oct 24; these are teammate-recorded historical claims, not reverified live
here. The reported call used Bolna's model and does not establish the Svaar
conversation bridge. The later dashboard 422 and voice handoff remain unresolved.

Main adds repository/workflow/branch incident grouping, scoped timeline/actions,
acknowledgement, same-org ops/lead/admin outbox alerts (A-018), request-scoped
negotiation constraints (A-019), bounded validator-driven rounds and isolated
operator-supplied simulated replay. No log-tail fingerprint, owner rule, GitHub
App client, risky CI adapter or real voice bridge is established by this merge.
Original phase exit checks and incomplete live acceptance remain unchanged.

Migration collision: both branches called a different revision 0011. Main's
0011 -> 0012 -> 0013 chain is preserved; voice receipts now use 0011_voice from
0010. A merge revision 0014 joins 0013 and 0011_voice. A database whose existing
0011 is the old voice-only schema needs a schema-verified version correction
to 0011_voice before upgrade. Never blindly stamp or apply main's 0011 over it.


Merge verification, 2026-10-26: 526 PostgreSQL tests passed with no skips and the
existing A-004 warning. Ruff lint/format and the conflict-marker scan passed.
Test-only migration 0014 -> 0010 -> main-only 0013 -> combined 0014 passed;
both development and test databases have clean drift checks at 0014.
Voice-only database labels were corrected after schema verification (A-020).
No Git staging, commit, push or further pull was performed. The working files
are resolved; the index remains unmerged until the user stages the four files.
No live providers, calls, messages or public tunnel were used during resolution.


### Oct 26: authoritative main-plan reconciliation

User explicitly designated main's plan authoritative. Read-only comparison showed
plans/PLAN.md is identical in HEAD, MERGE_HEAD and the working tree. The divergent
documents were progress/checkpoint records, not a revised product plan. No
requirements file was changed or replaced.

Preserved main's incident aggregation, timeline/actions, private role-based
alerts, deterministic negotiation/validator and isolated replay. Offline items
now reflect the merged 526-test verification without claiming live acceptance.
The checklist retains individual implementation/offline/live sections so an
implemented subset is visible without weakening the original phase exit check.

Outstanding plan gaps remain explicit: GitHub App/log-tail fingerprinting, an
actual repository owner rule (A-018), standing constraints and agent wiring
(A-019), planned manual incident creation, validator-linked replay, claim/evidence
flow, Jev runtime acceptance and the real confirmed CI action. Voice wiring stays
with the teammate. The current transport-only status handler closes failed call
receipts instead of setting failed; full completed-transcript/evidence processing
and balance alerts are missing (A-021). These are incomplete requirements, not
implicit approvals to change the plan.

This reconciliation edited only checkpoints/anomaly documentation. The prior
526-test result remains the latest code verification; no further tests, migration,
provider action or Git mutation were performed for these documentation changes.


### Oct 26: standalone read-only GitHub App adapter

Implemented integrations/github_app.py and optional paired App settings.
for_repository resolves only a same-org repo mapping and that mapping's
installation. JWT lifetime is nine minutes including a 60-second backdated iat;
token caching stops five minutes before expiry. Token exchange scopes to one
repository and Actions/metadata read permissions. Repository and workflow-run
GETs verify returned identities. HTTP is bounded, redirects/proxy inheritance
and retries are disabled, and failures reveal no keys/tokens/provider payloads.
PyJWT[crypto] is the added dependency for RS256; uv.lock was updated.

No startup/gateway/tool composition or new Compose credential forwarding exists.
No real GitHub request, authentication, workflow mutation, call or message was
made. Logs/archive retrieval, normalized log-tail fingerprinting, explicit owner
mapping and end-to-end runtime integration remain pending. Webhook observations
are not rewritten or synthesized from these reads.

Verification: 545 tests passed without skips, including 19 adapter/settings tests;
Ruff lint/format passed. The existing A-004 warning remains. No schema change or
Git mutation was performed. The earlier paused merge still needs user staging
and its manual commit; this task did not finish that Git operation.


### Oct 26: bounded workflow logs and normalized signatures

GithubAppClient.workflow_log_signature verifies a completed failed run before
requesting its documented log archive redirect. Only HTTPS documented Actions
storage hosts are permitted. A separate client sends no App JWT, installation
token, API cookie or API headers to storage. There is one explicit hop, no
automatic redirects/retries, and an 8 MiB streamed download limit.

incidents/fingerprints.py reads only in memory, caps archive entries at 100 and
expanded bytes at 16 MiB, and rejects unsafe paths, links, encrypted/non-text
members, excessive compression and invalid/empty archives. It hashes the final
40 nonempty normalized lines per file (bounded to 64 KiB), removes timestamps,
ANSI formatting, paths and PIDs, and preserves ordinary numbers/error codes.
Only log-tail-v1 digest/file-count metadata returns. A pure helper scopes the
digest by organization, repository, workflow and branch.

Existing incident grouping and observed events are unchanged. These signatures
are not yet persisted or fetched by webhook/gateway jobs. Attempt-specific
provenance and runtime orchestration must be designed before regrouping existing
incidents. No failure category, claim verdict or production recovery is inferred.

Verification: 570 tests passed without skips, including 25 new synthetic archive/
download cases. Ruff lint/format and alembic check passed. No schema change, new
dependency, real GitHub request, call, message or Git mutation occurred. A-004
remains. The paused merge still requires manual staging and commit.


### Oct 26: attempt-bound durable log-signature enrichment

Added explicit integrations.log_enrichment.enrich_event and migration 0015 for
workflow_log_signatures. Signed observed failed runs and their accepted delivery
receipts must match org scope; incomplete/missing workflow scope is refused.
The App adapter verifies the attempt-specific run response against run, attempt,
commit, workflow and branch before requesting that attempt's log archive.
No latest-attempt shortcut is used for persisted provenance.

The network read is outside DB transactions. Mapping scope is rechecked under
lock before storing only digest/fingerprint/version/file-count and source IDs.
A unique attempt/algorithm key plus advisory lock serializes duplicates; changed
hashes return conflict rather than overwrite. PostgreSQL forbids record updates
and deletes. Failed/unavailable logs never fabricate provenance or modify events.

This is an explicit internal operation with fake adapters in tests. No automatic
job, public route, tool registration, live GitHub call or incident regrouping was
added. Runtime work claiming/retries, missing-log policy and log-based grouping
remain pending. Existing observed history and incident membership are unchanged.

Verification: 586 PostgreSQL tests passed without skips; Ruff lint/format and
whitespace checks passed. Migration 0015 round trip and drift checks passed
on svaar_test; local svaar upgrade/check passed. Both databases are at 0015.
No new dependency, live provider request, call, message or Git mutation was made.
The existing A-004 warning remains; the user still needs to complete the paused
Git merge manually.


### Oct 27: Jev removal and optional structured classifier

Removed decisions/jev.py, provider-specific tests and active Jev references from
types, docstrings, agent policy, configuration examples and the website footer.
DecisionSource.MODEL replaces the retired source for new answers; historical
audit rows are neither rewritten nor migrated. Core policy and mission gates
remain unchanged.

Implemented decisions/classifier.py with strict named JSON answers, independent
slot validation, finite confidence checks and conservative per-slot fallback.
The existing HttpChatModel supplies one bounded request without tools or retries.
Application/gateway composition enables it only when SVAAR_CLASSIFIER_ENABLED=true
and existing LLM configuration is complete; default false remains heuristic-only.
No extra provider key, dependency, schema change or startup network call is added.

The voice gate locally rejects unclear short/noisy speech before inference,
accepts six-digit code candidates for further checking, and groups usability/
intent into one classifier request. Returned labels never change call mission.
Inference shares the voice deadline; abandoned results cannot dispatch tools.
Tests retain invented-code rejection, exact code checks, phone-code history
redaction and durable duplicate behavior. Failure-path tests now use clear text;
new regressions verify unclear speech consumes no verification attempts.

Verification: 594 PostgreSQL tests passed without skips (retired provider tests
removed, classifier/regression coverage added). Ruff lint/format, frontend
production build, Compose config and alembic check passed; A-004 warning remains.
The database initially was stopped; starting the existing service resolved that
test setup error. Schema remains 0015. Real classifier responses/calibration and
the Bolna bridge are not verified. No live messages, calls, model/provider
requests, .env changes or Git mutations were made.


### Oct 27: explicit incident ownership and owner-only alerts

Migration 0016 adds nullable owner references on repo_mappings and incidents.
Mapping creation can take a same-org principal owner; operator-only
PUT /repo-mappings/{repository_id}/owner configures the future default.
A new incident snapshots the approved same-org owner. Invalid/missing ownership
never falls back to role broadcasts. Only the owner receives the durable private
alert if one verified route exists. Acknowledging an incident does not transfer it.

The explicit assign_unowned_incidents flag can assign only open unowned incidents,
queueing their deduplicated alert in the same transaction. Assigned/acknowledged/
resolved incidents are never transferred. Mapping updates do not reroute existing
incident owners. Missing route means no notification; no delivery is promised.
No phone call, escalation job or model-proposed owner selection is enabled.

Verification: 608 PostgreSQL tests passed without skips. Added scope, developer-
owner routing, no-broadcast, future snapshot, explicit backfill, concurrent dedupe,
rollback and downgrade protection coverage. Ruff lint/format/whitespace checks
passed. Test-only 0016 -> 0015 -> 0016 and drift checks passed; development upgrade/
check passed. Both databases are at 0016; A-004 warning remains.
Prior tests caught an extra webhook-dispatch argument and a missing test import;
both were fixed before the passing full run. No live provider requests, messages,
calls, .env edits, new dependencies or Git mutations were performed.
Next implementation: claims/evidence and guarded escalation, using this explicit
owner. Live owner setup and alert acceptance remain incomplete.


### Oct 27: scoped claim/evidence core

Migration 0017 introduces claims and append-only event-linked evidence. Claims
are scoped to an incident/org and authenticated author. Source correlation
deduplicates retries; conflicting content cannot rewrite a recorded assertion.
record_claim/check_claim/list_claims dispatch through actions; AgentLoop binds
statement text to the caller's original message. GET /incidents/{id}/claims is
operator-only and read-only. Added tool names are a scoped plan extension (A-023).

The workflow-success rule needs a narrow positive assertion plus exact run,
attempt, optional SHA and same-incident accepted signed observation. Named run
numbers cannot be substituted by the model. Missing, failed, foreign, mismatched
or ambiguous facts never create contradicting evidence. fix_merged cannot be
confirmed by successful CI and stays unverified without a merge/call evidence
source. Rules derive status only after evidence is persisted; the model cannot
set status, author, organization, stance or evidence IDs via tool arguments.

Dedicated automatic claim detection, merge-event ingestion, call-answer tools,
classification/retention and verification/escalation remain pending. Statuses
refresh through explicit check_claim, not a new automatic job. Existing incident
history and live providers are untouched. There is no claim-driven dialer yet.

Verification: 626 PostgreSQL tests passed without skips, including 18 new claim/
evidence cases. Ruff lint/format/whitespace passed. Test-only 0017 -> 0016 -> 0017
and schema checks passed; local development upgrade/check passed. Both databases
are at 0017. A-004 warning remains. No new dependency, model/provider call,
message, phone call, .env edit or Git mutation occurred. Phase 5 remains incomplete.

## 2026-10-27: guarded escalation preparation

Phase 5 implementation and offline checks progressed; phase completion remains open.
Migration 0018 adds escalation_jobs and incident-bound voice intents. The optional
gateway callback starts grace only from confirmed owner-alert delivery, checks an
open incident's explicit owner and exactly one verified phone, claims rows with
SKIP LOCKED and enforces per-recipient cooldown. One incident can have at most one
escalation intent. Missing delivery/phone defers; acknowledgement before preparation
cancels; independent savepoints contain failures. Bound voice incident tools cannot
select another incident.

Evidence: 639 tests passed, no skips; Ruff lint/format, Compose validation and
git diff --check passed. Test-only 0018 -> 0017 -> 0018 and schema checks passed;
development database upgraded to 0018 with no drift. Existing warning: A-004.
Relevant files: jobs/models.py, jobs/escalation.py, gateway.py, agent/worker.py,
agent/notifications.py, voice/calls.py, voice/models.py, voice/runtime.py,
incidents/tools.py, actions/registry.py, config.py, migration 0018 and escalation tests.

Integration status: preparation is local, opt-in and disabled by default. No
provider requests, calls, messages or Git mutations occurred. Default CallService
refuses these incident-bound intents without an injected authorization guard.
Live dispatch/readiness, final incident checks and delivery remain pending with
the teammate's voice wiring (A-024). This does not complete claim_check, automatic
claim detection, call-derived evidence or the phase's live acceptance criteria.

## 2026-10-28: non-voice investigation, resolution, replay and confirmed CI actions

Verified: 687 tests passed without skips; Ruff lint/format, Compose (ci/gateway),
git diff --check and both database drift checks passed. Test-only round trip:
0021 -> 0018 -> 0021. Development upgraded to 0021. The first migration-check
attempt met a stopped database; after restarting the existing container all
checks passed. The existing Starlette warning remains A-004.

- 0019: operator-owned standing constraints, coherent revisions, negotiation
  snapshot revision, immutable tracked drafts and accepted-plan replay linkage.
  start_negotiation, request_replay and approve_exception use the action gate.
- 0020: one leased CI job per signed observation. Provider reads use the existing
  adapter outside DB transactions. Matching hashes group failures; missing logs
  retry before explicit coarse fallback. No observed facts or existing links
  are rewritten. New read tools expose recorded CI facts, not live current state.
- 0021: default-disabled confirmed rerun/cancel; durable placing/accepted/rejected/
  unknown intent and exact-attempt business-key dedupe across fresh confirmations.
  Read-only tokens remain read-only; a separate writer requests Actions write.
  Owner outbox codes now include requested action/target review text.
- The combined non-voice rehearsal uses fake readers and a simulated confirmation,
  never live delivery, telephony, LLM inference or a GitHub mutation.

Relevant new modules: resolution/policy.py, drafts.py, tools.py; replay/tools.py;
jobs/ci.py and __main__.py; incidents/grouping.py; integrations/ci_tools.py,
github_actions.py, ci_actions.py and ci_action_tools.py. Existing composition,
models/routes, configuration, migrations and test cleanup were updated.
No new dependency or broker was added. The CI worker is a process in the same
application/image so slow downloads cannot block chat polling.

A-019's missing store is resolved for implementation. A-026/A-027 record current
CI integration limits. All live acceptance boxes stay open. Automatic claim
detection, merge evidence, CI category/adaptive escalation and labelled evaluation,
manual incident creation, workflow dispatch and final rehearsal remain pending.
Voice routes/runtime and the teammate's hosted Bolna wiring are untouched.
No private .env edit, live messages/calls/provider mutations or Git mutations occurred.


## 2026-10-31: claim_check calls, merge evidence and claim detection

Branch feat/phase5-claims-escalation, based on feat/caspian-chat-runtime (Oct 28).
Owner: not assigned in this document. Windows 11 development machine.

- Migration 0022 binds claim_check calls to one claim (at most one open check per
  claim), adds claim_answers and lets evidence cite an answer instead of an event.
  Migration 0023 adds an optional pull_number target to fix_merged claims.
- verify_claim (lead/admin, chat) rechecks evidence and prepares a pending intent for
  the claim author with exactly one verified phone; nothing is dialed. CallService
  refuses claim_check intents unless a composed guard confirms the claim is still
  unverified and the recipient is its author.
- record_claim_answer is offered only in a bound claim_check call; AgentLoop replaces
  model arguments with the caller's exact words. The call prompt quotes the claim as data.
- ClaimAnswerWorker (gateway, SVAAR_CLAIM_CHECK_JOBS_ENABLED, default false) waits for
  the call receipt. Completed calls get one audited claim_answer decision; only a
  model answer at or above the high threshold maps confirmed/denied to
  supports/contradicts. Failed/unanswered calls discard answers. Text is purged.
- pull_request webhooks closed with merged=true become append-only observations that
  never open incidents. merge-event-v1 supports a narrow positive merge statement only
  for the claim's pull request, in the incident's repository, merged at or after the
  incident opened.
- claim_detection runs only when the classifier is enabled and a status word appears;
  a confident detection adds a prompt hint to use record_claim.

Verification: 725 passed, 1 failed, 4 errors (728 tests); the failures are the
Windows-only cases in A-026, which do not occur on Linux CI/macOS. Ruff format/lint
passed. Test-only round trips 0022 -> 0021 -> 0022 and 0023 -> 0022 -> 0023 and
alembic check on both databases passed. No live provider requests, calls, messages
or classifier requests were made; all model, classifier and voice providers are fakes.


## 2026-10-31: escalation advice and dispatch-time guards

- Questions ci_failure_category and escalation_step are asked in one classifier request
  once the acknowledgement grace has elapsed, at most once per job (migration 0024,
  escalation_jobs.advised_at). Each answer has its own audit row and action_taken.
  A confident flaky category sends one quiet private note; a confident chat_nudge sends
  one reminder; either, or a confident wait, defers preparation by one grace period.
  Fallback, low-confidence and call_now keep the deterministic schedule. Advice never
  runs before the grace and cannot make a call sooner. The gateway passes decisions
  only when the classifier is enabled.
- CallService rechecks escalation intents against the open, unacknowledged incident and
  its owner, and claim_check intents against the unverified claim and its author. It
  refuses to dial when an optional readiness probe fails or raises, and caps placements
  per recipient at SVAAR_VOICE_DAILY_CALL_LIMIT (default 3) in any 24 hours, under a
  per-recipient advisory lock. Migration 0025 adds voice_calls.placed_at.
- create_call_service composes all of these guards. It is not yet invoked by any route,
  job or model tool.

Verification: 736 of 739 tests passed; the remainder are the Windows-only cases
in A-026. Ruff format/lint passed. Test-only round trip 0025 -> 0023 -> 0025 and alembic
check on both databases passed. No live provider requests, calls, messages or
classifier requests were made.


## 2026-10-31: Windows test failures fixed

- incidents/fingerprints.py now rejects backslash archive member names using
  ZipInfo.orig_filename. On Windows, zipfile rewrites backslashes to "/" when reading,
  so the previous check never fired there; Linux behaviour is unchanged.
- agent/loop.py treats a classifier turn-deadline expiry in the voice gate as a timed
  out turn. Timer waits can return a few milliseconds early on Windows, which turned
  the fixed unavailable fallback into a clarification request.
- Tests: short explicit IDs for parametrized cases whose generated IDs exceeded the
  Windows environment-variable limit, a raw-name helper for the backslash archive, and
  float tolerance on the 0.1 second budget assertion.
- Local only: the git-ignored .env now uses 127.0.0.1. On this Windows machine localhost
  resolved to IPv6 first and each new connection took 10 seconds, which broke a 5 second
  concurrency barrier in test_log_enrichment and slowed the suite.

Verification: 739 passed, 0 failed (full suite, 4 min 53 s); Ruff format/lint passed.


## 2026-10-31: Phase 5 plan-gap closure

A requirements review against PLAN.md sections 10 and 17 found three gaps, now closed:

- Section 10: a failed claim_check call (no-answer, busy, failed, canceled, stopped,
  error) now tells the requester. Migration 0026 adds voice_calls.requested_by;
  verify_claim records the requesting principal. The status receipt queues one private
  "claim stays unverified" notice to the requester, keyed per call and atomic with the
  receipt, in addition to the existing notice to the person called.
- Section 17, grouped decisions: a test proves a malformed CI category answer falls back
  and is audited as invalid while the valid escalation answer in the same request is
  kept and applied.
- Section 17, CI classification and escalation: every allowed label of both slots
  validates and invented labels do not.

Verification: 752 of 752 tests passed; Ruff format/lint passed; test-only round
trip 0026 -> 0025 -> 0026 and alembic check on both databases passed. No live provider
requests, calls or messages were made.


## 2026-10-31: operator manual incident creation (Phase 4)

POST /api/v1/incidents (operator token) opens an incident for a repository explicitly
mapped to the organization. The owner defaults to the mapping's owner and must belong
to the organization; no role or name is guessed. The incident uses the automatic
grouping fingerprint (organization, repository, workflow, branch), so a later CI
failure joins it, and an active duplicate returns 409 under the same advisory lock.
No observed event is fabricated; the timeline stays empty until CI facts arrive. The
owner alert is queued atomically through the existing outbox; missing routes queue
nothing. Verification: 758 of 758 tests passed; Ruff passed. No schema change.


## 2026-10-31: Bolna voice turn route and operator dispatch

Built on the user's instruction not to wait for the teammate. Contracts were read from
Bolna's docs first: a custom LLM gets OpenAI chat completions at
{base_url}/chat/completions with Bearer auth and must stream deltas ending in
data: [DONE]; user_data keys fill {{variable}} prompt placeholders. Prompt delivery to
the custom LLM, execution IDs in requests and retry behaviour are undocumented (A-028).

- voice/turns.py mounts only the configured route. llm_endpoint: /voice/llm/models and
  /voice/llm/chat/completions; the call reference is read from a svaar_call_ref marker
  in the system message, the turn index from the count of earlier caller messages, and
  the reply streams as a role chunk, a content chunk, a stop chunk and [DONE]. Missing
  or ambiguous references, an empty utterance or a non-user final message get the fixed
  refusal without running the agent. function: /voice/turn sequences arrivals.
- Bearer SVAAR_VOICE_TURN_TOKEN, constant time, separate from all other credentials.
- ReferencedTurnRunner activates a queued placed call on its first authenticated turn,
  so a late or rejected in-progress callback cannot strand a live call.
- The restricted Cloudflare listener also serves the configured turn route and starts
  the shared agent only when a turn mode is set; docs, health and operator routes stay
  absent there.
- python -m svaar.dispatch lists pending intents and places or refreshes one named call
  through create_call_service, after Bolna readiness. It never prints phone numbers.

Verification: 778 of 778 tests passed; Ruff passed. No Bolna configuration was
changed and no call, message or provider request was made. Live acceptance is pending.

## 2026-10-31: Deterministic approval-set serialization

CI on Linux failed test_resolution_tools intermittently: required_approvals was a
frozenset, serialized in per-process string-hash order, so a stored negotiation snapshot
could differ from its source constraints. The same order fed tier-2 confirmation hashes
for proposals carrying approvals. Approval sets now serialize sorted; a regression test
covers both models. Resolution tests passed under six PYTHONHASHSEED values.

Separately observed once in a full local run and passing on rerun:
test_ci_jobs::test_different_log_signatures_do_not_merge_failures. Suspected cause, not
yet confirmed: the test freezes its clock about one second ahead, then ingests a second
job, which a slow run can create after the frozen time. Test-only; not yet fixed.

Verification: 779 of 779 tests passed; Ruff passed.

## 2026-10-31: isolated private demo deployment, public acceptance pending

- Added compose.demo.yaml with a separate project/volume, fresh generated secrets,
  no published PostgreSQL port and a private operator API at 127.0.0.1:18000.
  Existing .env/development data are preserved. .env.demo is ignored, mode 0600,
  generated exclusively and never printed.
- Restricted ingress mounts provider routes/probes only and rejects non-loopback
  peers. The prepared named Cloudflare sidecar shares its network namespace.
  Existing status secret/IP checks and voice Bearer/HMAC gates remain unchanged.
  Named tunnel is necessary because Quick Tunnels lack SSE (A-029).
- Image built successfully; app/db/ingress started and are healthy. Migrations
  through 0026 and schema drift checks passed before/after an isolated restart.
  A temporary probe survived restart and was then removed. No development tables
  or volumes were modified.
- CI worker now has an atomic, bounded process-local heartbeat and --status.
  Empty-queue lifecycle/start/restart passed with synthetic App credentials in
  the disposable test environment, then that worker stopped. Live CI worker
  remains stopped because App credentials are missing.
- Full suite: 784 passed, no skips; Ruff and Compose validation passed. The suite
  includes non-voice rehearsal. Existing Starlette warning remains A-004.
- Groq native tools: host 3 requests / 0.3857 seconds median full-response;
  actual image 3 requests / 0.602 seconds. Caspian GET checks passed with zero
  sends. Bolna GET checks passed with zero calls, turn delivery unverified.
- Authenticated synthetic SSE refusal ended with [DONE] locally. No real placed
  call or Bolna-delivered turn is established by it.
- Gateway --check passed; live gateway is deliberately stopped until authorization
  to process/send through the bot. Tunnel/publication is not started. GitHub App,
  key and HMAC secret are absent. Hosted Bolna configuration is unchanged.
- Added docs/DEPLOYMENT.md, docs/DEMO_RUNBOOK.md and a workflow_dispatch-only toy
  CI fixture. Do not run/copy/dispatch it in an external repository without
  explicit controlled-repository approval. Updated stale README deployment text.
- Phase 8 deployment readiness progressed; no phase-complete/live acceptance
  boxes were inferred. No Git operations or external account mutations occurred.

## 2026-10-31: Render Free target replaces public Cloudflare setup

User instruction: exactly one Free Docker web service and one Free PostgreSQL,
zero paid infrastructure; preserve the private fallback. User signed into Render
and reports a Free database available in Singapore. render.yaml references that
existing database rather than creating another one, and explicitly selects Free
with manual deploys. No paid worker, disk, cron or pre-deploy task is defined.

Added serialized startup migrations, dynamic PORT binding, a dedicated Render
restricted factory/Host policy, and a port-aware container probe. Only the Render
factory trusts the documented edge-overwritten CF-Connecting-IP; status secret,
Bolna allowlist, turn Bearer auth and call-reference checks are retained.
Private loopback ingress and its running containers are preserved.

70 focused tests passed, including PostgreSQL call-reference cases. The first
DB rerun used a stale dynamic test-container port; refreshing only that private
test URL resolved connectivity. A separate Render image built and started against
disposable PostgreSQL. This is local platform simulation, not actual Render
API/database or voice delivery acceptance. The full 784-test suite was not repeated.

Caspian polling is deferred on the sleeping Free service. Private provisioning and
call dispatch require an explicit secure operating path; Free offers no shell.
Do not expose operator routes or bypass enrollment to manufacture a live demo.
Source publication, web-service creation/credential entry and approval remain the
current human boundary. Actual HTTPS URL and phone tests remain pending.
