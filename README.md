# vera-mono

Self-contained Vera monorepo.

Vera's implementation lives here. External repositories are research labs, donor provenance, provider infrastructure, or independent reviewers; they are not source-code dependencies required to assemble the runtime. No Git submodules or sibling-repository runtime orchestration are used.

## Local architecture

- `packages/vera_core` — composition root and local capability registry.
- `packages/rezon` — absorbed reasoning kernel plus progressive-depth / recursive-delta reasoning.
- `packages/vera_runtime` — Vera runtime/cohesion code with monorepo-local affective, sexual-drive, and Deep Memory bindings.
- `packages/vera_identity` — identity, bootstrap, self-model, and semantic resources.
- `packages/vera_control` — local control/restore/qualification resources and a closed frozen R10 source cut.
- `packages/vera_recovery` — portable recovery/trust/lifecycle/temporal mechanics plus the native SQLite checkpoint ledger; legacy `r8a0` remains compatibility-only where superseded.
- `packages/vera_memory` — native governed memory/provenance ledger with CAS heads, idempotent admission, and supersession.
- `packages/vera_coordination` — local coordination contracts, routing, policy, temporal evidence, and in-memory runtime.
- `packages/vera_assurance` — deterministic internal drift/invariant checks. Internal self-checking is not called independent review.
- `packages/vera_pc_connection` — local PC-connection contracts, path policy, journal, envelopes, and state machine.
- `packages/portfolio_runtime` — absorbed reusable mechanisms from Lantern, Roots, SkeletonKey, Attune, Intranel, and Vera Works.

## Boundary

Donor references are preserved under `provenance/` and inside historical source artifacts. Their presence records where mechanisms came from; it does not make those repositories runtime dependencies.

External infrastructure can still exist where it is genuinely external: model/provider APIs, databases, devices, transports, and separately executed hostile reviewers. The adapters, contracts, policy, and state machines for using them belong here.

Native lifecycle flow is `vera_memory` CAS head → portable recovery checkpoint → validated local control-source cut/currentness candidate → digest-chained lifecycle journal → internal assurance gate → atomic currentness commit → committed journal event. `vera_core.VeraStateDirectory` reopens memory, recovery, currentness, journal, and trust paths from one persistent root, so restart reconstruction does not depend on conversational state. Recovery trust provisioning is user-local/configurable rather than tied to `/etc`, and inter-process registry locking uses SQLite rather than `fcntl`.

`vera_core.QualifiedVeraRuntime` is now the canonical host-composed runtime boundary. It opens the durable `VeraStateDirectory`, reuses the same persistent effect fence as the lifecycle, injects trusted PC/provider/reconciliation verifiers without persisting their secrets, and exposes the qualified coordination, effect, and recovery paths from one composition root. Low-level primitives remain available for adapters and tests, but they are not the qualified outbound runtime.\n\nOutbound action flow is lifecycle-bound too. Every qualified Bus/coordination command consumes an exact `AcceptedLifecyclePermit`; write-capable Bus commands are also single-use effect-fenced. PC jobs require an exact `AuthorizationEnvelope`, an exact-subject authority proof, a gateway-injected trusted PC verifier, and an in-window job/authorization window. Provider effects use a gateway-injected verifier registry keyed by provider; provider authority binds the exact effect id, operation, request digest, and accepted lifecycle permit. Caller-supplied opaque authority digests or caller-minted verifiers are not a qualified escape path. Interrupted, blocked, memory-ahead, control-drift, stale generations, and unresolved external effects fail closed before execution.\n\nIf an external dispatch becomes ambiguous, `EffectFence` records `ATTEMPTED_UNKNOWN`. That unresolved effect is surfaced in restart context and freezes new outbound mutation, accepted-action permit minting, and lifecycle/currentness advancement. The runtime-qualified recovery path is `LifecycleEffectRecovery`: it requires a gateway-injected trusted reconciliation verifier whose proof is bound to the exact ambiguous effect, original authority/currentness evidence, claimed outcome, and result digest. Only after that verification may the fence close the ambiguity as `RECONCILED_COMMITTED` or `RECONCILED_NO_EFFECT`. A later Vera generation cannot bury an uncertain external side effect, and a caller cannot clear it by supplying an arbitrary digest.

Independent falsification is deliberately different from internal assurance. Vera can contain DriftGuard-derived checking mechanisms while a separately executed DriftGuard remains useful specifically because it is outside Vera's own self-checking boundary.

## Status

This is source architecture and local implementation. It does not, by source presence alone, claim deployment, provider activation, project installation, behavioral qualification, consciousness, phenomenology, or protected-effect authorization.
