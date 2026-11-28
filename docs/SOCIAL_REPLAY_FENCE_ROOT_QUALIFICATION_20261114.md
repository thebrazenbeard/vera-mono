# Synthetic correction replay fence: unadmitted initial history (2026-11-14)

**Provenance:** Lappy `D:\VERA\experiments\social-appraisal-pr214-20261113`, `thebrazenbeard/vera-mono` Draft PR #214; fiction-only Ed25519 test keys. Source-only; no native control, canonical memory, user private material or external effects.

## Hostile falsifier and actual RED

> Can a validly signed correction smuggle a previous *unsigned/unadmitted* ledger history into a brand-new persistent replay fence, simply because the signature covers the new event's previous-head digest?

Yes, before this change. The verifier correctly validates the *new* event signature and its claimed parent hash, but neither cryptography nor caller-supplied `CorrectionLedger` authenticates prior events. In `CorrectionReplayFence.claim`, the old `if count:` lineage guard deliberately skipped the first candidate. A signer could therefore sign event #2 on a caller-generated historical ledger, and the fence recorded event #2 as its first accepted candidate, making unverified source events implicit prior state.

TDD: added `test_first_candidate_rejects_unadmitted_prior_ledger_history` first in `tests/test_social_correction_replay_fence.py`. The test constructs synthetic entry `invented-prior`, appends it locally without admission to fence, generates a **genuinely valid ephemeral Ed25519 signature** for a new distinct candidate whose parent is the invented ledger head, and first verifies the signature succeeds. The actual existing implementation then accepted this first claim incorrectly. Observed **RED** Python 3.12 pytest: `AssertionError: FenceBlocked not raised`, 1 failed, 12 deselected, `RED_EXIT=1`. This is an actual behavior assertion, not a module-import failure.

## Minimal fix and GREEN

In `packages/vera_core/src/vera_core/social_correction_replay_fence.py`, require `witness.expected_previous_head == ROOT_HEAD` when the persistent fence has zero accepted candidates. Any first event preceded by caller-only ledger history fails before SQLite INSERT and metadata update. Subsequent candidates already require `previous_ledger_head` equal to the last accepted candidate's resulting head and are unaffected.

Same targeted test: **1 passed / 12 deselected, GREEN_EXIT=0**. Existing focused replay, checkpoint, cross-process signature and witness tests: **38 passed / 74 subtests passed, FOCUSED_EXIT=0**. Full-suite, optimization, Python3.14 and repository verification recorded after completion.

## Effect limits and possible host integration

This prevents one unadmitted-history promotion path in the synthetic SQLite fence. It is NOT an independently trusted host replay store, verified real-time user-origin signature, independent checkpoint writer, retention policy, release binding, or proof of relational competence. `synthetic_fixture_mode=True` remains mandatory; production mode remains disabled. A legitimate migration from a pre-existing ledger would require a separately specified authenticated, rooted checkpoint admission protocol and must not silently bypass this genesis check.

No model identity, consciousness, user consent, protected action or canonical memory is inferred. No host service started, no key registered, no live database installed and no user text stored.

## Full source verification and receipts

- Full Lappy Windows Python 3.12.10 test suite: `py -3.12 -m pytest -q --tb=short --basetemp=D:\VERA\experiments\social-replay-root-full-20261114 tests`: **1182 passed, 104 skipped, 278 subtests passed**, **one pre-existing PytestCollectionWarning**, `FULL_EXIT=0`, 143.90 seconds.
- Focused normal Python 3.12 witness/fence/checkpoint/cross-process suite: **38 passed +74 subtests, FOCUSED_EXIT=0**.
- Focused optimized Python 3.12 `-O`: **38 passed +74 subtests, OPT_EXIT=0**, expected pytest optimization warning.
- Focused Python 3.14: **38 passed, PY314_EXIT=0**, expected pytest-asyncio deprecation warning.
- `compileall` exit0; `git diff --check` exit0. These are local source tests only. No hosted CI result is implied.
- GitHub publication/remote-head verification, when performed, is a separate evidence class from these local test results.
