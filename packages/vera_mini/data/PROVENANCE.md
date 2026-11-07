# Mini-Vera dialogue-intent curriculum V1

**Origin:** Original examples authored for this Mini-Vera experiment. No
transcripts, private repository files, copied model outputs, personal secrets,
or third-party copyrighted dialogues were imported.

**Scope:** Six dialogue-route categories: `challenge`, `support`, `probe`,
`direct`, `identity`, and `unknown`. The words are instructional labels,
not facts about any subject and not action/authorization permissions.

**Splits:** `train.jsonl` has 72 examples; `validation.jsonl` and `test.jsonl`
have 36 each. Each JSONL record has exactly `text`, `label`, and `group`.
Scenario groups are disjoint between splits to reduce contamination; simple
normalization checks also reject literal duplicates. This does not guarantee
semantic independence or external validity.

**Rights and consent:** These synthetic examples were created by this agent
team for Patrick's Mini-Vera local project, under the user's explicit request
to train Mini-Vera. The corpus is not a general grant to use Patrick's private
communications, other projects, or external datasets for training. Original
portfolio source files are for read-only retrieval research until rights and
source boundaries are separately resolved.

**Limitations:** 144 small, balanced, and intentionally structured prompts
are insufficient evidence of broad language understanding. Some examples
can reasonably support multiple labels. The test set was read to diagnose
failure modes after the first recorded training run; no claim of a fresh blind
test is made for subsequent tuning that uses that knowledge. A new untouched
benchmark would be required for further comparative claims.

**Reproduction:** Run `python tools/train_policy.py` from this package root.
The script reads the three exact split files, checks group/text leakage,
trains from zero with fixed seed, emits a parameter checkpoint, and writes
`training_receipt_v1.json` containing exact dataset and checkpoint hashes,
metrics, confusion matrices and the majority-class baseline.
