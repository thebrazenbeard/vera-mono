# Mini-Vera public-memory host revision floor — source contract (2026-11-07)

**Status: source and synthetic-test evidence only. No production host issuer, durable-floor provider, or installation has been qualified.**

The V2 broker checked a host-provided `current_authority_revision()` twice and
remembered the largest revision within one Python broker instance. A new broker
forgot the observed maximum. A synthetic test reproduced that restart-shaped
rollback: a broker that had accepted revision 11 was discarded and a fresh
broker accepted revision 10 with the same grant, records and ledger head.

An independent hostile review also reproduced a **stale grant resurrection**:
the reader moved from authority revision 10 to 11, but the host grant callback
continued returning a previously issued revision-10 grant with the same epoch.
The old broker silently re-HMACed that stale grant under revision 11 and still
projected PUBLIC records. `PublicMemoryGrant` now requires an exact
`authority_revision` field, populated by the actual host issuer at issuance.
The broker rejects any mismatch against `current_authority_revision()`; merely
reading a newer revision cannot refresh the authorization decision.

`bind_host_public_memory` now additionally **requires** the trusted host callback
`atomic_host_revision_floor(revision: int) -> int`. It must atomically:

1. Read an authenticated, externally owned **durable** floor scoped to the
   exact project, identity and authorization issuer, separate from the model
   and mutable memory ledger.
2. Commit `max(previous_floor, revision)` before returning, with cross-process
   serialization and rollback-resistant storage.
3. Return the committed floor as an exact, non-boolean unsigned 64-bit integer.

The broker refuses any response other than the current authority revision.
A larger floor means a stale reader or rollback; a smaller floor means the host
failed its commit/attestation contract. An absent/throwing callback also fails
closed. Revocation/regrant must still advance the authority revision **at the
host issuer**. Neither client-supplied grant data nor a local file exposed to
the model is a valid implementation of this host authority.

The new callback and `PublicMemoryGrant.authority_revision` are mandatory,
intentionally breaking experimental V2 callers that do not have a host-owned
durable floor or grant issuance binding. The synthetic tests use both an
in-memory fixture and a disposable, transactionally updated SQLite fixture
with an entirely new connection on reopened state; they demonstrate only the
broker's enforcement of the callback contract. They do **not** demonstrate
hardware- or service-level protection against snapshot rollback, caller
impersonation, database substitution, or a host issuer that falsely reports a
commit. A host binding and separate real-system/hostile verification are still
required before any PUBLIC memory runtime can be called qualified. PRIVATE
memories remain inadmissible even with a valid grant and floor.
