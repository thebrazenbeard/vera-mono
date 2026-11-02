# Recovered hardening: read-only audit of the current memory ledger

**Source comparison (2026-11-02):** Patrick's local archive
`VERA_CANONICAL_MEMORY_KERNEL_V0.2.3_VALIDATED.zip`, SHA-256
`34d7904816afe5a460cb1ce7b524c2da6c56de48e5e778c3fb9106d427d8134b`.
Archived `vera_memory/store.py` supplied the *historical design requirement*:
`audit_event_sourcing` reported unmatched events, incomplete projections,
migration failures and orphaned lineage. It was an older, different SQLite
schema. **No archive source, memory contents, database, or old authority
instructions have been installed or admitted.**

The current `vera-mono` `MemoryLedger` instead stores governed admission
records, operation receipts, mutable supersession state, and generation/CAS
heads. It already verifies individual record digests and successor lineage
on read. It did not have an equivalent read-only whole-store consistency
check. This contribution adapts the useful historical *audit principle*
to today's exact schemas and semantics; it does not recreate the old store.

## New usable capability

`audit_current_memory_ledger(path, project_id=..., identity_id=...)` from
`vera_memory` opens an **existing** SQLite file read-only and, within one
snapshot, verifies:

- Every canonical record payload against its stored digest and originating
  request digest, expected project/identity, and exact current schema.
- Every canonical operation receipt against its associated record and
  bound privacy, authority and provenance references.
- A one-to-one, contiguous sequence of admitted generations. Recomputes
  the entire admission-head hash chain from the genesis state and checks
  each receipt's intermediate head and the final meta head.
- All stored supersession references, predecessor ordering, and mutable
  CURRENT/SUPERSEDED column state.
- Bounded record and database sizes; rejects missing files, symlink paths,
  WAL-mode headers, and SQLite `-wal`/`-shm`/`-journal` sidecars. No hidden
  migrations, writes or fallback initialization. The auditor uses an immutable
  read-only connection to prevent SQLite from creating sidecar files.

Returns only `ok`, counts, generation, the local head digest, and a
bounded evidence class. Memory text and raw provenance references are
**never included in the report**. On corruption, raises
`CurrentMemoryAuditError` without the record text or private values.

Example on an explicitly authorized **quiescent, offline copy** of an
existing local ledger (rollback-journal format, with no active sidecars):

```python
from vera_memory import audit_current_memory_ledger

result = audit_current_memory_ledger(
    "/path/to/existing-ledger.sqlite",
    project_id="vera-mono",
    identity_id="vera",
)
assert result["ok"]
```

## Claims and boundary

This verifies **self-consistency inside one detached offline database snapshot**, not
external authenticity, writer identity, canonical-memory admission,
historical migration, or continuity of experience. A writer with full
database access can replace rows, receipts, metadata and hashes together.
A separately protected monotonic reference is required to detect such a
coordinated replacement. An empty ledger has no per-record identity evidence.
Historical sources never acquire authority because they inspired the check.

The local test suite uses synthetic private-looking text and adversarial
mutations; no exported conversation or real memory content is committed.
No changes are made to the original Downloads archive or live memory DB.
