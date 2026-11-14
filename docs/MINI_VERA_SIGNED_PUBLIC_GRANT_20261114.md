# Mini-Vera pinned Ed25519 PUBLIC-memory grant verifier — 2026-11-14

Status: opt-in source-only candidate. No production issuer, protected signing
key, independent host principal, or private user-memory access is installed.

## Objective and integration

The Mini-Vera repository previously contained an Ed25519 verifier for fixed
read-only host source observations and a separate in-process host-memory
broker expecting PublicMemoryGrant values. There was no dedicated
cryptographic verifier for those public-memory grants. This candidate
adds tools/mini_vera/signed_public_grant.py with one small, read-only API:

    reader = PinnedSignedPublicGrantReader(
        trusted_public_key=operator_supplied_public_bytes,
        expected_public_key_sha256=operator_independently_pinned_sha,
        expected_issuer_id="synthetic-issuer-A",
        expected_project_id="vera-mono",
        expected_identity_id="vera",
        now_seconds=host_trusted_clock,
    )
    grant = reader.verify(signed_grant_bytes)

A successful result is the existing frozen PublicMemoryGrant type. The
verifier does not store, create, manage, rotate or obtain private keys,
does not read any memory ledger, does not edit model weights or call
host tools. Its inputs are caller-supplied. The public key and SHA-256
pin MUST originate independently of the purported grant. The sample
above is illustrative only; it does not install an issuer or assert
such independence exists.

It checks strict duplicate-free JSON, bounded envelope size, exact
payload/schema, Ed25519 over canonical sorted-key JSON bytes, exact
issuer/project/identity scope, allowed synthetic record count/IDs and
SHA-256 digests, uint64 authority epoch/revision, ledger head, time
(issued within 120 seconds prior, at most 5 seconds future; expiry
within 30 minutes), and optional cryptography availability. It
produces tuple-based immutable record selections for the existing broker.

A host may supply reader.verify(packet) to the existing
bind_host_public_memory(current_grant=...) callback. That broker STILL
requires a separate externally issued authority revision reader,
durable revision floor, record-level approval policy and ledger.
The signed grant cannot authorize a record by itself, nor bypass the
broker's head/digest/revision checks.

## Red/green, positive tests and falsifiers

TDD RED: this verifier module did not exist. After implementation the
focused tests use a disposable private Ed25519 key only inside a test
or separate, short-lived signing Python subprocess; only its public
key and signature reach the reader. Positive test returns exact
PublicMemoryGrant with frozen record ID/digest tuples, and actual
synthetic MemoryLedger + host-memory-broker integration works.

Negative tests reject tampering with record selection, digest, scope,
grant epoch/revision, issuer, public-key pin, independent signer,
duplicates, unknown fields, boolean revisions, stale/future/expired
grants and key mismatch. With an independent revision floor at 11,
an older signed grant for revision 10 cannot be replayed by a fresh
broker, even while its original signature is valid. A new independent
authority revision also requires fresh signed grant material.

**Critical remaining attacker counterexample:**

A same-user attacker who generates a different signing key and
changes BOTH the signed grant AND the caller's trusted public-key/pin
can successfully pass signature checks. The test deliberately
demonstrates this. Valid cryptography authenticates a pinned key's
bytes, NOT the real host's identity, issuer key custody, a PUBLIC
record's truth, or an unforgeable grant. The unprotected SQLite floor
from PR217 can also be replaced/rolled back by the same user.

No claim is made that any independent issuer is installed. There
are no trusted Windows ACL/OS-principal probes, TPM attestation,
protected key creation, host-grant rotation, or persistent signing
service in this work. A production authorization gate requires a
separately provisioned, protected issuer and independently stored pin,
read-only record custody, protected authority revisions, authentic
revocation and readback, and tests across principal boundaries.

## Effect constraints

Only source and synthetic tests are changed. No user/private memory,
credentials, real host access permissions, shared-service process,
model weights, paid compute, deployment or protected-branch merge
is touched. A passing regression is SOURCE/TEST evidence, not live
qualification of the external issuer or of neural behavior.
