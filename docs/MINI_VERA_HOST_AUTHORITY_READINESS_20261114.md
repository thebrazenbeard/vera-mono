# Mini-Vera host-authority readiness probe — 2026-11-14

**Status: source candidate and read-only REAL Lappy negative probe.**
This does NOT establish a trusted issuer, key custody, host revision authority,
production memory access, host attestation, or qualified live Mini-Vera.

## What this executable does

`python -B -m tools.mini_vera.host_authority_preflight --read-only-windows`
runs exactly one fixed, non-interactive PowerShell read-only query. It checks
the current Windows token's administrator membership, whether Ollama model
processes appear to share the caller principal, and whether three explicitly
configured potential issuer/broker service names are present and running:
`MiniVeraIssuer`, `VeraIssuer`, `VeraHostBroker`.

The query outputs no account names, SIDs, service command lines, file paths,
key bytes, sensitive records, or credentials. It never creates an account,
creates a service, accesses a signing key, modifies ACLs, takes ownership,
starts/restarts software, or writes to the operating system. The Python API
validates the exact JSON shape with strict boolean and integer types,
duplicate-field rejection, bounded byte length, and fail-closed subprocess
errors. It does not accept an operator-supplied script, path, model text,
certificate or trusted key.

Even if every named service appears separate and the caller token is not
admin, the verdict is `INSUFFICIENT_INDEPENDENT_EVIDENCE`, **not**
`QUALIFIED`: mere local process metadata cannot prove protected key custody,
public-key pin independence, signed issuer provenance or rollback-resistant
authority. A Windows administrator may be able to tamper with or reconfigure
resources on that same machine; even differing process owners do not
establish an independent protected trust boundary.

The program intentionally returns exit code **3** for `NOT_QUALIFIED`,
exit **0** for `INSUFFICIENT_INDEPENDENT_EVIDENCE` (still explicitly
unqualified), and exit **2** for probe errors. None is a production
authorization success. `issuer_host_qualified` always remains false.

## Actual Windows host evidence

On Lappy, one native read-only probe returned:

- Exit `3` and status `NOT_QUALIFIED`.
- `CALLER_ADMIN_ON_PROPOSED_HOST`.
- `MODEL_SHARES_CALLER_PRINCIPAL` for the observed existing Ollama process.
- `NO_NAMED_ISSUER_SERVICE_DETECTED` among exactly the three names above.
- `PROTECTED_SIGNER_CUSTODY_UNVERIFIED`,
  `PROTECTED_PIN_CUSTODY_UNVERIFIED`, and
  `PROTECTED_REVISION_STORE_UNVERIFIED`.
- `INDEPENDENT_HOST_ATTESTATION_UNAVAILABLE`.

The JSON result SHA256 was
`ad2a5d63a5135ee6537c3ccda187477db370efa34ac08872ab6f94bc5c6b71c9`
when first captured. The source tree contains no private key, pinned
production issuer, privileged service or production memory grant as an
effect of this change. The search did not inspect every possible service
name or remote provider, so **do not** claim that no authority service
could exist under another name.

Executor reported VN1 and VN2 connected, but one bounded read-only start
attempt to each failed: VN1 transport returned an internal error and VN2
could not start the process. There is no successful current cross-host
principal/ACL verification; both remote hosts remain **UNKNOWN** on this
specific question. No alternate unapproved transport was used.

## Hostile and regression evidence

TDD RED missing module, then RED bool/integer input coercion: JSON integers
0/1 were initially accepted as booleans, and model owner `unknown_count`
could contradict a definite `same_principal=false`. Both were fixed.
Tests cover administrator/same-principal refusal, no-service evidence,
seemingly separate service still unqualified, same-principal service
refusal, unresolved owners, malformed or injected fields, strict type
checks, failed PowerShell execution, and output free of account identifiers.

Important: These tests exercise self-reported read-only Windows metadata
and policy logic; they do not elevate local facts into cryptographic
identity attestation, issuer isolation or a successful deployment.

## Next externally qualified work

A genuinely protected issuer requires an authority principal and signing
key outside Mini-Vera's model/caller control, independently pinned public
key, protected monotonic revocation state and independent readback. It also
requires verification that the caller cannot rewrite both authority and
trust pin, followed by real signed-grant and revocation tests across
separate principals. Lappy's current admin/same-principal setup fails that
separation. A distinct workstation **might** permit a better boundary,
but VN1/VN2's actual current execution identity remains UNKNOWN.

No production services or permissions were modified and no protected-branch
merge, neural training, user/private memory, paid compute, model inference
or actual issuer installation happened in this iteration.
