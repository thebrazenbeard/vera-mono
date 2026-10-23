# Goal 1 causal-trial protocol — evaluator interface contract

**Event:** `GOAL1-LIVE-20261023-02`  
**Status:** local synthetic protocol prototype; NOT a QVR integration or learning result.

## Candidate/controller interface

The current local Python prototype is `research/goal1_evaluator/causal_trial.py`. Vera's adapter should implement the following semantics, preferably through a versioned authenticated controller interface rather than importing the evaluator's private state.

1. `issue(phase)` returns only `{challenge_id, features}`. It must not return labels, split metadata beyond the requested phase, the answer key, randomization seed, or private test fixture. IDs, scoring method, budget and stopping rule are frozen before any prediction.
2. `commit_prediction(arm, challenge_id, prediction, prompt_digest, budget_units)` is called before any feedback. The controller assigns sequence/order and stores a durable receipt. Client-supplied order, time, budget, candidate identity, or outcome is not authoritative. One attempt per arm/case; exact public prompt digest; exact budget match.
3. `release_feedback(arm, challenge_id)` is allowed only for a training case with a committed prediction and is one-use. LEARNED receives the true training label; FROZEN receives no feedback; PLACEBO receives fixed non-informative feedback; SHUFFLED receives labels permuted across training cases. No arm receives held-out labels.
4. `score()` rejects incomplete held-out batches and scores all four arms on the same frozen held-out case set. The controller returns aggregate exact-match accuracy and budget usage only after every holdout prediction has been committed.
5. A stored correction or changed prompt is context state, not an outcome. It is not scored as learning. A learning claim requires matched arms, observed held-out behavioral difference, causal controls, and later cold-restart/transfer evidence.

## Frozen synthetic fixture

- 4 training and 4 held-out cases per arm.
- Arms: LEARNED, FROZEN, PLACEBO, SHUFFLED.
- One budget unit per prediction; one attempt per arm/case.
- Stopping rule: score only when all 4 holdout predictions exist for every arm.
- Scoring: exact-match accuracy over all 4 held-out labels; no partial score.
- Test suite ID is public; private labels are held in controller instance state. This is synthetic test data, not a hidden production benchmark.

## Explicit limitations

The current prototype is same-process Python state, not a security boundary. The Python object, memory and host can be inspected or altered by same-privilege code. Its sequence is controller-assigned but not externally attested; the fixture's private labels are not protected against a hostile same-user process. The four-arm tests verify protocol invariants and reject common misuse, but do not invoke a model, implement parameter updates, prove the model consumed any prompt, or establish feedback-caused improvement. A corrected prompt alone must never be counted as a learning success.

## Required production-facing evidence before qualification

Vera's QVR adapter must emit, per attempt, a controller-issued run/arm/case binding, exact candidate and adapter build digests, verified model artifact identity and loaded artifact digest, prompt digest, exact output/prediction, controller sequence, measured resource usage, and durable pre-feedback receipt. Timeout after possible dispatch must become OUTCOME_UNKNOWN with no automatic retry. The evaluator must control inference dispatch or independently attest it. After feedback, require randomized matched arms, committed pre-feedback predictions, held-out truth custody, a real process restart with exact artifact digest loaded, unfamiliar transfer cases, rule reversal, and negative-transfer veto. Same-host SQLite hash chains and caller-supplied metadata are insufficient independent custody.
