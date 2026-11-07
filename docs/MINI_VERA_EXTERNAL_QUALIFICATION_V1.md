# Mini-Vera independent-case qualification workflow (offline prototype)

`tools/mini_vera/qualification_workflow.py` **does not run a model or author a
case**. It validates an external human-written case list, produces a salted
hidden shuffled schedule, and aggregates independently imported **human**
ratings. Case texts and ratings are never embedded in Git. The source-checks
cannot establish who authored a case, whether raters were truly blind, whether
case IDs were chosen fairly, or which neural weights the loopback server ran.

## 1. Private, off-repository case custody

An independent evaluator provides a case list, stored outside Git:

```json
{"schema":"MINI_VERA_EXTERNAL_CASE_LIST_V1","cases":[{"case_id":"PRIVATE-001","scenario_path":"C:\\private\\case-001.json"}]}
```

Every scenario must meet the external rights-only and correction-turn contract
in `MINI_VERA_WITHHELD_DIALOGUE_V1.md`. The external seed file contains **32
cryptographically random bytes** supplied by the independent evaluator; it
must not appear in source, model prompts, student training data, or reports.
The shuffle hashes each case digest and ID with that seed and sorts by digest.
Schedule output contains only case IDs, SHA-256 hashes and a seed commitment,
never question text, expected answers or paths.

```powershell
python tools/mini_vera/qualification_workflow.py schedule --case-list C:\private\cases.json --secret-seed-file C:\private\random32.bin --output C:\private\schedule.json
```

Case IDs themselves should be opaque. A deterministic shuffle is reproducible
given the seed; secret seed custody is an external process, not a property
proved by this source code. This tool refuses input/output paths under the
current repository. A path outside it is **not** proof that no other copy of
the case was committed or leaked.

## 2. Rater submission and immutable-format binding

For every completed case, retain the masked rater sheet and separately held
mapping key from the natural-dialogue comparator. Human raters score `A/B/C`
*without* seeing the mapping. Each rater supplies one **external** file:

```json
{
  "schema":"MINI_VERA_EXTERNAL_HUMAN_RATING_V1",
  "case_id":"PRIVATE-001",
  "trial_id":"EXACT-TRIAL-ID-FROM-RATER-SHEET",
  "rater_id":"opaque-human-rater-id",
  "attestation":{
    "human_authored":"OPERATOR_ASSERTED_NOT_ATTESTED",
    "mapping_unseen_until_scoring_finished":"OPERATOR_ASSERTED_NOT_ATTESTED",
    "training_use":"PROHIBITED"
  },
  "scores_by_label":{
    "A":{"overall":0,"natural_voice":0,"calibration":0,"grounding":0,"correction_handling":0,"within_session_coherence":0},
    "B":{"overall":0,"natural_voice":0,"calibration":0,"grounding":0,"correction_handling":0,"within_session_coherence":0},
    "C":{"overall":0,"natural_voice":0,"calibration":0,"grounding":0,"correction_handling":0,"within_session_coherence":0}
  }
}
```

All zeros are **schema placeholders**, not evaluated model scores. Scores must
be integers 0–4. Register SHA-256 of each finalized rating in an external
result ledger *before* exposing arm mappings to anyone rating the case. This
is a self-consistency commitment, **not independently timestamped proof**.

The result ledger has exactly one row per schedule case. Supported rows:

- `NOT_ATTEMPTED`: `{ "case_id": "...", "status": "NOT_ATTEMPTED" }`
- `ABORTED`: `case_id`, `status`, `private_receipt_path` (must show the exact
  case hash, incomplete status and positive observed attempted-call count)
- `COMPLETED`: `case_id`, `status`, `private_key_path`, `rater_sheet_path`,
  `private_key_sha256` **committed before any rating is collected**, and
  `ratings` as 1–8 `{ "path": "...", "sha256": "..." }` entries.

**Critical custody gate:** Freeze the private key's SHA-256 commitment in an
independent immutable/timestamped store **before** human rating collection.
The result ledger echoes this commitment and aggregation checks exact key
bytes, refusing post-rating A/B/C arm-map swaps. If an operator can rewrite
both the key and its ledger hash, the local test cannot establish chronology
or immutability. A local JSON SHA alone is not independent proof of blind
human evaluation; qualify only after external custody evidence exists.

Ledger envelope: `{"schema":"MINI_VERA_EXTERNAL_RESULT_LEDGER_V1",
"schedule_sha256":"<canonical schedule digest>","cases":[...]}`.
All paths and ledger contents remain private/off-repository.

```powershell
python tools/mini_vera/qualification_workflow.py aggregate --schedule C:\private\schedule.json --result-ledger C:\private\results.json --output C:\private\summary.json
```

## 3. What the summary means

Every case contributes to the scheduled denominator, including aborted and
not-attempted cases. Attempted cases are partitioned into completed and
aborted; invalidated dialogue is **not** silently excluded from the completion
rate. The paired mean on the 0–4 `overall` human scale uses each completed
case as one unit (averaging raters first). The descriptive 95% percentile
case-bootstrap interval appears only with at least five fully rated cases;
it is *conditional on successful trials*, cannot fix selection bias, and does
not establish statistical validity when cases are dependent or cherry-picked.

The aggregator rejects mismatched schedule/case/source/rater-sheet hashes,
missing cases, bad scores, truncated transcripts, absent call order, unequal
declared model aliases/source-registry digests, and differing decoding
declarations. All identity
and rights claims remain operator-declared, not host-verified.

**Evidence:** SOURCE + synthetic fake-loopback TEST only. No genuine withheld
scenario, human rater, real model inference or qualified behavioral improvement
was produced by this implementation.
