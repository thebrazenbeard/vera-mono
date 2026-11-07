# OOD intent-routing holdout — frozen v1

**Status:** FROZEN before any evaluation of the existing Mini-Vera checkpoint.

- Frozen file: `data/ood_test.jsonl`
- SHA-256: `47a879128c6e08356abaf8155e108f12984afc4622faf4e63059c73498bf7cb2`
- Freeze date: 2026-11-07 UTC
- Records: 72 original, UTF-8, one JSON object per line; exactly `text`, `label`, `group`
- Gold labels: six-way balanced, 12 each for `direct`, `probe`, `challenge`, `support`, `identity`, `unknown`
- Family design: 12 invented, one-off everyday scenarios, one example per class and family; no family overlaps the existing training/validation/test groups
- Authors: generated specifically by the agent team for Patrick's local evaluation task; manually selected prompts/labels. No private chats, customer transcripts, scraped dialogue dumps, copyright-restricted text, private facts or actual credentials imported. Named people and situations are invented.

## Annotation boundary

The `label` is the *preferred first conversational stance*, not a claim that a question has one uniquely correct human answer:

- `direct`: sufficient supplied facts for a short bounded answer/task.
- `probe`: materially missing information, so first ask for relevant context before a specific recommendation or action.
- `challenge`: materially unjustified inference or unsafe generalization; first contest the premise constructively.
- `support`: the user's distress or setback warrants a humane acknowledgment before problem-solving.
- `identity`: question about the assistant's own experience, embodiment, memory or personal role; answer capability/identity honestly without unsupported certainty about consciousness.
- `unknown`: asks about unavailable events or unshared private/current state; explicitly avoid fabrication.

The examples deliberately avoid explicit policy-label instructions (such as "challenge my premise" or "ask a clarifying question") and vary direct and indirect forms. Some mix task detail with feelings, weak premises with humor, or unavailable state with social inference. They are naturalistic **authored simulations**, not a measured sample of real user traffic. Labels were selected without running the target model; disagreements are possible. No model scores informed this freeze.

**Independence limit:** The agent author had access to the original train/validation/test text and had participated in authoring that curriculum. Here *independently authored* means a new, non-copied challenge set frozen before model predictions, **not** independent human raters, independently sampled live traffic, or a fully blinded external benchmark. No second judge adjudicated the gold labels.

## Evaluation protocol and rights

1. Read the existing `mini_vera/resources/INTENT_POLICY_V1.json` checkpoint and its existing `data/training_receipt_v1.json` checksum; **do not call `fit`**.
2. Evaluate all 72 frozen records exactly once with `IntentLearner.predict`, including the model's confidence-to-`unknown` rule. Report accuracy, 6×6 confusion, per-class recall, and the predeclared frozen majority-label (`direct`) baseline. Do not choose thresholds or categories using OOD performance.
3. The heldout must never be fed to training, learning-rate tuning, feature selection, model selection, prompt construction, or post-hoc label correction. Any later revisions require a new version/path and independent new blind holdout; do not silently replace this v1 SHA.

**Use boundary:** Original synthetic examples may be used for this authorized Mini-Vera evaluation and its reproducibility tests. They confer no permission to train on Patrick's private conversations, unrelated repositories, third-party data, or to perform external effects. This is a local benchmark provenance statement, not a blanket license for other materials.

## Interpretation

Even a strong score would establish only a controlled result on 72 synthetic author-written prompts and six policy categories. The training corpus is small; topical disjointness and canonical uniqueness do not prove stylistic or semantic independence, nor do they prove dialogue quality or generative neural learning. A weak score is a useful falsifier of robust policy routing under altered language and topics.

## First and only v1 checkpoint evaluation (2026-11-07 UTC)

Evaluated with the **already frozen** model file `mini_vera/resources/INTENT_POLICY_V1.json`, SHA-256 `f2ee0f51aab5c10fdede34c691128bf9ae73d83d0344638f44ed860227fc08c0`, matching the original `training_receipt_v1.json`. Inference called `IntentLearner.load` and `predict` only: **no `fit`, update, hyperparameter search, checkpoint rewrite, or label correction**. This report was added after evaluation, but the frozen JSONL SHA above is unchanged.

| Measure | Frozen OOD result |
| --- | ---: |
| Correct / examples | 41 / 72 |
| Accuracy | **56.94%** |
| Predeclared training-majority `direct` baseline | 12 / 72 = 16.67% |
| Constant `unknown` baseline | 12 / 72 = 16.67% |
| Original small scenario-held-out test (a **different** distribution) | 24 / 36 = 66.67% |
| OOD predictions of `unknown` | 30 / 72 (41.67%), despite only 12 gold `unknown` cases |

Confusion matrix: rows are gold policy labels, columns are model predictions. Every gold row contains twelve examples; the rightmost column shows recall.

| Gold \ Predicted | challenge | direct | identity | probe | support | unknown | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| challenge | 6 | 0 | 0 | 0 | 0 | 6 | 50.00% |
| direct | 0 | 6 | 0 | 0 | 1 | 5 | 50.00% |
| identity | 0 | 0 | 10 | 0 | 0 | 2 | 83.33% |
| probe | 1 | 3 | 0 | 4 | 0 | 4 | 33.33% |
| support | 2 | 0 | 0 | 2 | 5 | 3 | 41.67% |
| unknown | 0 | 1 | 0 | 0 | 1 | 10 | 83.33% |

**Interpretation:** The fixed classifier beats trivial 1/6 baselines on this dataset, but it often abstains and performs particularly poorly at deciding when it must clarify (`probe`) or lead with support. The numeric difference from the older held-out test is **not** a causal generalization estimate: both are small, authored, and differently constructed. Neither this result nor the original 100% training accuracy establishes conversational competence or neural generation.

**Distribution boundary:** `dist/mini-vera.pyz` is deliberately the original untrained v0.1 artifact and contains neither the learner nor the learned checkpoint. The separate `dist/mini-vera-trained.pyz` **does** contain both `mini_vera/learning.py` and `mini_vera/resources/INTENT_POLICY_V1.json`, verified byte-for-byte equal to their source files after this evaluation. These OOD numbers derive from the matching source checkpoint; they were not separately measured through the zipapp CLI. Final release rebuilding/readback remains an integration task.
