# Synthetic multi-turn review audit: duplicate-record integrity
Date: 2026-11-14. Scope: existing vera-mono Draft PR #214 only.
Owner: relational-agency research worker. Source-only, unmerged, uninstalled.

## Hostile falsifier and observed RED
The audit converted blind/reversed/judge JSONL into dictionaries keyed by case ID,
silently overwriting duplicate records. Generated turn validation checked only
total length and fixture hash, not the exact case/model/turn multiset.
A hostile fixture derived from the committed 12-case, 72-generation benchmark
appended an identical judge row; a second replaced the last generation with
the first and updated only the caller-supplied mapping digest.
Both incorrectly passed the original audit. Command:
`py -3.12 -m pytest tests/test_social_multiturn_review_contract.py -k duplicate_rows -q`
Observed RED_EXIT=1; 2 subtest failures because ValueError was not raised.

## Narrow implementation and observed GREEN
`scripts/audit_social_multiturn_review.py`: refuse duplicate cases before
forming dictionaries (blind, reversed, initial/reversed judge); require each
exact (case_id, model, turn_index) exactly once using the recorded assignments.
`tests/test_social_multiturn_review_contract.py`: two adversarial
same-length/rehashed input mutations, plus the untouched artifact baseline.
Command: `py -3.12 -m pytest tests/test_social_multiturn_review_contract.py -q`.
Observed GREEN_EXIT=0; 15 passed, 4 subtests passed.
Python 3.12 -O: 15 passed, 4 subtests, 1 pytest optimization warning;
OPT_EXIT=0. Diff check exit0.

## Trust ceiling
The changed audit protects record cardinality and identity, not authenticity
of model outputs, reviewer independence, bias, semantic correctness, or claims
about Vera's current state. The existing swap audit still disqualifies the
position-biased judge; no previously reported model win is upgraded.
No private Library text, keys, credentials, production runtime, memory,
protected actions, or model weights were copied or changed.

## Integration verification and host boundary
An initial full-suite attempt ran without child-process PYTHONPATH and reported
5 subprocess import failures (`vera_core` missing), not a changed assertion.
A narrower retry with only vera_core/src still failed on portfolio_runtime;
the five affected test files passed 21/21 +7 subtests once PYTHONPATH
included all repository packages/*/src (RETRY_EXIT=0). The complete correctly
configured Lappy Python 3.12 suite then passed: 1183 passed, 104 skipped,
280 subtests passed, one pre-existing PytestCollectionWarning, exit0
(140.66 seconds; isolated D: basetemp). This qualifies source regression
consistency under that invocation only, not deployed model behavior.
Read-only `probe_social_host_boundary.ps1` on the isolated Lappy checkout
reported broad write grants on checkout and parent, reference service
NOT_RUNNING, and `production_qualified=false`. These are host observations,
not authorization, and the probe did not create or mutate a service.
