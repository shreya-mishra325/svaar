# Svaar demo runbook

Current primary target: [Render Free](RENDER_DEPLOYMENT.md). The local Compose
configuration below is retained as a fallback. Cloudflare setup is superseded
for the public deployment; do not start its tunnel.

Current state: infrastructure and offline rehearsal verified on 2026-10-31.
This is a recording plan, not a record of successful live execution.
See DEPLOYMENT.md for startup, credentials, trust boundary and recovery.

## Preconditions before pressing record

- Approved named HTTPS hostname; remote SSE, 401/403 authentication and operator
  404 tests pass through the real tunnel.
- Gateway healthy and user authorized to send messages through the configured bot.
- Owner enrolled through a single-use invite in the explicit demo organization.
- Controlled repository installed/mapped to the organization and owner.
- GitHub HMAC/subscriptions and App log reads accepted against that repository.
- Bolna custom LLM selected with the correct demo turn token, prompt reference line
  and matching status secret. Do not show keys while recording.
- Owner verifies their own test phone via /verify_phone privately; each dispatch
  gets a separate explicit approval covering the prepared call and recipient.
- A real placed call has persisted authenticated turns and final status, with
  call_ref/history retry behavior verified. Do not assume the model-registration
  probe proves any of these.
- Trusted standing constraints configured for the scenario, with an actual
  validator-accepted negotiation available before replay.
- All migrations current; no unresolved placing/unknown actions being replayed.

## Controlled CI fixture

docs/fixtures/svaar-demo-workflow.yml is a workflow_dispatch-only toy workflow:
it deliberately fails when fail=true and succeeds otherwise. It has no deploy
credentials or external mutations.

Only after approval for the controlled repository should the user/team copy it
under that repository's .github/workflows, commit/push manually, and trigger one
named run. Agents do not push or dispatch it without target-specific approval.
Never point the failure fixture at a production deployment workflow.

## Exact live sequence, approximately three minutes

1. 0:00-0:20: show the approved repository's controlled failing workflow, then the
   owner alert in Telegram. Verify the delivery/observation/incident identifiers
   match before calling it live success. Redelivery must not repeat the alert.
2. 0:20-0:45: owner asks "What happened?" in private chat. Show the scoped timeline,
   provenance and occurrence order. Explain that a signature groups failures;
   it does not prove a root cause.
3. 0:45-1:20: if demonstrating escalation, obtain approval for the exact prepared
   escalation call, then dispatch once. Answer as the verified owner and request
   the timeline. Check a voice_turn row and completed status, not just queued.
4. 1:20-1:45: state a bounded work-status claim for the demo incident. Show evidence
   or unverified status honestly. A merged-fix claim needs an actual matching merge
   event; workflow success cannot substitute. A claim_check phone verification is
   an optional additional call requiring separate approval. Failed calls must leave
   claims unverified.
5. 1:45-2:15: present the hotfix proposal conflicting with freeze/staffing/capacity.
   Show rejected round and a revised validator-accepted plan from saved constraints.
6. 2:15-2:35: request replay of the correction with explicit scenario steps.
   Keep the SIMULATION label visible; no real pipeline runs during replay.
7. 2:35-3:00: request a tracked draft approval, or, only with separate CI write
   authorization and App permissions, request rerun of the exact toy run attempt.
   Show the nonce gate waiting. A real confirmation call needs its own approval.
   Verify the single durable action receipt; GitHub acceptance is not recovery.

A shorter live demo can use one approved voice call and a draft confirmation in
the permitted channel. Never enable same-channel confirmation just to hide an
unverified voice path or call a scripted response live.

## Evidence checklist after each step

- Chat: inbound processed, tool audit, outbox actually sent.
- GitHub: accepted signed delivery, recorded observation, incident membership,
  mapped owner alert. Unknown/unmapped payloads are not successful ingress.
- Voice: real call execution/agent match, correct recipient/mission, authenticated
  indexed turns, final callback and saved status. Queued alone is insufficient.
- Claims: evidence references and deterministic status; no invented contradiction.
- Resolution/replay: saved policy revision, validator rounds, simulated result.
- Risky action: confirmed owner/channel/nonce plus durable receipt and no repeated
  POST. Stop and review placing/unknown states instead of retrying.

## Safe fallback

Run the existing test_nonvoice_rehearsal plus CI/voice boundary tests against the
dedicated disposable test database. Label the recording OFFLINE / SIMULATED.
Use the real Groq inference probe as a separately labelled provider check if
available. Do not fabricate a Telegram delivery, phone conversation or GitHub run.

If a provider fails during recording, retain its truthful error and explain the
unverified stage. Continue only independent validated steps. No missing call,
failed workflow or unavailable provider can establish a contradiction or recovery.

## Current blocking approvals

First: named Cloudflare account/domain/connector configuration and authorization
to publish the restricted origin. Later: bot processing/sends, controlled GitHub
configuration/run, hosted Bolna configuration, and each exact live phone call.
Ask for one group at a time. No domain/plan purchase is authorized.
