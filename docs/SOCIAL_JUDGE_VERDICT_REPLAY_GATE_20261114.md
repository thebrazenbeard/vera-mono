# Synthetic social review: raw-verdict replay gate (2026-11-14)

Scope: existing Vera Mono OPEN DRAFT PR #214, source-only evaluation.
No private user conversations, host configuration, model weights, runtime,
memory, independent-review qualification, or protected effects changed.

## Falsifier: observed RED

The audit accepted a reviewer's caller-supplied `judgment` and converted
`parsed_valid` with `bool(...)`. An adversarial synthetic review could
change a valid winner A to B without changing the reviewer's stored
`raw_response`; could change the raw answer but retain its old verdict;
or could replace a Boolean with the truthy string `"false"`.
Before the fix, focused Python3.12 pytest reported **3 failed subtests,
1 passed test, 17 deselected, RED_EXIT=1**: audit did not raise.

## Repair and observed GREEN

`scripts/audit_social_multiturn_review.py` now checks the review
schema and typed flag, reparses each recorded `raw_response`, runs
the original producer's `validate_judge_output`, and compares the exact
recomputed parser verdict to the stored `judgment` and `parsed_valid`.
This does not change the reviewer prompt or favor either candidate.

Focused tests: Python3.12 **18 passed +7 subtests**, exit0;
Python3.12 `-O` **18 passed +7 subtests**, exit0 with expected pytest
optimization warning; Python3.14 **18 passed**, exit0 with pre-existing
pytest-asyncio warning. `git diff --check` exit0.

## Unmodified baseline replay

Replay of the original 12-case / 72-record synthetic evaluation: exit0.
All 8 comparable judgments still favored the **same A/B letter**
even after swapping the underlying answers; **zero** concrete
position-stable model winners, overall behavior qualification false.
Report SHA-256: `f750a50e2ddb8708bbd949e864bd9e035100e13a0c5da77431a8a9a9839a73fb`.
Source files and old judge decisions were not modified.

## Trust ceiling / hostile challenge

> This guards consistency of the saved raw answer and parsed verdict,
> **not authenticity**. A party able to rewrite both consistently can
> still counterfeit a reviewer decision, and the local judge has
> demonstrable A/B position bias. Neither model wins a behavioral
> qualification from this source-only replay. A genuinely independent,
> separately anchored evaluation on unseen dialogue remains necessary.

## Full regression suite

Correctly configured Vera Mono Python3.12 pytest over all `tests` with
`packages/*/src` on `PYTHONPATH` and isolated D: pytest base:
**1,186 passed, 104 skipped, 283 subtests passed, one existing
PytestCollectionWarning, FULL_EXIT=0**, completed in 124.00 seconds.
`git diff --check` exit0. No hosted CI claim.
