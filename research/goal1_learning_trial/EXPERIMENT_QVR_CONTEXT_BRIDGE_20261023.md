# Goal 1 — isolated QVR challenge/revision consumption cut (2026-10-23)

**Disposition: RESEARCH-ONLY, NOT QUALIFIED AS FEEDBACK-CAUSED LEARNING.**

## Source / host binding

- Vera-owned Draft/HOLD PR #86 source commit `6876326d85108aa531f974738473601c23a9c68b`.
- New `research/goal1_learning_trial/challenge_binding.py` source Git blob `962aae6a237f5c99e11ec7a474ba1b1bca92c9af` and tests `tests/research/test_goal1_challenge_binding.py` Git blob `574551221c58cfac8eb253eb2560245ac0ea35ce`.
- Selected **isolated** Lappy `QualifiedVeraRuntime` installed Python source Git blob `ba5a5a3d0ed601341617d1dae9d9c492baded5aa`, originating from Integration-owned Draft #82; production `VeraMonoPilot` NOT installed/selected by this trial.
- Loopback Ollama `qwen3:4b-instruct`; reported registry digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0` is **not** independently witnessed loaded model weights.
- Physical VN2 Python3.12 isolated blob-verified source+test `unittest`: **19/19 passed**. Physical Lappy Windows Python3.12 source+test: bridge **10/10 passed**. The strict output instruction's new test was observed RED (1 fail out of 10) before modifying `format_case_task`, then GREEN afterward. GitHub monorepo CI must be checked on this exact head before full-CI claims.

## Public challenge versus model prompt

The bridge deterministically renders exactly `{challenge_id, features}` into a bounded task and preserves separate hashes:
- `challenge_view_digest`: SHA256 of canonical public challenge JSON, compatible with Malaphor's synthetic controller `digest(challenge.learner_view())`.
- `model_prompt_sha256`: SHA256 of the **actual assembled prompt**, including optional gated revision context. These two digests MUST NOT be conflated.
- `model_response_sha256`: SHA256 of raw QVR text; model must return exactly `A`, `B`, or `ABSTAIN`, with whitespace allowed only around the literal token.
- Source validates caller-supplied QVR journal entry shape, prompt/response hashes, invocation ID, model, route, journal entry digest and expected case. This is **source integrity only**. Caller could fabricate a consistent history row, unkeyed hashes and timing. No authenticated evaluator custody or independent dispatch evidence exists here.

Two initial real Lappy trials completed QVR inference and each created one journal entry, but the model emitted explanatory prose rather than an exact label. Bridge correctly returned `QVR_COMPLETED_BINDING_REJECTED`. The first diagnostic mistakenly called its binder exception `OUTCOME_UNKNOWN`; **correction:** completed QVR inference is not an ambiguous dispatch. No same-attempt inference retries occurred. Adding an explicit 'Return ONLY the literal token' output contract then produced exact single-label outputs.

## Observed frozen and synthetic revised conditions

| Evidence | Case | Model output | Actual prompt SHA256 | QVR journal entry digest |
| --- | --- | --- | --- | --- |
| FROZEN, no revision | `synthetic-bridge-03`, `bits:011` | `A` | `ab5c81f134d350c9d81a516a246407b7defbc19ec7915419785441fd1504d6a6` | `baacb92390c34e32e9d1fe4b80c96f4044f2af3356c8048d596b18c79c425839` |
| REVISED, same public case | `synthetic-bridge-03`, `bits:011` | `B` | `08096be3850e2bf5518a28aeec2f090387f85895096ef02e6f9a32d33322d721` | `07e3ae89ec23cc947380501e05a3a3570856c71e6213aedbb92cca2a0f9ef6a7` |
| REVISED, **new process and new case** | `synthetic-bridge-04`, `bits:110` | `B` | `c1b88e2d70c32d6d63a4a2113beee12ad572425a4516feca536cb6dcf928080c` | `c52cc193534d69d71aee1868cc42b78f9e584873420865fae9137ed30113d047` |

The synthetic revision was locally self-authored and self-reviewed:
`For bits with two 1 digits, predict B; otherwise predict A.`
Its content-derived revision ID is
`e04a69b2b468c91e07afecec7861f396100ae1bac6ec77aa333f5cd8a79d90c3`.

The revised-context experiment received **no independently withheld true labels**. It is easy to make a language model change its response by supplying an answer-like rule. **A → B is prompt conditioning, not learned improvement.** The frozen and revised prompts have unequal content/token budgets, so this is not a matched causal benchmark.

The first revised process created local SQLite correction + influence gate state. A **distinct process** reopened both, rejected the prior cue as replay, generated a new cue on a different synthetic case, and observed another QVR prediction bound to the same revision ID. The rule text was **reconstructed by test code**, not autonomously recovered from a model-owned learned artifact. This demonstrates state/cue persistence plus real model prompt consumption, **not** independently qualified learned skill surviving restart.

## Unmet acceptance gates

1. Integration-owned QVR #82 must durably reserve inference *before dispatch* and represent timed-out possibly delivered calls as `OUTCOME_UNKNOWN`, with no automatic retry. Current QVR journal only records success and can leave unrecorded ambiguous attempts.
2. Malaphor-owned independent evaluator #87 must keep hidden truth and authentically witness prediction-before-feedback. Its current synthetic `commit_prediction(prompt_digest)` compares against the public-view digest rather than actual prompt bytes; this cross-interface defect is documented on Issue #85 and must be fixed on #87.
3. Matched randomized LEARNED/FROZEN/PLACEBO/SHUFFLED/MEMORIZER arms with actual measured inference and tool budgets, unfamiliar held-outs, label reversal, negative transfer veto, and actual artifact consumption across a true cold restart.
4. Separate custody/attestation and model artifact identity; source digests, process IDs, self-authored calibration or separate process are insufficient.

**No protected effects:** no merge/direct main mutation, service installation/deployment, provider/trust/credential change, canonical memory write, or unsafe VS Code workspace/payload execution. Local source/test and isolated user-owned model research only.

> **HOSTILE REVIEW — ACCEPTED:** A synthetic rule selected by the primary and written verbatim into a revised prompt predicts the requested output. Different model answers and cross-process use of that same string establish prompt response sensitivity and persistence of gate state, not model-self-learning. Do not upgrade the claim until independently controlled feedback is causally linked to later measured held-out behavior under matched controls.
