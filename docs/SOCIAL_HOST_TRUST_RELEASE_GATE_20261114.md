# Vera social host trust boundary — live Lappy evidence and release gates
Date: 2026-11-14. Scope: thebrazenbeard/vera-mono Draft PR #214, relational-agency worker only. No native release authority claimed.

## Executed evidence

I checked the actual Windows host read-only through Executor Lappy Dedicated, not a file export or historical report.

- Current tool execution is under a normal local Windows interactive user token; token's Administrators group is deny-only (not elevated).
- The original PR #214 checkout and its parent directory inherit an **Allow Modify** access rule for **Authenticated Users**. A checkpoint stored in that location is **not** independently protected against the same model/tool path.
- Other Vera-named Windows services exist under LocalSystem, and a Vera Mono pilot service is configured under LocalService but is **not running**. No read-only evidence established that those services issue authenticated user-correction signatures, own PR214, hold a protected checkpoint, or observe native ChatGPT user-source events. Existence is not authority.
- A new read-only native Windows probe, scripts/probe_social_host_boundary.ps1, reported `candidate_broad_write_grant=true`, `candidate_parent_broad_write_grant=true`, `current_process_admin_token=false`, `reference_service_state=NOT_RUNNING`, and all three of `user_authentication_verified`, `independent_checkpoint_verified`, and `issuer_credential_custody_verified` **false**. Status: `production_qualified=false`. The report deliberately contains no private key, token, SID, username or full path and is **not** an OS-backed identity certificate.
- This tool did not modify any ACL, Windows service, registry key, credential store, native ChatGPT Project installation or canonical user memory.

## New cryptographic checkpoint contract

Source: packages/vera_core/src/vera_core/social_checkpoint_witness.py
Tests: tests/test_social_checkpoint_witness.py and tests/test_social_correction_replay_fence.py

- Synthetic Ed25519-signed checkpoint binds issuer/key, installation, exact source session, 40-hex release commit, correction issuer key fingerprint, candidate count, local fence head, predecessor checkpoint digest, and required monotonic epoch. Domain separated; no raw correction text.
- TrustedCheckpointVerifier validates the signature under a **supplied** public key with exact expected scope and epoch. Its receipt recomputes signature verification rather than accepting a caller-supplied boolean. It deliberately reports `independent_host_custody_verified=false`, `actual_user_source_verified=false`, `canonical_memory_admitted=false`, and `external_effect_authorized=false`.
- `reopen_synthetic_fence_from_signed_checkpoint` verifies this checkpoint's signature and exact session/release/issuer/epoch/previous digest first, then opens existing SQLite in synthetic mode with the signed fence head and checks row count. Signed data cannot attest to a different snapshot without new host-key signing. Caller-selected trust keys and old epochs **still do not establish actual host authority or anti-rollback**.

## TDD and tests

1. Missing Windows probe source failed two real-process tests as intended, exit1; after implementation, 3 passed exit0, plus actual native read-only probe exit0 with the negative host conditions above.
2. New checkpoint verifier module initially failed collection (ModuleNotFoundError, exit2). Implemented exact canonical format and tests: 7 tests +30 subtests passed Python3.12.
3. Integration test for reopening SQLite through a signed checkpoint initially failed (ImportError, exit1). Added the explicit synthetic reopen adapter. Combined checkpoint+replay-fence+host-readiness focused tests: **22 passed, 35 subtests**, exit0, Lappy Python3.12. This is not a native host test of key custody; the signing keys were generated in test memory only.
4. An old signed checkpoint is deliberately shown valid again when the caller also submits the old expected monotonic epoch. It is rejected against a later independently supplied epoch. This is why the external epoch/counter must be **held outside the model/SQLite process and refreshed from its actual authorized owner**, not copied from the signed JSON itself.

> Hostile finding: A perfectly valid signature under a user-supplied public key plus a self-reported epoch is **not** independent host authentication. The local SQLite file and its parent are presently broadly writable; model/tool code can tamper with them. Neither static code review nor successful tests can certify the current host as a signer or prove native user input. Promoting this candidate now would be a real trust-boundary error.

## What must be established outside this source branch

**Release owner and exact target:** Patrick's target-specific authority for creating/starting a dedicated host process, its Windows service SID, protected directory ACL, credential generation/key rotation, and checkpoint store. Do not commandeer a service whose release ownership is unknown.

**Host protections:** Dedicated least-privileged host principal, key material unavailable to ordinary model/tool principal, protected checkpoint journal + monotonically advanced counter with transactional CAS, power-loss restart/readback, verifiable no-read/no-write probe from unprivileged process, and protection against file substitution across native handles. A host should use OS-backed credentials or provider keys with actual independent custody, not store an unencrypted private key in D:\VERA.

**Current user source:** The privileged signer must observe the actual authenticated user turn at the native host/platform trust boundary and bind exact bytes, actor identity, session/turn and source. Text supplied to a model/tool by a caller or an imported JSON record cannot become a genuine user-origin witness by relabeling or signing itself.

**Behavior:** Continue independent model/human multi-seed position-invariant evaluation. Previous local judge was falsified by swapped A/B labels; do not promote a winner based on those invalid preferences.

**Before production:** An independent release owner must verify exact native interface/control binding, host key custody, checkpoint owner, actual private storage admission/privacy, and real runtime consumer. The next release must carry explicit Patrick authorization for credential/permission/service and canonical effects. Until that happens, this PR is a source-only Draft and every production admission/effect remains denied.

## Final tests and external checkpoint discovery (2026-11-14)

Read-only connected Supabase list_projects returned a Vera project in active/healthy state, but the first read-only list_tables(public) attempt failed with server-side PostgreSQL 28P01 password authentication for the connector read-only role. No table/schema/content was inspected or changed, no retries or credential repair were attempted. This is NOT evidence that a qualified off-host checkpoint exists.

The first Lappy Python3.12 repo-wide run after this change had 1126 passed, 104 skipped, 233 subtests passed and one existing unrelated DeepMemory CLI 0.2-second PID-file timing failure, exit1. The exact failing test then passed three standalone runs, exit0 each. A subsequent full repo-wide isolated basetemp run returned **1127 passed, 104 skipped, 233 subtests passed, one pre-existing collection warning, exit0** in 118.50s, with no source edits between runs. Command:
py -3.12 -m pytest -q --tb=short --basetemp=D:\VERA\experiments\social-host-trust-full-recheck-20261114 tests

Focused host-boundary, signed checkpoint and replay-fence tests: **22 passed, 35 subtests passed** under Python3.12 normal and Python3.12 -O (one expected pytest assert optimization warning), and 22 passed under Python3.14 (pytest-asyncio deprecation warning); compileall and git diff --check exit0. All checked on Lappy. No hosted CI result, independent reviewer, live host key or native runtime consumer is claimed.

The next operational step is NOT to invent a signer by setting synthetic_fixture_mode=True. It is a target-specific release-owner decision and privileged host installation with ACL/key/checkpoint custody and native current-user input binding, after which independent adversarial host probes can establish or reject the actual security boundary. This PR remains source-only.
