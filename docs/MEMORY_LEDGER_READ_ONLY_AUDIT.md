# Vera current memory ledger: bounded offline structural audit

Status: **SOURCE + SYNTHETIC TEST**, not host qualification, authentication,
authorized training, promotion, or currentness proof. This file describes the
current governed ledger only. It does not import historical exports.

The canonical API is `vera_memory.audit_current_memory_ledger`. It reconciles
the read-only verification objective of draft PRs #162, #165, #167 and #169
into **one** implementation. No alternate unbounded `audit.py` API is introduced.

```python
from vera_memory import audit_current_memory_ledger

result = audit_current_memory_ledger(
    "/path/to/quiescent-ledger.sqlite",
    project_id="your-project",
    identity_id="your-governed-identity",
    max_records=100_000,
    max_database_bytes=128 * 1024 * 1024,
)
```

Inputs must be a detached/quiescent, existing SQLite rollback-journal-mode
snapshot with no `-wal`, `-shm`, or `-journal` sidecars. A symlink in the
resolved path ancestry is refused; dangling symlink sidecar directory entries
are also refused. The reader uses SQLite `mode=ro` and
`immutable=1`, `PRAGMA query_only=ON`, bounded table queries and file-size
checks; it never initializes or mutates a ledger. The caller must ensure the
file is not being concurrently mutated. Path inspection is not an atomic
defense against a hostile filesystem actor replacing files during the read.

The audit checks:

- SQLite header and expected record/operation schema surfaces; metadata is
  bounded to exactly the current two keys (`generation`, `head`), rejecting
  unexpected extra keys;
- bounded record/operation counts and generation consistency;
- canonical record and receipt JSON, digests, request digest, and exact
  `AdmissionRequest` field **and semantic** validation;
- project/identity bindings, operation/receipt correspondences, supersession
  lineage, CAS generation and deterministic ledger head reconstruction.

The return value holds aggregate counts, the computed head and an explicitly
  limited evidence class. It does not include stored text, provenance refs,
  privacy refs, or individual record IDs.

## Claim ceiling

> A fully privileged writer can forge an internally consistent database,
> digests, receipts and head. Structural consistency therefore neither
> authenticates a writer nor proves the authority/privacy references true.
> `immutable=1` is safe only for a genuinely quiescent snapshot.

This API grants **no** historical promotion, policy authorization, runtime
activation, cross-system currentness, independent custody, model training
authority, or attestation. The returned head must be compared to a separately
protected previously witnessed head before any stronger continuity claim.

## Test evidence and remaining work

The synthetic `unittest` suite checks empty/valid admission, succession,
privacy of output, digest/receipt/head/binding corruption, hard limits,
symlinks, sidecars and WAL header, plus **three fully rehashed** forged
records (empty text, unknown memory class, duplicate provenance). These
three were intentionally red against the bounded-only baseline and green
after exact current `AdmissionRequest` semantic replay was added. Additional
hostile regressions reject extra metadata, dangling sidecar symlinks and deeply
nested invalid record/receipt JSON without leaking raw `RecursionError`.

SQLite's connection context manager commits/rolls back but does **not** close
the database handle. The current `MemoryLedger` now closes all four connection
lifecycles explicitly *after* their transaction context exits, and closes a
connection if setup fails before it can enter the caller's context; the synthetic
fixture writers also close their connections. Tracked-connection regressions
assert normal/exceptional ledger handles close, while a Windows-only test attempts to unlink
the completed audit file. The latter requires a Windows CI run; a Linux pass
cannot prove Win32 handle release behavior.

Still unqualified: Windows/OneDrive path behavior, concurrent malicious
filesystem writers, very large or adversarial SQLite database performance,
external head custody and independent production-host readback. Keep the
host/runtime gate **HOLD** until separately tested and authorized.
