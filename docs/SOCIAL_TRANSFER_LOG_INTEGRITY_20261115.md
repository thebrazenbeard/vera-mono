# Relational Agency: local model A/B log-integrity falsification

Date: 2026-11-15.
Status: SOURCE-ONLY RESEARCH, existing Vera Mono Draft PR #214.
Parent commit: a9259a19e773f662ebe9bb66eeb0bab95bf2b512.
This is a reproducibility improvement, not social competence qualification,
independent review of model behavior, or native Vera installation.

## What failed before this increment

Two other authorized machines independently used the existing audit program
on the frozen synthetic eight-case trial:
- VN1 Windows, Python 3.13, Qwen3.5:0.8B previously recorded 48-row log.
- VN2 Linux Mint, Python 3.12, Qwen3:4B previously recorded 48-row log.

The then-current scripts/audit_social_behavior_transfer.py incorrectly
accepted permuted record ordering, including an out-of-sequence dialogue.
It accepted negative eval_count and accepted a substituted response string.
A healthy-looking JSON audit from this version could overstate provenance,
while source/prompt hashes alone could not bind answer bytes.

> A substituted model response is especially important: without an
> independently retained digest of the entire output file, the auditor
> has no basis to recognize modifications to the answer text.
> A self-declared digest inside the same mutable file would not fix this.

## Bounded repair

- Require exact sequence from the existing runner: fixture case order,
  prompt-arm order alternated between successive cases, then three
  sequential user turns for each arm. Reject missing, duplicate, foreign
  and reordered records.
- eval_count must be an integer, not a bool/float/null, and nonnegative.
- Optional CLI --expected-results-sha256 takes an exact lowercase 64-digit
  SHA256, compared with raw file bytes before parsing. Report
  result_hash_pinned and model_response_authenticated=false.
- Existing fixture/system hashes, user/source text, model identity/digest,
  seed, no-tools flag and truncation diagnostics remain checked.

No old model results were modified. Pinned audit of both existing
archives passed, preserving their original SHA256:

| Frozen source | Records | Complete | Length-capped | Raw SHA256 |
| --- | ---: | ---: | ---: | --- |
| Qwen3:4B seed79 | 48 | 40 | 8 | b7572c2d0a2458927480a2ba91d494f12a335389d2335a7bffceb7cb7c74e463 |
| Qwen3.5:0.8B seed79 | 48 | 46 | 2 | 8aa0fdd19dfa8eb1272d80e24c357b4917975e41e9cdbc00b99236e7cc633a7f |

Fixture SHA256:
f4a429cc474d9ac2eab5c86a4e80ff248a5c4716a7d661df48ebe2be29636dd2.

The fixtures and raw response logs predate this increment.
This work does NOT create 96 new model generations.

## Local test evidence

Test-first hostile checks in the previous interruptible iteration
found five failing reorder/count cases before code correction.
After repair: 7 passed and 13 subtests, exit0.
Added a second-case fixture to guard the existing runner's
intentional per-case prompt-arm reversal. Expanded focused suite:
- Python3.12: 8 passed, 13 subtests, exit0.
- Python3.12 -O: 8 passed, 13 subtests, exit0; expected
  optimized-assert pytest warning.
- Python3.14: 8 passed, exit0; preexisting pytest-asyncio
  deprecation warning.
- Python3.12 compileall and git diff --check: exit0.

Fresh full Python3.12 suite after changes: 1263 passed, 106 skipped, 363 subtests passed, one preexisting TestVerifier collection warning, exit0, 128.61 seconds.
Cross-workstation falsifier at commit 7bfe528:
- VN2 Linux Python3.12: 8 unittest cases passed and pinned Qwen3:4B
  48-row audit passed, original SHA256 preserved.
- VN1 Windows Python3.13: 8 pytest cases and 13 subtests passed,
  but the pinned 0.8B log audit correctly FAILED. VN1 has
  core.autocrlf=true. Both published 48-line raw JSONL files lacked
  a per-file -text rule: checkout inserted 48 CR bytes in each file.
  The original Git blob SHA256 matched the pinned expected value,
  while the altered working files did not.
- Added byte-preserving -text rules for exactly those two JSONL
  files in evaluations/.gitattributes, leaving original logs
  entirely unchanged. This is a checkout-currentness fix rather
  than an adjustment to the auditor or evidence.
Final exact-head 5299687 cross-machine revalidation:
- VN1 Windows Python3.13, FRESH isolated sparse Git clone with
  core.autocrlf=true: both raw JSONL worktree files exactly match
  Git blobs (zero CRLF), with the original 46399-byte and
  54544-byte lengths and frozen SHA256 values. The new -text
  attribute is unset on both files. Eight pytest cases and
  13 subtests passed; 0.8B pinned 48-row audit PASS, exit0.
- VN2 Linux Mint Python3.12, refreshed same exact commit:
  8 unittest cases PASS and 4B pinned 48-row audit PASS,
  exit0; both attributes report unset.
- GitHub PR #214 remains a SOURCE-ONLY research draft.
  This validates source byte portability, not model authorship,
  native deployment, host access authority or social quality.
No device reboot, model inference, native release or merge occurred.

## Material hostile limits

> Exact ordering shows consistency with the expected output structure,
> not witnessed model execution. An attacker controlling every record
> could recreate the same structure.

> SHA256 proves byte identity only relative to an independently trusted
> expected digest. A hash recorded alongside an editable log does not
> establish independent provenance. No signed external inference transcript.

> Qualifying raw logs does NOT qualify model judgments, social competence,
> empathy, preferences or subjective experience. The prior eight-dialogue
> synthetic fixture was authored by the research team and previously viewed.

Scope: audit source, regression tests and this report only in the
existing source-only draft PR. No merge, deploy, native Project install,
training, private/canonical memory changes, credentials, production
machine configuration, other delegated repos or spending.
