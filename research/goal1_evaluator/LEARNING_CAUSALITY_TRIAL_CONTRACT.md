# Goal 1 learning qualification — primary result triage and next experiment

**Purpose:** independently evaluate the reported isolated QVR result without upgrading prompt conditioning or replay persistence into learning evidence.

## Current primary evidence supplied for triage

Source head reported by the primary worker: PR #86 `5f3c63a0a148ed0048720aac7277ebc26a702508`.

The research-only adapter `research/goal1_learning_trial/revision_context.py` assembles a prompt for either `FROZEN` or `REVISED`. The revised condition requires a completed correction-ledger state, review-gate admission, and one-use cue consumption. It then inserts `revision.rule_text` into the prompt. The receipt explicitly defaults `model_consumption_verified=False`, `learning_improvement_verified=False`, and `independent_truth_verified=False`. Its module docstring explicitly calls this prompt-context conditioning, not parameter learning.

Reported isolated QVR outcome:
- Frozen control: `B`
- Revised-context condition: `B`
- Both calls completed.

This is **no observed improvement on this trial**. It is not evidence that the revised rule changed model behavior. Because sample size is one paired case and the reported task/prompt details and raw receipts are not included in this independent checkout, it does not establish equivalence or a general null effect. The honest conclusion is narrow: the reported observation fails to demonstrate a feedback-caused behavioral improvement.

Reported separate-process reopen:
- The old cue was rejected on replay.
- A new cue was admitted.

This supports durable gate/replay behavior only if the process and database provenance is independently verified. It does not show that the model consumed the revised prompt, learned a change, retained a change, or used it after restart.

## Causal claim ladder

Keep these claims separate:

1. **Correction record exists:** ledger stages and refs are persisted.
2. **Influence gate admits a version:** exact revision reviewed; cue spent once.
3. **Prompt differs:** revision bytes appear in the revised prompt, frozen prompt excludes them.
4. **Selected QVR consumed prompt:** requires transport-side receipt binding prompt digest, route, actual model/build identity, response digest, and invocation attempt.
5. **Behavior changed:** paired, predeclared held-out predictions differ in a beneficial way.
6. **Feedback caused change:** randomized/matched condition assignment and frozen/placebo/shuffled-feedback/memorizer controls rule out prompt wording, example memorization, leakage, and extra budget.
7. **Learning persisted:** after real process restart, exact learned artifact is loaded and its digest is verified by the consuming runtime.
8. **Transfer qualified:** new held-out cases improve, reversal follows new evidence, and negative transfer stays below a predeclared veto threshold.

Evidence at a lower rung must not be described as proving a higher rung.

## Next experiment contract

Before dispatch, an independent custodian freezes the task generator, held-out labels, assignment seed, scoring code, budget definition, and stopping rules. The learner receives cases without labels. Truth remains inaccessible until a controller records the pre-outcome prediction commitment.

Use randomized, matched arms:
- **LEARNED:** feedback-derived rule/context after the qualified update.
- **FROZEN:** identical initial state with no update.
- **PLACEBO:** same token/compute budget, but a neutral or irrelevant correction.
- **SHUFFLED:** same feedback count and budget with labels permuted across cases.
- **MEMORIZER:** exact training examples retained, no rule abstraction, to expose example leakage.
- **ADAPTIVE vs fixed-budget** only as a separate comparison; do not let one arm receive more calls/tokens/time.

Evaluate on untouched, unfamiliar held-out cases; include a rule reversal after new evidence. Score primary accuracy and calibration, plus a predeclared negative-transfer veto. The same cases and scoring must be used across arms. Do not select a stopping point after seeing results.

Record each actual transport dispatch with durable reservation before send; ambiguous timeout becomes `OUTCOME_UNKNOWN` and must not be retried under the same attempt. Capture independently witnessed prompt/response digests, measured token/call/time budget, model/build and artifact identity, pre/post revision digests, and feedback release order. After update, terminate the process, start a new process, verify the exact artifact digest actually loaded, then run new held-out tasks not present in calibration or qualification.

A single changed answer is not enough. Qualification requires a predeclared effect size and uncertainty interval across enough held-out cases, no label leakage, no budget imbalance, successful reversal, no negative-transfer veto, and evidence that the post-restart runtime consumed the artifact.

## Current blockers

- No independently administered truth custody has been demonstrated in this branch.
- SQLite gate persistence and hashes are not independent host attestation.
- The adapter creates prompt context; it does not itself update model weights or establish the selected QVR consumed the exact prompt.
- The one reported paired result is `B` vs `B`, so improvement is unobserved.
- The supplied summary does not include exact prompt/response receipts, per-call model/build identity, actual budget telemetry, assignment seed, held-out truth commitment, or a verified loaded-artifact digest after restart.

**Disposition:** HOLD / NOT QUALIFIED. Keep this result as a negative/insufficient observation. Do not call it a learning success.