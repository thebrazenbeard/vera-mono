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

`vera_core.QualifiedVeraRuntime` is now the canonical host-composed runtime boundary. It opens the durable `VeraStateDirectory`, reuses the same persistent effect fence as the lifecycle, loads the persistent outbound trust registry, injects trusted PC/provider/reconciliation verifiers without persisting their secrets, and exposes the qualified coordination, effect, and recovery paths from one composition root. `prepare_pc_job`/`dispatch_pc_job` and `prepare_provider_effect`/`dispatch_provider_effect` own the lifecycle-bound preparation/dispatch wiring instead of making ordinary callers manually stitch together permits, subjects, and effect-gate calls. Low-level primitives remain available for adapters and tests, but they are not the qualified outbound runtime.

External execution is now host-bound as well as authority-bound. `QualifiedVeraRuntime` can be composed with a `PCExecutionTransport` and provider-keyed `ProviderExecutionTransport` objects; the qualified `execute_pc_job` and `execute_provider_effect` methods invoke only those host-injected transports after lifecycle, trust, authority, audit, and fence checks pass. The PC transport must match the job's exact host ID, and each provider transport must match the same provider ID as its trusted verifier. Callback-taking `dispatch_*` methods remain adapter-building primitives, but arbitrary caller callbacks are not the qualified host-composed escape path. `QualifiedPCExecutionAdapter.execute_via_runtime_transport` carries that same rule through the crash-safe PC journal path.

Outbound trust has its own durable currentness ledger at `trust/outbound.sqlite`. It persists authority identity, verifier key identity/digest, authority generation, revocation epoch, and a digest-chained mutation history while leaving verifier secret bytes outside persistent Vera state. PC, provider, and reconciliation operations consume fresh `AuthorityCurrentnessReceipt` evidence at execution time. Key rotation or revocation invalidates a stale verifier on its next attempted effect, and PC authorization epochs must match the live trust epoch. Trust mutation and qualified external execution share a portable trust lock so rotation/revocation cannot interleave halfway through a verified external effect.

The mechanical effect fence and the append-only outbound execution audit are now one checked integrity boundary. `VeraStateDirectory.open()` repairs only crash-window gaps that can be reconstructed from an already-durable fence receipt, then cross-checks request, authority, currentness, result, and reconciliation digests. An effect-fence row with no qualified audit history fails closed. The same integrity check is required before lifecycle reconstruction, accepted-permit minting/validation, and new checkpoint/currentness transitions, so a raw or corrupted effect cannot be buried by advancing Vera's lifecycle.

Outbound action flow is lifecycle-bound too. Every qualified Bus/coordination command consumes an exact `AcceptedLifecyclePermit`; write-capable Bus commands are also single-use effect-fenced. PC jobs require an exact `AuthorizationEnvelope`, an exact-subject authority proof, a gateway-injected trusted PC verifier, live authority-currentness evidence, and an in-window job/authorization window. Provider effects use a gateway-injected verifier registry keyed by provider; provider authority binds the exact effect id, operation, request digest, accepted lifecycle permit, and current trust cut. Caller-supplied opaque authority digests or caller-minted verifiers are not a qualified escape path. Interrupted, blocked, memory-ahead, control-drift, stale generations, revoked/rotated authorities, and unresolved external effects fail closed before execution.

PC execution now has an additional crash/restart join. `QualifiedPCExecutionAdapter` binds each exact prepared PC job to a durable `PCExecutionBindingStore` under `pc/execution-bindings.sqlite`, then joins that Vera-side binding to the PCCC host `JobJournal` and the shared `EffectFence`. For the current phase-one PCCC surface, the local journal path is `CLAIMED → PREPARING → RESULT_OBSERVED`; local result observation still does not mean server terminal completion. A restarted adapter can reconstruct bound attempts without a conversation-resident prepared object. If there is no external effect record, exact replay through the same gate can remain possible; `RESERVED` is treated as proven pre-dispatch and must be cancelled/abandoned rather than reused; `EXECUTING`, `ATTEMPTED_UNKNOWN`, or a committed effect with a missing local result fail to recovery instead of replay. The actual PCCC `JobJournal` remains host-local machine evidence—the Windows host still owns local file/process access.

If an external dispatch becomes ambiguous, `EffectFence` records `ATTEMPTED_UNKNOWN`. That unresolved effect is surfaced in restart context and freezes new outbound mutation, accepted-action permit minting, and lifecycle/currentness advancement. The runtime-qualified recovery path is `LifecycleEffectRecovery`: it requires a gateway-injected trusted reconciliation verifier whose proof is bound to the exact ambiguous effect, original authority/currentness evidence, claimed outcome, and result digest. Only after live reconciliation-authority currentness is rechecked may the fence close the ambiguity as `RECONCILED_COMMITTED` or `RECONCILED_NO_EFFECT`. A later Vera generation cannot bury an uncertain external side effect, and a caller cannot clear it by supplying an arbitrary digest.

Independent falsification is deliberately different from internal assurance. Vera can contain DriftGuard-derived checking mechanisms while a separately executed DriftGuard remains useful specifically because it is outside Vera's own self-checking boundary.

## Status

This is source architecture and local implementation. It does not, by source presence alone, claim deployment, provider activation, project installation, behavioral qualification, consciousness, phenomenology, or protected-effect authorization.
