# Historical memory recovery: read-only structural audit

**Source comparison:** the local historical `VERA_CANONICAL_MEMORY_KERNEL_V0.2.3_VALIDATED.zip` has a `MemoryStore` API containing event-journal audit and projection-rebuild operations. Current `vera-mono` is a distinct `MemoryLedger` implementation with canonical records, admission receipts, compare-and-swap heads, and successor verification. The archived source remains local/private. This change is **originally implemented against the current schema**, not a wholesale transplant or a replay of historical memory.

`vera_memory.audit.audit_memory_ledger(path, project_id=..., identity_id=...)` opens an existing SQLite ledger in **read-only mode**, takes an explicit read transaction, and checks the full locally stored admission chain. It validates canonical record hashes; source project and identity labels; one-successor lineage; current/superseded flags; each operation's record, request and policy-reference bindings; receipt canonical JSON and exact field sets; chronology rebuilt from validated receipt generations rather than mutable SQLite rowids; recomputed admission heads; and final metadata. It refuses missing databases instead of creating them.

A successful result has `status=CONSISTENT_LOCAL_STRUCTURE_ONLY`, `authorization_effect=NONE`, and `claim_ceiling=INTERNAL_STRUCTURE_ONLY_NOT_PROVENANCE_OR_AUTHORITY`. It does **not** establish the truth or rights of a memory, currentness, qualified owner consent, independent provenance, protection against a malicious SQLite owner who can rewrite all records, or historical event-journal reconstruction. No memory is admitted, revised, imported, exported, promoted, projected, or connected to a live runtime.

## Focused regression

Run with the repo's existing test dependencies and the required package paths:

```bash
python -m pytest -q tests/test_memory_ledger_recovery_audit.py tests/test_memory_ledger.py
```

The tests cover empty and revised ledgers, unrelated corrupted record data, mutable successor-status forgery, missing and corrupt operation receipts, forged receipt privacy references, forged extra authority fields, changed SQLite rowids, duplicate receipt generations, tampered metadata head, and missing-path refusal. The receipt privacy-reference case was **observed failing before its guard was implemented**. At the Lappy Windows Python 3.12 checkpoint, 19 focused and existing ledger tests passed. The changed-rowid test was observed failing before the ordering correction, then passed after the repair. These are TEST evidence, not a runtime installation or a formal security proof.

## Next recovery gate

For the legacy ZIP, keep original archive SHA-256 and member digests in private custody, compare feature semantics and data schema against current source, run the archive's original tests in an isolated sandbox if rights/permissions allow, and migrate only reviewed capabilities with new tests. Do not import private memories or publish personal archive contents. Any protected memory admission remains governed by its existing authority boundary.

> Hostile limitation: a self-consistent, maliciously rewritten SQLite file can pass this audit because the head has no external trusted anchor. The function is a local structural diagnostic, **not an integrity attestation against a fully compromised disk**.
