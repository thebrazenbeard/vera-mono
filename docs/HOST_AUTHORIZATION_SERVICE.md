# Host-owned authorization service — source candidate

This opt-in package is a new service boundary, not a wrapper patch or a deployed
model-visible tool. A model process is an untrusted requester. It cannot set its
authenticated peer, grant issuer, provider transport, identity, subject, host,
or consent decision.

The service binds a kernel-authenticated peer to an immutable principal, verifies
a signed host-issued grant with exact model/runtime/subject/purpose/provider/
operation/payload/epoch/host scope, asks a host-owned consent-status authority,
and performs a durable one-use claim before provider execution. It refuses
unknown grants or principals. Ambiguous provider outcomes stay held for
reconciliation rather than automatic retry.

The host must own process isolation, issuer key and provider custody, a truly
external monotonic/exclusive-authority witness, and the consent authority.
SQLite by itself is not rollback-proof or cross-host split-brain protection.
Synthetic test witnesses and signers demonstrate behavior, not real authority.
Models sharing an indistinguishable OS identity cannot be distinguished by
self-asserted JSON identities and must be separated by the host first.

**Release HOLD:** Do not install, merge, or advertise production authorization
until an independent exact-head review establishes issuer/consent provenance,
OS peer separation on each target host, trusted antirollback, provider effect
fencing and status recovery, crash/restart tests, and Windows as well as Linux
authenticated transport. The concurrent PR #156 is not production-qualified.

## Explicit hostile findings during source qualification

Independent adversarial tests have demonstrated that an arbitrary mutable
provider callback can change its nested target after being pinned; the wrong
target can receive an instruction before the service rejects its forged or
incorrect acknowledgement. A `frozen` Python value also cannot protect an
issuer verifier from code that already executes inside the privileged host
process. Accordingly the trusted service and provider must be OS-isolated
from model code, and canonical provider effect admission must be preserved.

Two distinct processes under the same Linux UID yield the same kernel peer
identity. A model binding is valid only with a distinct host-provisioned OS
principal; a caller-supplied model name or peer claim is insufficient.

An asynchronous consent revocation may occur after the last consent check but
before the physical effect. This is not solved by more repeated reads. It
requires a governed claim-to-provider-dispatch linearization policy and
provider-side lease/fencing at use time, with independently tested revoke
semantics. Pending claims cannot be silently retried or assumed cancelled.

The host authorization service's new signed authorization receipt is an
independent layer and must not bypass existing `QualifiedVeraRuntime`
lifecycle, outbound trust, mechanical effect fence and audit. A dedicated
qualified bridge is required for Vera provider effects.
