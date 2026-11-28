# Correction replay fence — synthetic-only experiment (2026-11-14)

Status: SOURCE ONLY. PRODUCTION DISABLED. No authenticated host, independent checkpoint, installed memory or protected effect.

Scope: Existing thebrazenbeard/vera-mono Draft PR #214, separate from Mini-Vera-owned PRs and the pre-existing replay systems under vera_memory.supervised_feedback and vera_pc_connection.journal. This narrowly tests the replay gap of the source-only Ed25519 user correction witness.

Source: packages/vera_core/src/vera_core/social_correction_replay_fence.py
Tests: tests/test_social_correction_replay_fence.py

## Exact mechanism

The CorrectionReplayFence requires synthetic_fixture_mode=True. No database is created in default production mode. SQLite records a random journal ID, installation and issuer/key binding, public-key fingerprint, opaque signed witness digest, previous/resulting correction ledger heads, and an SHA-256 chained local candidate sequence. It does not store private signing keys, raw statement text, subjects or conversations.

Each claim recomputes the signed correction check, then uses SQLite BEGIN IMMEDIATE to compare the supplied expected fence head with the actual read-replayed state, enforcing a unique signed witness and matching previous accepted ledger head. A separate SQLite readback checks the committed local candidate chain. Returned status is LOCAL_CANDIDATE_UNCONFIRMED and explicitly authorizes no external effect or canonical memory.

Any existing database requires an external previously retained checkpoint on opening. A caller-supplied pin is not independent authority. A database and its checkpoint both writable by an attacker can be rolled back together; that case is not protected. The model cannot authenticate the signer, current user, host custody, private storage, real consent, or durable effect.

## Test-first evidence

- Initial RED: missing replay-fence module at test collection, exit2; subsequently one first GREEN run required a Windows Path subclass fix.
- First nine expanded tests: eight passed; one test fixture failed Windows temporary-file cleanup because a sqlite3 connection was left open by the test; corrected the test to explicitly close its connection. Nine passed.
- Hard-link substitution after initial path check: reproducible RED (expected FenceBlocked not raised), then fixed by rechecking path before each new connection, GREEN.
- Deleted existing database silently recreated by SQLite: reproducible RED (file unexpectedly existed after failed access); fixed by requiring read-write mode=rw existing-file URI and refusing missing files, GREEN.
- Tests construct only fictional signed corrections, ephemeral Ed25519 keys and temporary SQLite paths. No real user text.
- Actual concurrency test starts four independent Python subprocesses attempting the same synthetic claim against the same database: precisely one accepted locally and three refused. Sequential distinct corrections can be consumed in ledger order.
- Wrong key/installation/checkpoint, altered signature, tampered database hash, and database rollback with a separately held newer checkpoint are rejected. Path checks reject symlink and hard-link substitution in tested cases.
- Focused Lappy Python 3.12 suite: 11 passed, exit0. Broader test results will be appended after completion.

## Hostile release challenge

> SQLite atomicity does not prove host authority. A caller controlling both database and external checkpoint may recreate a past state. Path validation is not atomic OS handle or ACL enforcement. Source-only signing and local duplicate suppression cannot establish protected identity, actual user source, one-time semantic effect, or private memory admission. Do not deploy or promote based on this test result.

Unresolved: independently protected checkpoint custody, authorized real host identity/key, source-currentness observation, consent and effect separation, power-loss and provider qualification, and independent multi-seed behavioral tests. No merge, deployment, canonical memory, production services, or actual permissions changed.

## Final Lappy verification and negative evidence

The first post-implementation full suite on the exact experimental source checkout returned **1115 passed, 104 skipped, 198 subtests passed, one failure**, exit1: unchanged tests/test_deep_memory_cli_transport.py::PinnedCLITest::test_slow_stdout_is_killed_at_deadline expected its subprocess PID file within 0.2 seconds but the file was missing under broad-run load. This is the previously observed timing-sensitive test outside this module, not a source change or a claim that it is fixed. One attempted grouped isolated retry had an invalid PowerShell-generated --basetemp and three command-line parser exits 4; corrected the test invocation. The correct isolated test then passed **3/3** runs (exit0 each).

Final post-fix full rerun on Lappy Windows Python3.12.10:
py -3.12 -m pytest -q --tb=short --basetemp=D:\VERA\experiments\social-correction-replay-recheck-20261114 tests
**1116 passed, 104 skipped, 198 subtests passed**, one preexisting collection warning, **exit0**, ~112.65 sec.

Replay-focused tests: **11 passed**, exit0, Python3.12 standard, Python3.12 -O (expected pytest assert-mode warning), and Python3.14 (pytest-asyncio deprecation warning). Python3.12 compileall exit0. No hosted CI checks claimed. Actual four-child interpreter race was exercised by these tests. Source-only release boundary remains unchanged.
