# Independent evaluator custody contract — Goal 1

**Status: design contract only.** This document specifies the minimum boundary for a future independent qualification service. It does not claim that the local SQLite prototype, GitHub CI, the current Remote Desktop Commander host, or a caller-supplied QVR journal is independently trusted.

## Trust boundary

The evaluator must be operated under separate administration from the candidate runtime: separate host or demonstrably isolated security principal, separate credentials, separate truth storage, separate audit retention, and an access policy the candidate process cannot modify. A different process, repository branch, account label, OS, code signature, or hash is not by itself proof of trust separation.

Prefer an evaluator-controlled inference worker when the experiment requires evidence that a specific model invocation occurred. If a candidate-controlled host supplies output text, prompt/response digests and PID/model metadata remain claims unless independently attested. The evaluator must not accept a caller-supplied journal row as proof that an invocation happened or happened before feedback.

## Minimum protocol

The interface is authenticated, versioned, bounded JSON over TLS or a local authenticated IPC channel. Reject unknown fields, duplicate JSON keys, non-finite numbers, oversized bodies, stale nonces, and invalid state transitions. The candidate has no read/write access to evaluator truth, signing keys, controller database, or audit journal.

1. **Create run (evaluator operator only).** Bind the exact candidate source/build digest, runtime adapter/build digest, task-suite version, model identity and its verification level, arm ID, budget limits, randomization seed commitment, and scoring/negative-transfer thresholds. Keep the seed and answer key private until the run is closed.
2. **Issue challenge.** The controller chooses the next case and returns only an opaque challenge ID, nonce, feature-only public case, allowed prediction schema, expiry, and server-issued budget allowance. The candidate cannot choose its split, replace its case ID, or request evaluator metadata.
3. **Reserve inference attempt before any model call.** Persist a unique attempt ID, run/challenge/arm binding, candidate and adapter build digests, route, prompt digest, budget reservation, controller sequence, and trusted timestamp in an atomic transaction. The only permitted inference path must enforce the reservation. An untrusted client that can bypass the gateway cannot be said to have exactly-once invocation evidence.
4. **Commit prediction before outcome.** The evaluator records the exact prediction distribution, selected action/abstention, response digest, prompt digest, attempt ID, candidate build digest, server-assigned sequence/time, and independently measured resource usage. The evaluator returns a signed, durable receipt. The candidate cannot supply its own sequence, time, budget, candidate identity, or receipt signature.
5. **Resolve inference result.** Successful responses transition the reserved attempt to COMPLETED. A timeout, disconnect, or crash after dispatch transitions it to OUTCOME_UNKNOWN, never to “no attempt.” Do not retry or reuse that attempt ID automatically; reconciliation is explicit and separately recorded.
6. **Release training feedback.** Only after a valid prediction receipt is committed, the controller may reveal that training case's label once. The challenge state and release are atomically consumed. Replays, rotated candidate IDs, or process restarts cannot obtain another release.
7. **Score held-out batch.** The controller withholds held-out labels and per-case correctness until every arm has committed every prediction. It then returns aggregate accuracy, calibration/Brier score, coverage/selective accuracy, task-family breakdown, budget consumption, and negative-transfer deltas. No single held-out response reveals a label that can inform later predictions in the same batch.
8. **Close and attest run.** Preserve the ordered event log, run/config digest, challenge-set commitment, per-arm prediction receipts, aggregate results, all failed/unknown attempts, and operator identity. Publish a redacted manifest without truth labels or private keys; an independent reviewer verifies the signed receipts and audit continuity.

## Durable state machine

- Challenge: NEW → ISSUED → PREDICTION_COMMITTED → (TRAINING_FEEDBACK_RELEASED | HELDOUT_BATCH_SCORED).
- Inference attempt: RESERVED → COMPLETED, or RESERVED → OUTCOME_UNKNOWN. Unknown is a terminal state until a separately recorded reconciliation; it is not silently reset.
- A state transition and its append-only audit event must share one transaction with uniqueness constraints. The controller checks chain continuity and row digests on every reopen. An unkeyed hash chain detects accidental edits but is not tamper-proof against an administrator who can rewrite both data and hashes; signatures/keys must be held outside the candidate's authority and checkpoints witnessed externally.

## Controlled learning comparison

Use separate, state-isolated candidate processes for at least these arms: adaptive update, frozen policy, placebo feedback, shuffled feedback, and exact-example memorizer. Keep task cases, model/build snapshot, available training feedback, prediction slots, inference/tool-call limits, and measured resource budget matched. Randomize arm order and avoid shared mutable memory between arms.

- Training cases must permit an explicit, reproducible update rule; the evaluator controls labels and reveals them only after prediction commit.
- Qualification cases must use unseen feature combinations/task families, not only new IDs for familiar examples.
- Include rule reversal and an out-of-distribution family to measure negative transfer. Report errors/regressions as well as wins. Pre-register a veto threshold: if the adaptive revision causes material harm versus the frozen baseline on protected families or reversals, do not promote it.
- Confidence is scored against outcomes (for example, Brier score and calibration bins), not accepted as a self-reported qualitative claim. Abstention is scored with coverage and selective accuracy so an always-abstaining arm cannot claim success.
- Budget must be metered by the trusted worker/gateway (tokens, calls, elapsed time, and relevant compute), not supplied by the candidate. Prediction-slot equality alone is a partial control, not total compute equality.

## Cold-restart qualification

After training and revision, stop the candidate process completely. Start a distinct process from the exact recorded build, reopen the exact revision artifact by digest, and capture evidence that the runtime actually selected and consumed that revision. Submit fresh, previously unseen cases and rule reversals through the independent controller. Compare behavior with frozen/placebo/shuffled/memorizer controls. A journal reopening, persisted hash, saved memory record, or identical metadata is not evidence that learned behavior survived restart.

## Current implementation gap

The local prototype in `custodian.py` demonstrates feature-only challenge responses, commit-before-feedback ordering, durable one-use state, aggregate held-out scoring, and process-reopen checks. It is on the same Windows host as the learner and its SQLite truth is readable by a same-privilege process; its hash chain is unkeyed. It does not invoke QVR, meter actual model tokens/compute, attest model bytes, protect against a malicious host administrator, or prove any learning. A real service needs a separately administered custody host and an adapter that reserves each inference attempt before dispatch.
