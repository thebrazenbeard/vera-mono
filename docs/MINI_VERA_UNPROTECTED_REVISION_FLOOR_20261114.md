# Mini-Vera unprotected SQLite revision floor — 2026-11-14

Status: SOURCE CANDIDATE and synthetic test utility, not an installed or
independently authorized host currentness backend. The module creates no
real-memory approvals or signing credentials.

## Motivation and exact role

The existing tools/mini_vera/host_memory_broker.py requires an
atomic_host_revision_floor callback and an independently maintained
current_authority_revision reader. Prior tests supplied an in-memory
floor callback or an inline test-created SQLite implementation. This
change creates a reusable, executable SQLite revision-floor callback,
UnprotectedRevisionFloor(path).advance(revision), for *test and isolated
candidate* execution. It is not a substitute for a protected host
revision source or grant issuer.

The revision floor stores the maximum observed 0..2^64-1 unsigned
authority revision in a single SQLite row encoded as sixteen lowercase
hexadecimal digits. A BEGIN IMMEDIATE transaction serializes competing
writers. SQLite synchronous=FULL, journal_mode=DELETE, PRAGMA quick_check,
strict table schema and post-commit readback help prevent ordinary
crashes, corruption and SQL-shape mistakes from silently being mistaken
for healthy current state.

The operator supplies an absolute path ending .sqlite, in an existing
directory outside the source checkout. The module rejects symlink and
Windows reparse components, an oversized/nonregular file, a corrupt
database and an unexpected table schema. A zero-byte file can be accepted
during concurrent SQLite initialization; it can also be recreated by
an attacker who controls the file. There is no protected OS principal,
no independently anchored signature or external rollback witness.

## Hostile and functional evidence

Tests use a disposable test directory with no real project records.

- Reopen the SQLite floor through a fresh Python instance, retaining
  the highest previously committed revision.
- Persist the full uint64 range, including values larger than SQLite's
  signed integer range, without precision loss.
- Race six actual independent Python child processes against the same
  file; the committed maximum must be 24.
- Refuse boolean/negative/fractional/out-of-range revisions, invalid
  paths, symlinks, corrupt and wrong-schema databases.
- Integrate the floor as the existing host_memory_broker's
  atomic_host_revision_floor callback; a fresh broker must reject a
  stale authority revision after the external floor has reached 11.
- Demonstrate the remaining counterexample: a same-user replacement of
  the SQLite file with a previously copied database resets the apparent
  highest revision from 8 back to 5. This is EXPECTED, explicit failure
  of rollback protection. The test passes by showing the vulnerability.

## Trust ceiling

This file-backed floor satisfies the BROKER API's atomic concurrency
and ordinary process-restart persistence properties in source tests.
It does **not** qualify the broker's stated external-host security
requirements. An attacker who controls the same OS user account, file
and callback can replace/erase the database, reissue grant material or
report a fabricated revision. A test success is not proof of protected
host custody, real runtime currentness or source-authentic memory.

Use only synthetic PUBLIC fixtures until a separate trusted principal,
external revision source, protected atomic store and independently
attested host issuance/revocation have been qualified and read back.
The source-only portable bundle intentionally contains no SQLite
database, private data, model weights, user keys or host permissions.

No deployment, shared service restart, real user-memory access,
production credential provisioning or protected merge is performed.
