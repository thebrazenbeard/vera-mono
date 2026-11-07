# Mini-Vera host-owned public-memory broker — source candidate

Status: **SOURCE + UNIT TEST ONLY.** No Lappy installation, independent
authorization service, true host grant, private-memory enablement, model call,
or independent currentness witness has been established by this change.

`tools/mini_vera/host_memory_broker.py` binds an existing host-owned
`MemoryLedger` and its current authenticated policy to the real
`local_session.main(..., live_public_provider=...)` integration introduced by
PR #201. It is a narrow Python API, **not** a new memory store or a CLI flag
that lets a model or operator self-approve private data.

## Live host contract

The embedding trusted host supplies:

1. An **existing** `MemoryLedger` object with the expected project and identity.
   Constructing it or applying DB migrations is the host's responsibility,
   outside this broker; the broker never calls `admit()` or mutates the ledger.
2. A 32-byte host-held root integrity key, never the model's choice.
3. `current_grant()`, an authenticated host-controlled callback called **twice
   per projection**. It returns `PublicMemoryGrant`, or `None` if unavailable,
   denied or revoked. The grant includes exact project/identity, externally
   anchored ledger CAS head and revision, explicit record IDs, monotonically
   advancing approval epoch, and a maximum one-hour absolute expiry. The host
   MUST increment its epoch on **each** policy change, including a revoke and
   regrant with otherwise identical records.
   The broker requires exact primitive field types and an immutable tuple of
   bounded, unique record IDs; a frozen dataclass containing a mutable list is
   rejected. Grant canonical bytes are compared across both reads, even if a
   callback returns and mutates the same Python object.
4. `approve_record(record, grant)`, an independent host policy decision for
   each selected record, covering authorized source, provenance, privacy,
   project/identity and currentness. `PUBLIC` in SQLite metadata alone is not
   approval. Every selected record is necessarily `CURRENT`, `WORKING_PROJECT`,
   `PUBLIC`, source-backed and bounded even when the host callback errs.

The API is intended to be called from a host-owned Python entrypoint:

```python
from tools.mini_vera import local_session
from tools.mini_vera.host_memory_broker import bind_host_public_memory

# All four inputs come from independently authenticated, already-configured
# host services, NOT from a prompt, model-supplied JSON or command line:
# ledger, host_root_integrity_key, host_current_grant, host_record_approval
provider = bind_host_public_memory(
    ledger,
    integrity_key=host_root_integrity_key,
    current_grant=host_current_grant,
    approve_record=host_record_approval,
)
raise SystemExit(local_session.main(argv, live_public_provider=provider))
```

The names above are **integration inputs**, not defined runtime variables or
an installed launcher. A real host implementation must supply them and keep
the independent authoritative head/revision/epoch outside the editable ledger.

The broker derives a fresh state-HMAC key from the host root key and exact
grant (including approval epoch). Thus an intervening revocation and regrant
under a new epoch changes the state's signed bytes even if the public text is
identical. The existing session performs its provider check after the model
response and **withholds** output if the approved state's digest changed.
Revocation cannot retract a prompt already sent to the local server; neither
this broker nor `local_session` controls plugins inside an operator-run server.

## Explicit nonclaims and limits

- The broker verifies the *shape and consistency* of a host decision. It does
  not prove that the callback actually comes from the authenticated host.
- It does not validate identity/behavior source pins. The integrated
  `local_session` has reviewed code-anchored SHA-256 expectations for both
  resources, but a host must independently attest the installed program;
  code-local pins are not a signed executable or identity-transfer proof.
- The root integrity key and grant epoch are host-owned. If a hostile host
  supplies forged approvals or reuses an epoch after revocation, the broker
  cannot manufacture authority from those untrusted inputs.
- Exported memories are data, not instructions; no private or autobiographical
  memory is activated. Conversation history stays process-local and volatile.
- Ledger CAS alone does not prove immutable history against whole-DB rollback.
  The host must retain its independent head/revision witness.
- A test-only SQLite ledger and localhost fake model cannot establish actual
  Lappy installation, good conversational quality or live currentness.

## Source verification

```shell
python -m unittest tests.test_mini_vera_host_memory_broker -v
python -O -m unittest tests.test_mini_vera_host_memory_broker -q
python -m unittest discover -s tests -p 'test_mini_vera_*.py' -q
```

Tests intentionally use synthetic grants and an in-process mock loopback.
They cover public export, host denial, explicit revocation, expiration, scope,
stale head, private record exclusion, mid-projection policy changes, cold
SQLite reopen and post-inference output withholding on reauthorization epoch.
