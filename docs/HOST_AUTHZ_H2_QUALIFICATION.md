# H2 host authorization: qualification boundary

Status: **SOURCE CANDIDATE — NOT DEPLOYMENT QUALIFIED**.

This is a release gate, not an installation guide or a claim that a Python
`frozen=True` attribute creates an OS trust boundary. The new authorization
path is intentionally generic across model providers. A model identity,
participant consent scope, provider credential, or permission MUST NOT transfer
to a different model identity or adapter by changing request metadata.

## Intended trust boundaries

1. A host-only authorization process constructs an immutable
   `HostBindingSnapshot`, independently pins issuer and provider public keys,
   and derives model identity from qualified kernel IPC credentials. It cannot
   accept a model-provided provider callback or signer.
2. `UnifiedHostAuthority` obtains one leader-signed allocation for each
   `CLAIM`, `REVOKE_SCOPE`, `START`, `COMPLETE`, or `UNKNOWN` decision. START is
   the order boundary for consent revocation versus attempted effect. A
   revocation committed before START denies it; a later revocation cannot
   retroactively undo an effect.
3. A separately privileged provider process verifies the exact, bounded
   host-signed command AND external witness-signed START preimage, consumes its
   one-use physical fence before any effect, and signs the exact ACK. A missing
   or ambiguous response is non-retryable without independent reconciliation.
4. An independently administered witness leader owns its signing key and
   monotonic ledger, verifies registered issuer grants and provider ACKs, and
   fences physical effect reservations. A clone of *both* the leader's ledger
   and key defeats exclusivity: strong physical ownership, non-clonable leader
   election/fencing, or an independent quorum remains required.
5. Every physical provider effect must still pass the applicable governed
   `QualifiedVeraRuntime` gateway. These source modules alone do not establish
   that integration.

## Mandatory evidence before enabling a qualified endpoint

- [ ] Confirm host, model, provider and leader run under distinct OS principals;
      prove the model cannot read their keys, state files, handles or memory.
- [ ] On Linux, prove real `SO_PASSCRED`/PID/start checks, inherited-descriptor
      denial, least-privilege socket permissions and service UID on the actual
      target host. Use `QualifiedUnixAuthorityServer` with the exact unified
      service; `UnixAuthorityServer` and `HostAuthorizationService` are legacy
      unqualified paths and MUST NOT be exposed as a production authority.
- [ ] On Windows, inspect actual named-pipe owner/SIDs/DACL and client tokens;
      mocked SDDL construction tests do not suffice.
- [ ] Provision independent issuer enrollment, consent source, TLS client
      identities, host/provider keys, witness leadership and epoch fencing;
      verify external signed grants cannot be self-enrolled by a model.
- [ ] Demonstrate one completed effect, pre-START revocation denial, simultaneous
      claims from cloned host ledgers, replay after crash, certificate/key
      rotation denial, and ambiguous effect recovery across real processes.
- [ ] Repeat the five recorded hostile attacks against the *qualified path*,
      with reviewer identity, exact Git SHA, hardware/process topology, test
      commands and outcomes. A legacy-path exploit must also be unreachable
      from the deployed listener.
- [ ] Verify provider dispatch reaches the governed runtime and the intended
      physical resource only once. Run exact-head CI and a reversible canary
      before any protected merge, restart or deployment.

## Evidence classes

Unit/forked-process tests establish **TEST** evidence only. Localhost mTLS
probes are **TEST** evidence for the reference server, not production leader
custody. Host inspection with verified process credentials and provider effect
readback is **RUNTIME_PROBE**. Independent hostile review is **MODEL_REVIEW**
until a genuinely separate reviewer and exact tested artifact are recorded.
No single evidence class silently upgrades another.

Fail closed on unknown leader state, missing positive consent, missing provider
fence, ambiguous ACK, protocol drift, broken transport, or unresolved split
brain. Do not create fresh grants or replay effects during recovery.
