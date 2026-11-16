# Mini-Vera: PUBLIC source-attribution snapshot race

Status: **SOURCE PATCH / TESTED SIMULATED RACE ONLY**. No qualified external host issuer or human-private memory.

Parent: thebrazenbeard/vera-mono draft PR #246, exact commit e3ee4e3c50b193452f74e75ec8291d0a97fed99f. Related neural prompt-format falsifiers: issue #247.

## Literal defect

The source-only host_exact_reader.read_public_record verifies a host-supplied mutable state and compares two HMAC-bound snapshots. Previously, after the last equality checks it read after_state["source_id"] from the host-owned dictionary rather than from either of the checked immutable snapshots. A hostile or concurrent host-owned mutation at that boundary could return a source attribution that did not match the reported state_sha256. The referenced text itself came from parsed verified records; **the falsifier is specifically the source-identity label**.

A related window existed between compose.verify_state(state) and a second serialization of the same mutable dictionary. Two reads could both produce identical post-verification but non-verified serializations, with a state hash corresponding to earlier content. Matching two mutable reads is not proof that either was the verified object.

## Reproducible test evidence

1. HostExactReaderTests.test_source_identifier_cannot_change_after_verified_snapshot captures a real synthetic SQLite PUBLIC broker projection, mutates its source ID during the final equality check using a deterministic test hook, and asserts the returned metadata remains bound to the verified state. **RED:** exit 1, expected ledger source ID but received forged-public-source-attribution. **GREEN:** exit 0 after the fix.
2. HostExactReaderTests.test_refuses_state_mutation_between_verification_and_snapshot_copy restores the same synthetic state before each verification and changes it during each subsequent serialization. Without the hash-match guard, the method returned SOURCE_READ (not refused). **RED:** exit 1 (HostSourceRefused not raised). Restored guard **GREEN:** exit 0.
3. Host reader, wrapper, allowlist and broker targeted suites: **63 tests PASS** on VN1 after the change. Full Mini-Vera test suite and Lappy cross-host targeted test are separate verification steps and are not promoted here.

These are controlled **internal Python race simulations**. No claim of independently induced physical concurrency, qualified host authority, general memory, model reasoning, or real user-private access follows.

## Minimum patch

- Rehash the immutable compose.canonical(state) snapshot and require equality with the hash returned by verify_state.
- Parse the source identifier from that **immutable byte snapshot** for the outward source citation. Never source it from after_state after equality checks.
- Keep the prior two approval/provider reads, exact-ID matching, digest/policy/revision comparisons, sanitized refusals, zero neural HTTP calls and unchanged host grant issuer separation.

## Residual challenge

> A host with full control over the issuer, signing key and revision floor can manufacture an internally consistent approval. This patch cannot attest that host or prevent changes after source release. It only closes the tested mutable-object attribution discrepancy and a specific verification-to-serialization race. Independent host identity, durable rollback protection, trusted grant custody, and externally held-out semantic/model testing remain separate gates.

No inference prompt, weights, launcher, host service, ACL, signer, memory admission or private record is changed by this source patch.