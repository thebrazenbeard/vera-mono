# Mini-Vera host-owned MemoryStore read adapter — source candidate

Status: **SOURCE + SYNTHETIC INTEGRATION TESTS ONLY.** This is not a trusted
PUBLIC authorization issuer, a newly installed memory service, or proof that
the current Lappy memory database contains any PUBLIC-project record.

## Purpose and exact source

The host's `D:\VERA\memory_runtime\vera_memory\store.py` source inspected
on 2026-11-07 reported `RUNTIME_VERSION = "0.4.0"`. Its existing `MemoryStore`
supports `read_only=True`, a `get_memory(memory_id)` method and an append-only
`events` table whose latest `event_hash` can serve as a **locally observed**
snapshot head. This is a different schema/API from Vera Mono's
`vera_memory.MemoryLedger`; the two databases cannot be interchanged.

`tools/mini_vera/memory_store_adapter.py` implements the narrow
`ReadOnlyMemoryStoreAsLedger` compatibility surface needed by the already
existing `bind_host_public_memory` and `local_session.main` modules. It reads
only (1) `PRAGMA query_only`, (2) the latest event head, and (3) **explicit
host-preapproved** memory IDs through `MemoryStore.get_memory`. It never
creates, migrates, admits, promotes, edits or searches memory records. It
rejects a writable store and does not use `MemoryStore.recall` because that
could scan unrelated memories.

The adapter performs necessary source checks *in addition to*, not instead of,
host authorization:

- Literal `privacy_scope == "PUBLIC"`. The existing store default
  `collaborator_shared` is **not** automatically reclassified as PUBLIC.
- Exact project scope, host-selected branch **and subject ID**, `granted` consent,
  `endorsed_current`/`active` lifecycle, `data_only` instruction status,
  no risk flags and a limited project-record class.
- Bounded text, source-text SHA-256 equality, source ID/locator, revision,
  and validity-window checks.
- Local event-head CAS before/after each read. The **independent host** must
  anchor that head and issue a revision; an editable database cannot attest
  itself or detect a whole-database rollback to an old matching head.

The host must provide **three separate authorizations**: a fresh epoch-bound
`PublicMemoryGrant` via `current_grant`, `allow_public_id` to approve an exact
ID **before reading the row**, and `approve_record` to verify the actual
project/source/content/privacy after reading it. It must additionally supply
the broker's separately authenticated `current_authority_revision` reader and
`atomic_host_revision_floor` commit callback, both bound to the same issuer,
project and identity. Any denial, rollback or revocation prevents context
projection. `bind_host_public_memory` rechecks the grant around projection;
the grant must contain exact externally pinned selected-record digests,
including each MemoryStore adapter descriptor's source locator, text hash,
revision and anchored event head. A changed text with a matching locally
recomputed `content_hash` but unchanged event head now fails closed against
the previously issued digest; a stored hash is not its own authorization.
`local_session.main` rechecks after model output.

## Embedding seam (not an installed launcher)

```python
from memory_runtime.vera_memory.store import MemoryStore
from tools.mini_vera.host_memory_broker import bind_host_public_memory
from tools.mini_vera.memory_store_adapter import ReadOnlyMemoryStoreAsLedger
from tools.mini_vera.local_session import main

# Host authority must independently provide these values/functions.
# Do not pass model-generated grants, arbitrary CLI assertions or a public
# label in the editable store as proof of consent/currentness.
with MemoryStore(host_approved_store_path, read_only=True) as store:
    ledger_view = ReadOnlyMemoryStoreAsLedger(
        store, project_id=host_project_id, identity_id=host_identity_id,
        branch_id=host_approved_branch, subject_id=host_approved_subject,
        allow_public_id=host_approve_public_id,
    )
    provider = bind_host_public_memory(
        ledger_view, integrity_key=host_integrity_key,
        current_grant=host_current_grant,
        current_authority_revision=host_current_authority_revision,
        atomic_host_revision_floor=host_atomic_revision_floor,
        approve_record=host_approve_exact_source,
    )
    raise SystemExit(main(host_verified_cli_args, live_public_provider=provider))
```

The `host_*` names are **not installed variables, services, or credentials**.
A constant-revision lambda or a mutable JSON/SQLite row under model control
does not meet the independent authority/rollback floor contract.
A real trusted host implementation must supply them, independently pin Vera
identity/behavior, qualify the model server and host resources, and establish
source rights and PUBLIC consent before any real call.

`MemoryStore` 0.4.0's actual `get_memory()` row contains `branch_id`, `scope`,
`subject_id` and `source_locator`, but **does not contain `project_id`** in the
present sources/memories schema. The adapter therefore rejects an absent or
wrong subject and rejects a conflicting/empty **explicit** `project_id` if a
future host export adds that field. It cannot manufacture a verified project
identity from those fields. The host's separate per-ID and per-record policy
must independently bind each selected source to the intended project; otherwise
no production authorization is established.

## Hard failure boundary: host authorization ABA

> A transient revocation *during* model inference followed by reissuing the
> exact same epoch-1 grant before post-inference checking is not observable by
> the consumer: it sees identical before/after grants. The source broker
> cannot manufacture a durable approval history. An external rollback-resistant
> host epoch/lease authority must advance its epoch on **every** revocation or
> policy change, including revoke/regrant, and must not restore old epochs.

Tests demonstrate withholding when the host does advance the epoch. They do
**not** claim to solve malicious or broken host grant issuance. A timestamp,
HMAC over caller-selected records, or stored PUBLIC label is not a substitute
for independent review or epoch custody.

## Tests and evidence limit

```shell
python -m unittest tests.test_mini_vera_memory_store_adapter -v
python -O -m unittest tests.test_mini_vera_memory_store_adapter -q
python -m unittest discover -s tests -p 'test_mini_vera_*.py' -q
```

Tests use a **synthetic** local SQLite `events` table and an in-memory fake of
the real `MemoryStore.read_only` / `conn` / `get_memory` API. They verify
explicit approved-ID reads, source filtering, privacy and consent denials,
read-only gates, external head mismatch, cold SQLite reopen, grant revocation
and post-inference output withholding using a fake loopback server. No real
Lappy memory database, private record, service or credential was opened.

The actual installed `MemoryStore` and host policy callbacks still require a
qualified Lappy runtime test *after* a legitimate PUBLIC authorization issuer
and independently protected CAS/epoch anchor exist. Source compatibility is
not production memory continuity.
