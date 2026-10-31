# Governed H3 provider-process effect adapter

**Status: source-tested; production installation and effect qualification HOLD.**

`vera_core.host_authz.governed_provider` adds a provider-owned constructor
`build_governed_provider_worker()`. It takes an already qualified
`QualifiedVeraRuntime` and its *same-instance* registered
`HmacProviderAuthority`. There is deliberately no arbitrary `execute`
callback argument; the worker's physical callback is always the captured
`GovernedProviderExecutor`.

The callback verifies exact provider instance and payload digest, rejects
rebound runtime provider transports or verifier objects, then uses Vera's
canonical provider-effect path:

1. `prepare_provider_effect()` (accepted lifecycle permit and durable binding).
2. `HmacProviderAuthority.issue()` with the prepared effect/request/permit.
3. `execute_provider_effect()` (registered outbound trust, mechanical one-use
   fence, and provider transport).
4. Require committed mechanical fence, matching request digest, committed
   audit event and fence/audit consistency before returning a bounded result.

The separate `ProviderCustodyWorker` requires an independently signed START
lease and external one-use provider fence **before** it invokes that callback.
If a provider call or audit verification fails after admission, the worker
must preserve ambiguous/non-replayable state; a caller must not retry or infer
that no physical effect occurred.

Source tests exercise the real `QualifiedVeraRuntime` fixture, committed audit
and fence, replay refusal, stale lifecycle, transport/verifier substitution,
provider identity and payload tampering, and uncertain canonical outcome.
They do **not** prove that an installed provider daemon uses this factory, that
its OS account and credentials are inaccessible to models, or that real
provider status/reconciliation is independent. Those require separate
process/host readback and an exact-head physical effect canary under a valid
host lease before merge/deployment.

The legacy `qualified_provider_handle()` remains a separate unqualified
in-process source bridge; this H3 constructor does not make that route safe to
expose as a production service.
