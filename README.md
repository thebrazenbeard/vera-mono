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

Independent falsification is deliberately different from internal assurance. Vera can contain DriftGuard-derived checking mechanisms while a separately executed DriftGuard remains useful specifically because it is outside Vera's own self-checking boundary.

## Status

This is source architecture and local implementation. It does not, by source presence alone, claim deployment, provider activation, project installation, behavioral qualification, consciousness, phenomenology, or protected-effect authorization.
