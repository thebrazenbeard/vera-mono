# Mini-Vera host PUBLIC-memory authority gap — 2026-11-07

**Verdict: BLOCKED for an authenticated production memory broker.** The
Mini-Vera source implements a correctly bounded host callback *consumer*, but
the inspected sources and read-only Lappy paths do not establish an active,
independently authenticated provider of `PublicMemoryGrant`, external
MemoryLedger CAS/revision anchors, or source-by-source PUBLIC approval.
Do not fill that gap with hard-coded string checks, an unauthenticated JSON
grant, CLI flags, another ledger, a mutable SQLite metadata row, or a lease
for an unrelated operation.

## Exact evidence and inspection scope

| Subject | Exact source / read-only result | What it establishes |
|---|---|---|
| Vera Mono PR #201 | Live branch `codex/mini-vera-mitosis-integration-20261107` head `424b77b11fd46b8699f0f50372d579703454d93d` | `tools/mini_vera/host_memory_broker.py` consumes host-supplied callbacks; it does **not** define or authenticate a real host grant issuer. |
| Vera Mono reviewed-memory CLI | Same head, `packages/vera_core/src/vera_core/cli.py`, `_require_independent_review_attestation` | Production reviewed-memory path expressly fails closed until an independently authenticated action-bound review broker exists. |
| Vera Mono supervised feedback | Same head, `packages/vera_memory/src/vera_memory/supervised_feedback.py` | Ed25519 review journal requires `synthetic_fixture_mode=True`; production feedback disabled. It does not authorize Mini-Vera PUBLIC memory. |
| Vera Mono PC connection | Same head, `packages/vera_pc_connection/src/pc_connection/{envelopes,journal,artifacts}.py` | Scoped operation leases, authorization revisions and revocation fields exist, but allowed operations are PC host/file operations, not public-memory selection, privacy review or ledger-grant issuance. Do not reinterpret `READ_TEXT` as consent to model projection. |
| Chat Communication Bus | `thebrazenbeard/chat-communication-bus` main `eb315a5612ae99aadddb397891ffcf3a2b0433a6`, `src/radar/{registry,reconciliation_journal}.py` | Message/node leases and fencing exist, but were not found to authorize PUBLIC memory projection. |
| Standalone MemoryLedger repo | `thebrazenbeard/MemoryLedger` main `55b431b5257880f7b6636e5c6b3b7b9d3ec46792` | No implementation files in the checked-out branch. This is not an authority provider. |
| Lappy workspace-local memory runtime | Read source at `D:\VERA\memory_runtime\vera_memory\store.py` and `README.md` through WorkBridge Commander | Separate `MemoryStore` schema supports `read_only=True`, source provenance, consent/privacy filters and event history. It is **not** `vera_memory.MemoryLedger`, does not return Mini-Vera `PublicMemoryGrant`, and its `collaborator_shared` privacy class is not equivalent to an externally approved PUBLIC grant. |
| Lappy filesystem metadata only | `D:\VERA\.vera-memory\canonical.sqlite3` and `D:\VERA\mini-vera\mitosis-pr201` appeared in directory listing | Presence of a DB/source checkout only. The DB contents, private records, authentication secrets, and runtime continuity were **not** read, queried, or attested. |

Lappy inspection was limited to benign directory names and public/source-code
documentation. No memory database contents were inspected. No host process was
started, service restarted, provider enabled, authorization widened, key
retrieved, or model inference attempted. The WorkBridge Relay health endpoint
reported its own read/process/write flags disabled; the separate WorkBridge
Commander directory/source reads nevertheless returned normally. Neither
proves memory-grant runtime binding.

This is **bounded negative evidence**, not a claim that no undiscovered host
authorization provider can exist anywhere in Patrick's ecosystem.

## Minimum existing-host interface required to activate the seam

The chosen, already-authorized host authority must supply all of the
following, from outside model-controlled state:

1. `current_grant() -> PublicMemoryGrant | None`: each call consults live
   authority and returns exact project/identity, selected PUBLIC record IDs,
   independently anchored selected record SHA-256 digests, ledger head and
   revision, a host-monotonic approval
   epoch (incremented on revoke/regrant), and a bounded expiry. `None` means
   denied, stale, unavailable or revoked. The grant cannot be signed by the
   same untrusted ledger it claims to verify.
2. `approve_record(record, grant) -> bool`: host review of each current
   WORKING_PROJECT source, independent source/provenance/privacy authority and
   consent. A metadata value of `PUBLIC` alone must not return `True`.
3. An already-open approved `vera_memory.MemoryLedger` bound to correct
   project/identity, plus a host-held 32-byte integrity root secret. **No
   implicit conversion or import** from the separate Codex `MemoryStore`.
4. A protected anchor/epoch store that detects whole-ledger rollback and
   revocation across cold restarts. The host owns and rechecks it; Mini-Vera
   only consumes the resulting decisions.
5. Independent immutable Vera identity/behavior SHA-256 pins, qualified local
   model and host resource approval before invoking `local_session.main` with
   the separate `--execute` and `--host-idle-confirmed` arguments.
   A valid memory grant does not imply model identity attestation.

When these exist, the integration is the already-tested call
`bind_host_public_memory(ledger, integrity_key=..., current_grant=...,
current_authority_revision=..., atomic_host_revision_floor=...,
approve_record=...)`, injected into `local_session.main(...,
live_public_provider=provider)`; the local session rechecks before and after
inference. The source-only tests in PR #201 do **not** establish an installed
host reviewer, native autobiographical continuity, or private-memory access.

**Decision:** no new host adapter or approval service was fabricated in this
wave because no examined interface met these authority contracts. Preserve
the fail-closed source implementation until a real host owner can provide and
independently qualify the above controls.

**Subsequent source hardening (Wave8, no host qualification):** a synthetic
SQLite writer reproduced a rewrite of an admitted record's canonical payload
and row digest without advancing the ledger head. With a permissive synthetic
host callback, the earlier broker projected the new text using an unchanged
grant. The V3 source grant now requires immutable, ordered, externally issued
record-digest pins and refuses that rewrite. These synthetic tests do not
authenticate a real host issuer or prove anti-rollback custody.
