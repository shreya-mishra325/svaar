# Svaar anomalies and open integration questions

Last reviewed: 2026-10-18 (Asia/Calcutta).

## How to use this log

Read alongside `rules.md`, `PLAN.md` and `checkpoints.md`. Record observed defects, intentional
limitations, unresolved contracts and design ambiguities separately. A planned
feature is not a bug, and a successful infrastructure probe is not proof of a
working integration.

For a new entry, use a stable ID and record status, category, evidence, impact,
next action and owner if assigned. Resolve entries with verification evidence;
do not silently delete them. Do not paste secrets or sensitive payloads.

## A-001: Gateway runtime is not implemented

- Status: Open; intentional scaffold limitation.
- Evidence: `src/svaar/gateway.py` exits with code 2 without `--check`.
  `compose.yaml` puts the service behind the `gateway` profile.
- Impact: No listener, outbox sender or polling jobs run. The successful diagnostic
  proves configuration/database access only, not chat availability.
- Next action: Implement the agent/jobs composition, transport shutdown and runtime
  health reporting before enabling the long-running service.
- Owner: Unassigned.

## A-002: External provider contracts remain unverified

- Status: Open; integration blockers, not implemented adapter defects.
- Evidence: PLAN.md sections 6, 9, 10 and 19 identify required smoke checks.
  No provider integration code or live-provider verification was added by scaffolding.
- Impact: Do not assume Caspian message IDs, sender trust, transport mode, delivery
  receipts or available channels. Do not assume Bolna's custom LLM endpoint,
  per-call reference delivery or latency units. Do not assume a common Jev payload,
  batching contract or partial-failure schema. The chat model's native tool behavior
  is also unverified.
- Next action: Record separately dated, redacted results for each provider and its
  selected mode/version before implementing its adapter. Use Telegram only through
  the same planned transport boundary if the Caspian decision gate selects it.
- Owner: Unassigned.

## A-003: Feature configuration names are not active settings

- Status: Open; intentional scaffold limitation.
- Evidence: `.env.example` comments and README's feature configuration section;
  `src/svaar/config.py` currently validates infrastructure settings only.
- Impact: Adding provider tokens to `.env` does not enable or validate integrations.
  Compose currently forwards infrastructure variables only. No operator, voice or
  webhook authentication is implemented.
- Next action: Introduce validation and process-specific credential wiring with
  each owning feature. Keep credentials server-side and without usable defaults.
- Owner: Unassigned.

## A-004: Upstream test-client deprecation warning

- Status: Open; non-blocking warning.
- Evidence: Last local run on 2026-10-18 passed 29 tests and emitted a
  `StarletteDeprecationWarning` about using httpx with Starlette's test client.
- Impact: Tests currently pass; future dependency updates may require test-client
  changes. This is not an observed production request failure.
- Next action: Review the supported upstream migration when updating dependencies;
  change the lockfile deliberately and rerun tests. Do not suppress the warning
  simply to claim a clean run.
- Owner: Unassigned.

## A-005: Planning document handling instructions conflict

- Status: Open; documentation/workflow conflict.
- Evidence: PLAN.md's introductory note and working rules discourage keeping or
  pushing planning documents. The user's explicit team instructions retain
  `plans/` for collaboration and now authorize these two context files.
- Impact: An agent following the plan alone might delete, move, ignore or commit
  documents against the team's current instructions.
- Current handling: Preserve `plans/` and existing plan contents. Do not change
  `.gitignore`, `.git/info/exclude` or Git configuration to hide these documents.
  Git operations and final submission cleanup belong to the team.
- Next action: Have the team reconcile the wording when it next edits PLAN.md.
- Owner: Team decision; no individual assigned.

## A-006: Confirmation atomicity does not guarantee external exactly-once effects

- Status: Open; design question for implementation, not an observed code defect.
- Evidence: PLAN.md section 7 describes a conditional confirmation update and a
  unique execution key. README also notes external side effects are not atomic
  with database commits. No confirmation executor exists yet.
- Impact: A crash after a provider accepts an action but before its receipt is
  persisted can leave the outcome unknown. Row locks or a unique local record alone
  cannot prove the provider executed exactly once.
- Next action: Define execution/unknown-outcome states, provider idempotency where
  supported, and reconciliation or human review. Never retry a risky action blindly.
  Test concurrency and crash boundaries with the executor implementation.
- Owner: Unassigned.

## Resolved entries

None recorded yet. When resolving an entry, retain its ID, add the resolution date,
relevant files and the specific check or external evidence establishing resolution.
