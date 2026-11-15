# Mini-Vera — synthetic durable revision across process restarts (2026-11-15)

**Subject:** stacked source candidate from `vera-mono` OPEN DRAFT PR #234 HEAD `0419cd5d9efbeb3217b6a1e50164fcb50d8d2c47`. Separate owned VN1 branch `bt2/mini-vera-revision-restart-canary-20261115`. This is **SOURCE / SYNTHETIC TEST evidence**, not a live model or installed host memory authority. LANTERN_CURRENTNESS remains UNKNOWN.

## Motivation and non-duplication

`tools/mini_vera/restart_public_canary.py` already proves a disposable PUBLIC record can re-enter request context in fresh Python processes. `varied_public_canary.py` has an R1/R2 *sentence inside one record*, not an actual **ledger successor**. The existing `vera_memory.MemoryLedger` has durable `supersedes` lineage with status checks, and `approved_ledger_provider` plus `local_session.main` already perform pre- and post-inference public authorization. This candidate exercises those mechanisms; it **does not create a competing store, add a writer to the neural shell, or open actual user memories**.

## New reusable canary

`tools/mini_vera/revision_restart_canary.py --run-trial` constructs a temporary SQLite ledger with three generated synthetic records: an unapproved PRIVATE decoy, a prior PUBLIC gate-code record, and a new PUBLIC gate-code record which **supersedes the prior by admitted ledger lineage**. It then launches **five fresh Python worker processes**:
- two corrected-current PUBLIC reads, independently generated new process each;
- one empty-memory control;
- one attempt to reproject the superseded predecessor, expected to fail before inference;
- one current-record projection with host approval revoked, expected to fail before inference.

The corrected current answer is kept in the parent evaluator, not given to the children. Two correct current answers plus UNKNOWN for the control and refusal in both negative arms are required for a behavioral pass. Each scored report contains only a SHA-256 digest of the synthetic token, statuses and counts; never raw private marker, generated token, or model prose. The synthetic host policy matches more than the stored PUBLIC privacy label. The worker refuses ordinary arbitrary ledger paths before opening a database, including non-temporary folders, basic symlinks/junctions and hardlink aliases. **This path check is only harness containment**, not an authenticated human/operator grant; callers must not use `--worker` for private data.

## Executed TDD / exact limitation

- New test `tests/test_mini_vera_revision_restart_canary.py` initially **RED** with missing source canary module (one ImportError, exit1); implemented module, then **GREEN** (3 tests pass). Tests use actual **SQLite transaction/record supersession, subprocess isolation and loopback HTTP payload capture** but a **fake reply-producing server**, not neural inference. The fake server always returns UNKNOWN, so behavioral_pass is correctly **false**, not disguised as success. Each of the three model-facing calls contains only approved corrected PUBLIC record or empty control; superseded and revoked arms perform **no HTTP**.
- Added hostile test: arbitrary external-path worker must refuse before even constructing/opening `MemoryLedger`. It **RED** with assertion failure (exit1), showing a path admission mistake. New worker path gate initially exposed a Windows `type(Path) is Path` mistake in rerun (one error, exit1), corrected to `isinstance(path, Path)`. Then **4 tests passed, exit0**, ~2.1 seconds. No success claim hides the intermediate mistake.
- Output schema: the emitted `synthetic_token_sha256` hashes only the synthetic answer token, not the complete memory record. A dedicated RED test caught the earlier inaccurately named `current_record_sha256` (KeyError, exit1); label corrected, four focused tests GREEN, exit0.\n- The full VN1 Python3.13 Mini-Vera regression after that correction **PASSED: 476 tests, 17 skipped, 0 failures, exit0** (122.965s unittest). OffGit log SHA-256 `9a7d19d93c775805d9e6a7d1ee075c65ca6c17b70936a6e2664a11583418cbe3`; log also contains a nonfatal Windows fake HTTP teardown `WinError 10053`. Optimized Python3.13 `-O` focused revision + old restart + varied-public regression **19 tests passed, exit0** (11.418s), offGit log SHA-256 `70e178fc4fffd964eed51c77901313b8fb43e034dc526a5ed84cd58d26b65a43`. `git diff --check` exit0.\n- The trial does not authenticate a model's tensors or host grant, establish privacy beyond its synthetic fixture, prove neural recall, qualify stochastic generalization, or validate an installed durable user memory service. Packaging and publication must be verified separately.

## Subsequent acceptance boundary

Future permitted runtime work should exercise real local model corrections with fresh held-out cases and independent scoring while preserving private isolation, host-issued grants, actual revocation, human authority, and rollback. The prior live 4B execution block remains a **hold**; do not route around it. Source tests cannot settle that issue.
