# Historical v0.2.3 memory-kernel recovery: read-only audit

Source artifact inspected locally (not copied into this repository):

- Filename: `VERA_CANONICAL_MEMORY_KERNEL_V0.2.3_VALIDATED.zip`
- SHA-256: `34d7904816afe5a460cb1ce7b524c2da6c56de48e5e778c3fb9106d427d8134b`
- Historical implementation: `vera_memory/store.py` event journal, projection versions, legacy migration metadata, and `audit_event_sourcing`.
- Current source baseline: `vera-mono` main `5be71f4c9171417f8d492db341a058a7072822ae`, `packages/vera_memory/src/vera_memory/ledger.py`.

The historical archive supplies *reference source*, not any eligible current memory or active runtime state. The current monorepo owns its independent governed CAS ledger; its data schema is not the old v0.2.3 SQLite schema. Installing or copying the old `MemoryStore` would create conflicting authority and duplicate storage.

The recovered, useful capability is a bounded, **read-only structural audit** for *offline copies* of historical v0.2.3 databases. It verifies expected tables and projection versions, event sequence continuity, event handler coverage, replayable memory payloads, relationship/source dependencies, and missing origin events. Only counts and finding types are returned. No source text, actor, subject ID, memory identifier, or payload is reported.

Run on a quiescent local archival SQLite file, **not a live writer**:

```powershell
py -3.12 -m vera_memory.legacy_kernel_audit 'D:\private\archived-v023.sqlite3'
```

The diagnostic requires a regular, non-symlinked file with a SQLite header and no `-wal`, `-shm` or `-journal` sidecar, refuses incompatible schemas and oversized files, opens SQLite with `mode=ro&immutable=1`, sets `query_only` and `trusted_schema=OFF`, checks bounded table sizes and strict JSON. It runs no archived Python code, executes no writes, and does not copy record content into the current ledger.

**Interpretation:** a clean report is only structural compatibility evidence. An old export might still be malicious, truncated, outdated, conflicting, unauthenticated or private. This tool does *not* perform migration, memory admission, consent, currentness, runtime activation, model training, or historical-story publication.

Follow-up: identify a historical database whose schema actually matches the source artifact, audit it locally, and map actionable anomalies to a separate owner-reviewed migration. A private ChatGPT archive and its historical SQLite files cannot be published or promoted merely because they appear in Downloads.
