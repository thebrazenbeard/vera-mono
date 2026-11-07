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

**Optional independently pinned key-checking seam (Wave 4):** Before a rater
sees any transcript, an evaluator can assemble a *private* manifest using
the already generated masked-dialogue keys:

```json
{
  "schema": "MINI_VERA_EXTERNAL_PRE_RATING_KEY_COMMITMENTS_V1",
  "schedule_sha256": "EXACT-CANONICAL-SCHEDULE-SHA256",
  "key_sha256_by_case": {"PRIVATE-001": "EXACT-CANONICAL-PRIVATE-KEY-SHA256"}
}
```

The manifest may contain a subset of scheduled cases, but every case later
reported as COMPLETED must have a corresponding digest. **The inverse holds
too:** a case with an externally pinned *completed-trial private key* must
remain COMPLETED in the result ledger, not be downgraded to ABORTED or
NOT_ATTEMPTED. The two case-ID sets must match exactly. This closes a hostile
denominator-relabeling reproduction in which five finished keys were pinned,
only four rating receipts were pinned, and the fifth completed case was
silently relabeled NOT_ATTEMPTED. A source trial truly interrupted before a
completed private key should use its separate aborted-attempt receipt.
Keep the manifest
outside Git, derive its canonical SHA-256 from sorted, compact UTF-8 JSON
(the same form as `loopback.canonical`), and **pin that SHA independently of
the mutable result ledger and the key files** before collecting ratings.
Then supply the pinned digest *from that independent channel* when aggregating:

```powershell
python tools/mini_vera/qualification_workflow.py aggregate --schedule C:\private\schedule.json --result-ledger C:\private\results.json --pre-rating-key-commitments C:\private\keys-precommit.json --expected-pre-rating-key-commitment-sha256 PINNED_SHA256_FROM_INDEPENDENT_CUSTODIAN --output C:\private\summary.json
```

With this input, changing both private arm mappings and their mutable ledger
hashes is **rejected** unless the separately pinned digest is also replaced.
**This key-only anchor does not protect the rating receipts.** In hostile
testing, replacing each rating's score values *and* its hash in the editable
ledger still reversed the result from +2 to -2, even while the key pin held.

**Optional post-rating, pre-unblinding receipt anchor:** After the independent
raters have submitted their scored sheets, but *before* anyone exposes the
arm mappings, an external custodian can pin the exact canonical SHA-256 of:

```json
{
  "schema": "MINI_VERA_EXTERNAL_POST_RATING_RECEIPT_COMMITMENTS_V1",
  "schedule_sha256": "EXACT-CANONICAL-SCHEDULE-SHA256",
  "rating_sha256_by_case": {"PRIVATE-001": ["EXACT-CANONICAL-RATING-SHA256"]}
}
```

Every later COMPLETED case must have exactly its independently pinned rating
hashes (one per distinct rater, up to eight); omitted and altered receipts
are rejected. Conversely, once a case is in the externally pinned rating
manifest it **cannot be relabeled NOT_ATTEMPTED or ABORTED** in the result
ledger; a hostile test reproduced this denominator-changing omission and its
rejection. The manifest's case IDs must match the ledger's completed-case IDs
exactly. This second manifest may include a subset of scheduled cases, but
cannot refer to a foreign case. Keep its full private contents outside
Git, and independently freeze the **manifest digest** outside the mutable
ledger and rating files. To check *both* source and submitted-score custody:

```powershell
python tools/mini_vera/qualification_workflow.py aggregate --schedule C:\private\schedule.json --result-ledger C:\private\results.json --pre-rating-key-commitments C:\private\keys-precommit.json --expected-pre-rating-key-commitment-sha256 PINNED_KEY_MANIFEST_SHA256 --post-rating-receipt-commitments C:\private\rated-receipts.json --expected-post-rating-receipt-commitment-sha256 PINNED_RATING_MANIFEST_SHA256 --output C:\private\summary.json
```

The synthetic original joint key/ledger attack changes an unanchored result
from +2 to -2, and the independent key digest rejects that attack. A second
hostile reproduction changes rating files and their mutable ledger hashes;
it still reverses a **key-only** anchored result, but is rejected when the
separate rating-receipt digest is pinned. The output distinguishes **no pin,
key-only, rating-only, and both**. None of these modes attests who supplied
the SHA values, when they were frozen, or that raters were independently
human and blind. Merely placing a digest on a CLI, in the same editable repo
or same-operator file is not proof of external custody. A truly independent,
timestamped and authenticated custodian is required for qualification.
Separately, the *disposition* of cases never externally rated (claimed
ABORTED/NOT_ATTEMPTED) is still operator-declared, not independently anchored
by this rating-manifest seam; an authenticated trial-outcome ledger would be
needed to establish noncompletion rates against adversarial omissions.

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
