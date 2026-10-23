# Goal 1 causal-trial protocol — evaluator interface contract

**Event:** `GOAL1-LIVE-20261023-02`  
**Status:** local synthetic protocol prototype; NOT a QVR integration or learning result.

## Candidate/controller interface

The current local Python prototype is `research/goal1_evaluator/causal_trial.py`. Vera's adapter should implement the following semantics, preferably through a versioned authenticated controller interface rather than importing the evaluator's private state.

1. `issue(phase)` returns only `{challenge_id, features}`. It must not return labels, split metadata beyond the requested phase, the answer key, randomization seed, or private test fixture. IDs, scoring method, budget and stopping rule are frozen before any prediction.
2. `commit_prediction(arm, challenge_id, prediction, challenge_view_digest, model_prompt_sha256, model_response_sha256, budget_units)` is called before any feedback. The controller recomputes `challenge_view_digest` from the exact public challenge it issued and rejects a mismatch. `model_prompt_sha256` and `model_response_sha256` are distinct lowercase SHA-256 digests supplied by the adapter for the actual prompt bytes submitted and response bytes returned; they are bound into the receipt but are **not independent proof** of dispatch or execution. The controller assigns sequence/order and stores a receipt containing arm, challenge ID, prediction, all three digests, sequence and budget fields. Client-supplied order is rejected. One attempt per arm/case.
3. `commit_prediction` now requires a `dispatch_evidence` envelope and an injected `dispatch_evidence_verifier`. The envelope must include `witness_kind=independent_dispatch_gateway`, unique `attestation_id` and `invocation_id`, `run_id`, arm/challenge binding, the public challenge digest, exact prompt/response digests, `model_identity`, `model_artifact_sha256`, monotonic dispatch/response timestamps, and `outcome_status=COMPLETED`. The verifier must authenticate an attestation issued by a dispatch gateway/observer controlled outside the learner process and OS privilege boundary. Same-host self-authored journal rows, caller timestamps, PIDs, and hashes are not independent evidence. Replays, mismatched challenge/hash/model identity, non-increasing timestamps, invalid artifact identity, and `OUTCOME_UNKNOWN` fail closed. An unknown outcome is not completed and must not be automatically retried.

4. `release_feedback(arm, challenge_id)` is allowed only for a training case with a committed prediction and is one-use. LEARNED receives the true training label; FROZEN receives no feedback; PLACEBO receives fixed non-informative feedback; SHUFFLED receives labels permuted across training cases. No arm receives held-out labels.
4. `score()` rejects incomplete held-out batches and scores all four arms on the same frozen held-out case set. The controller returns aggregate exact-match accuracy and protocol budget counters only after every holdout prediction has been committed.
5. `budget_units=1` is a **nominal protocol counter**, not measured model tokens, latency, GPU/CPU time, invocation count or total resource usage. Receipts explicitly mark `budget_kind=protocol_counter_not_measured_usage` and `resource_usage_measured=false`.
6. A stored correction or changed prompt is context state, not an outcome. It is not scored as learning. A learning claim requires matched arms, observed held-out behavioral difference, causal controls, and later cold-restart/transfer evidence.

## Frozen synthetic fixture

- 4 training and 4 held-out cases per arm.
- Arms: LEARNED, FROZEN, PLACEBO, SHUFFLED.
- One nominal protocol budget unit per prediction; one attempt per arm/case.
- Stopping rule: score only when all 4 holdout predictions exist for every arm.
- Scoring: exact-match accuracy over all 4 held-out labels; no partial score.
- Test suite ID is public; private labels are held in controller instance state. This is synthetic test data, not a hidden production benchmark.

## Explicit limitations

The current prototype is same-process Python state, not a security boundary. The Python object, memory and host can be inspected or altered by same-privilege code. Its sequence is controller-assigned but not externally attested; the fixture's private labels are not protected against a hostile same-user process. Prompt/response hashes are caller-reported metadata and do not independently prove what the model consumed or returned. The four-arm tests verify protocol invariants and reject common misuse, but do not invoke a model, implement parameter updates, prove the model consumed any prompt, or establish feedback-caused improvement. A corrected prompt alone must never be counted as a learning success.

## Required production-facing evidence before qualification

Vera's QVR adapter must obtain prompt and response bytes directly at the model transport boundary and supply their exact hashes, alongside a controller-issued run/arm/case binding, exact candidate and adapter build digests, verified model artifact identity and loaded artifact digest, exact output/prediction, controller sequence, independently measured resource usage, and durable pre-feedback receipt. Hashes provided by an untrusted caller are not independent dispatch evidence. Timeout after possible dispatch must become OUTCOME_UNKNOWN with no automatic retry. The evaluator must control inference dispatch or independently attest it. After feedback, require randomized matched arms, committed pre-feedback predictions, held-out truth custody, a real process restart with exact artifact digest loaded, unfamiliar transfer cases, rule reversal, and negative-transfer veto. Same-host SQLite hash chains and caller-supplied metadata are insufficient independent custody.

## Dispatch evidence trust boundary and explicit limits

The controller now accepts only an Ed25519DispatchEvidenceVerifier instance; generic boolean verifier injection is rejected at construction. The verifier validates a gateway signature against a deployment-pinned public key and requires a durable pre-dispatch reservation binding run, arm, challenge, challenge-view digest, exact prompt digest, and pinned model identity/artifact digest. The signed envelope additionally binds response digest, outcome, monotonic dispatch/response timestamps, unique attestation/invocation/reservation IDs, gateway identity, and measured token/wall-time usage. SQLite uniqueness and transactional consumption reject duplicate reservation and replay after verifier reopen. A signed OUTCOME_UNKNOWN closes the reservation and automatic retry is rejected.

This is only a source-level capability: unit tests generate ephemeral keys in-process. No production gateway, private key, or deployment-pinned public key exists in this branch, and a same-privilege process can rewrite the local SQLite DB or replace trust configuration. See DISPATCH_ATTESTATION_CONTRACT.md. Until Integration supplies a genuinely separate gateway/observer and trusted deployment configuration, real model dispatch remains unqualified; this is not a completed independent dispatch implementation.

The four-arm fixtures and their labels are synthetic and visible in source to repository readers. The controller's learner-facing `issue()` response omits truth, but this public fixture is not secret answer-key custody. A qualified run needs evaluator-held private labels outside learner-readable source/state. The test-only scores and `budget_units=1` remain protocol outputs, never measured usage or learning qualification.
