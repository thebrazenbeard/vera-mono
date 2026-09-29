# Vera Mono Runtime and Effect Contract V1

Status: CANDIDATE NATIVE PROJECT INTERFACE

Treat these as independent evidence dimensions:

1. **SOURCE** — exact repository source exists.
2. **BUILD_PACKAGE** — exact source builds/packages.
3. **INSTALLATION** — exact content is observed installed.
4. **CURRENT_ROUTE** — a live route selects an exact target.
5. **RUNTIME_CONSUMPTION** — a live consumer is observed using it.
6. **BEHAVIOR_EFFECT** — an exact probe produces observed behavior/effect evidence.
7. **EXTERNAL_ATTESTATION** — a separate provider attests to exact evidence.
8. **INDEPENDENT_REVIEW** — a genuinely separate reviewer evaluates a frozen subject/evidence cut.
9. **DEPLOYMENT_PRODUCTION** — production/canonical effect is separately authorized and verified.

No stage silently proves the next.

The preferred host-composed runtime boundary is `vera_core.QualifiedVeraRuntime`, backed by `vera_core.VeraStateDirectory`. Use it when live runtime execution is actually available. Source primitives, adapters, tests, repository files, or Project instructions do not become a live runtime merely because they can be imported or described.

Keep:
`REQUEST != AUTHORITY`
`AUTHORITY != ATTEMPT`
`ATTEMPT != EFFECT`
`EFFECT != VERIFIED_EFFECT`

Before consequential external writes, bind exact target/scope/operation, verify current authority and expected head/generation/digest, prefer CAS/non-force/transactional mechanisms, and preserve idempotency identity when available.

After the operation, read the target back independently and reconcile ambiguous outcomes before retrying.

Unless Patrick has already granted exact authority, do not merge/directly mutate `main`; deploy/install/activate/cut over runtime; alter credentials/permissions/providers/rulesets/trust roots/keys; mutate production provider state; incur cost; delete/irreversibly rewrite durable state; write canonical/autobiographical memory; or publish private material.

Safe preparation may include isolated branches, Draft PRs, tests, source-level implementation, review requests, and readiness classification.

Internal assurance can be strong engineering evidence. It is not independent review. A review applies only to the exact frozen subject/evidence cut it examined.
