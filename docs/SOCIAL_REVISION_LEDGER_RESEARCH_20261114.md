# Social correction and commitment archive - bounded source candidate

Date: 2026-11-14. Owner scope: relational-agency research worker on vera-mono Draft PR #214. No native installation, private-memory admission, model training, or protected effect.

## Engineering motivation

The prior synthetic multi-turn models repeatedly lost user corrections, replaced the actual proposition with a different one, or treated a plausible-sounding historical preference as current. An instruction prompt alone did not reliably fix that. This source-only module adds a deterministic, *typed history boundary*; it does not assert human-like memory, selfhood, consent, or successful live integration.

File: `packages/vera_core/src/vera_core/social_revision_ledger.py`. A `CorrectionEntry` stores an exact subject referent, proposition category (DEFINITION, INTENT, FACT, PREFERENCE, CONSENT, COMMITMENT), source category, source session and turn identifiers, exact statement, event ID and explicit superseded event ID. The journal is bounded to 256 events, entries to 4000 characters and IDs to 256. Its public receipt omits text, subjects, session/turn IDs and hashes.

## Demonstrated invariants

1. A correction can replace only the latest event of the same exact subject and proposition category; no vague topical similarity or broad "everything the user believes" updates. It must explicitly link to that event ID. Unrelated topics remain unchanged.
2. Append requires an expected current chain head (local optimistic CAS), refuses duplicate IDs, missing parents, stale parents and changed subjects. The old version remains in the history.
3. Full-text snapshots require an explicit `snapshot(allow_sensitive_export=True)` opt-in; ordinary `snapshot()` calls raise `PermissionError`. The opt-in is an accident-prevention interface, **not** permission to export real private data. Snapshots serialize source metadata and entry text into an exact canonical JSON hash chain. Restore verifies the chain and an optionally supplied external expected head. The hash detects tampering only **relative to an independently retained anchor**; a complete forgery with recomputed chain hashes cannot be ruled out from the JSON alone.
4. Restored records are categorized strictly as historical (anchored or unanchored). Even if a caller presents the old source session/turn identifiers, restored records are never emitted as same-turn candidate evidence.
5. A local, live-session lookup may return **only a typed source claim** from a matching current-user-labeled turn. It does not verify that the caller correctly labeled its source. No claim of authenticated user identity, actual preference, live host provenance, effect authorization, consent or canonical memory follows.
6. Entries labeled as foreign persona, historical record or agent inference cannot masquerade as a fresh user correction. A source category is evidence metadata, not a trust credential.
7. Consent/commitment are proposition types to avoid *conflating* them with definitions or facts. Recording those words in a historic archive never grants permission or effect authority.

## TDD and real separate-process evidence

First red observation: `tests/test_social_revision_ledger.py` initially failed at collection with `ModuleNotFoundError: vera_core.social_revision_ledger`, exit 2. After implementing the module, 21 focused tests plus 3 subtests passed with exit 0 on Lappy Python 3.12.10.

Added `tests/test_social_revision_cross_process.py` with actual separate interpreter execution using throwaway fictional "nonbiological life" correction content. The child process reads a temporary synthetic JSON snapshot, validates its exact externally supplied head, reconstructs both corrections, and confirms that even matching prior session and turn cannot be projected as a present correction. Test also recomputes an entirely forged history; unanchored restore accepts it only as untrusted archive, anchored restore rejects it against the previous head. This is an adversarial demonstration of both usefulness and limits. The first attempt at this test failed because the test itself incorrectly constructed a typed entry from raw JSON enum strings; test fixture corrected without changing source semantics. Combined focused **23 passed, 3 subtests** exit 0.

No real conversations or private memory were persisted. The only JSON snapshots materialized in these tests are synthetic temporary fixture files deleted by the test harness. An actual memory owner would need to supply authenticated input, private storage, encryption, deletion policy, independently preserved head, and verified current-session clock/source before this becomes a runtime feature.

> Hostile challenge: If an attacker can create the events, choose the source kind, rewrite the whole hash chain and hand back a freshly self-consistent head, this ledger CANNOT distinguish that record from a real user correction. If an application treats `current_turn_evidence` as authenticated identity/consent, the integration would be unsafe. Keep this API advisory only until a separately authorized host binds exact user source, signed current turn and privacy policy.

## Release status and frontier

Draft PR source only; no merge, deploy, native Project control update, credential/permission change, persistent storage of user data, or live model qualification. Next: independent owned host source binding and a qualified opt-in consumer; multi-seed position-invariant social judgment evaluation; privacy-protected memory review, with Patrick's explicit authority for any canonical writes.

## Privacy gate and final verification

An explicit negative test first FAILED against the unrestricted `CorrectionLedger.snapshot()` interface (`PermissionError not raised`, pytest exit1). Corrected the API so raw text cannot be serialized by a default call: `snapshot()` and `snapshot(allow_sensitive_export=False)` raise `PermissionError`, and only `snapshot(allow_sensitive_export=True)` emits the source-only JSON. The flag prevents accidental export; it is **not** authenticated privacy permission or consent to publish actual user text. The synthetic cross-process test opts in deliberately and deletes its temporary files.

On Lappy Python 3.12.10, focused tests **24 passed plus 3 subtests** exit0. Optimized `-O` **24 passed, 3 subtests** (expected pytest assertion-mode warning), exit0; Python 3.14 **24 passed** (pytest-asyncio deprecation warning), exit0; compileall exit0.

Broad repo test history on this exact source checkout:
- Initial pre-privacy full suite after new ledger: **1083 passed, 104 skipped, 156 subtests passed**, one collection warning, exit0.
- After adding export opt-in, first broad run: **1083 passed, 104 skipped, 1 failure**, exit1, at an **unrelated** `tests/test_deep_memory_cli_transport.py::PinnedCLITest::test_slow_stdout_is_killed_at_deadline`. That test expects a new subprocess to create a PID file before a 0.2s timeout; observed missing file under broad-run load. No ledger module involved. The exact test then passed **three isolated separate reruns** without changing its source.
- Final exact post-privacy isolated-basetemp full rerun: **1084 passed, 104 skipped, 156 subtests passed**, one collection warning, exit0 (`py -3.12 -m pytest -q --tb=short --basetemp=D:\VERA\experiments\social-appraisal-privacy-recheck-20261114 tests`). These results do not establish a hosted CI check, independent reviewer, or behavioral qualification.

No real user text was used, captured or written. Source-only default-deny protection does not substitute for owner-bound host input, authorized storage/export, deletion and human approval of private or canonical effects.
