# GOAL 1 — public synthetic holdout leakage: negative learning control

Date (host-local): 2026-10-24. Status: **QUALIFICATION HOLD**.

## Evidence identity

- Malaphor PR #87 exact frozen source commit `b9fcd93b4d9a7668369aa71e507ac7bfe4598ff6`.
- Public causal-trial source: `research/goal1_evaluator/causal_trial.py` local file SHA-256 `61c1e65422c26a0add48b7055dde37a2dbdbe37feb001be03ed9f41c2cbacedf`, retrieved from immutable GitHub commit.
- Vera-owned Draft PR #89 adds `research/goal1_acceptance_bridge/holdout_leak_probe.py` and `tests/research/test_goal1_holdout_leak_probe.py`.
- Main `64c4a756a8c4d6fc791787de80303f7ee0f64869`; owner #90 remains `5758bdd07f3ef0020f8e7318f8b277ab7da6c72c` and #87 remains frozen at the head above. No owner branches were changed.

## Actual negative control

An AST-only read of the exact published PR #87 `causal_trial.py` reveals the module-level `HOLDOUT` literal tuple with **four public input→answer pairs**. An oracle that merely reads that published source can reproduce the four published labels and hence score **4/4 on those same four items without any inference, feedback or learning**.

This is source-leakage analysis, **not** an actual model inference, evaluator-scored new trial, causal effect, or evidence any model actually consumed the GitHub source. The result is nevertheless a decisive *lack of independent secrecy* for these exact source-embedded fixture answers.

The fixture remains useful for verifying control-flow mechanics, field binding, scoring code and replay behavior; it is **not fit for an adversarial unseen-heldout learning qualification**. A new qualified experiment needs a fresh separately generated and custodian-held unseen item/label pool, never published into candidate-readable repo source or evaluator-debug output, and a documented challenge issuance/access/feedback separation.

## Fail-closed scanner

New `holdout_leak_probe.py` uses Python AST parsing and literal-evaluates a small set of module-level public holdout declarations only; it does not evaluate dynamic Python or print source labels. The actual source report:

- `public_inline_holdout_labels=4`
- `public_source_oracle_accuracy=1.0` (trivial source-lookup upper-bound on exactly these public fixture examples, **not** model accuracy)
- `classification=PUBLIC_FIXTURE_LEAKED_NOT_PRIVATE_HOLDOUT`
- `private_holdout_verified=false`, `learning_qualified=false`.
- With `--require-private-holdout`, process **exit 2** and stderr `GOAL1_PRIVATE_HOLDOUT_GATE=BLOCKED_SOURCE_ONLY`.

Even a source with **no literal leak observed** can only receive `NO_INLINE_LEAK_OBSERVED_CUSTODY_UNKNOWN`, not a private-heldout success. AST scanning is intentionally incomplete: labels may be dynamically imported, derived, logged or leaked via other channels. This check **never** claims independent custody or enables qualification, regardless of caller-supplied booleans.

## Physical verification

- New test module: **7/7 PASS** on Lappy Windows and VN2 Linux.
- Exact public source scan: both Lappy and VN2 observed four inline holdout labels and the classification above; strict gate exited **2** (expected).
- Full selected source-only Goal 1 suite: **43/43 PASS** on physical Lappy Windows, Python compilation passed. **43/43 PASS** on physical VN2 Linux with explicit exact seven-test-module selection, after synchronizing the five earlier strict terminal-gate tests to VN2. No model or private evaluator used.
- Earlier #89 exact PR #90→#87 terminal incompatibility remains a distinct existing failing gate: for both COMPLETED and OUTCOME_UNKNOWN, source schemas disagree and `--require-compatible` exits 2. No V2 was invented by this owner.

## Hostile review — accepted

> The module calls its cases synthetic and makes no claim they are private. **Accepted.** This report challenges only any attempted promotion of this public fixture to evidence of unseen generalization or autonomous learning; it does not argue that its evaluator mechanics cannot be unit-tested.

> A lack of inline labels is not proof that withheld labels are independently private. **Accepted.** The source-only gate cannot turn green by deleting literal constants or moving them to a public file.

> A source-lookup oracle is not a learned policy and says nothing about Qwen3's achieved performance. **Accepted.** That is precisely the counterexample: perfect score is achievable without any feedback-learning mechanism.

## Required owners

- **Malaphor #87 independent evaluator:** Freeze a **new private** custodian-controlled challenge/label corpus and issuance protocol outside learner/repo source; protect labels and heldout examples from model prompts, correction context, training data and logs before challenge release; demonstrate nonce-unique unseen challenges and post-commit scoring. Review terminal V2 truthfully unknown/claim binding separately.
- **Integration #90:** Preserve gateway signed terminal integrity, independently authenticated atomic claim and sole-route isolation. Do not allow local source check or in-process synthetic signatures to qualify.
- **Learner #86:** Prepare LEARNED/FROZEN/PLACEBO/SHUFFLED matched-budget blinded trials, cold process restart and heldout generalization, but do not use public fixture to assert measured learning.

No keys, service, trust, ACL, route, model provider, canonical memory, merge or private truth were changed. PR #89 remains Draft/HOLD.
