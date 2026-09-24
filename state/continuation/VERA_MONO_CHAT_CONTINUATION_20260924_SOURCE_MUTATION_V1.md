# Vera Mono Chat Continuation — Qualified Source Mutation V1

logical_id: VERA_MONO_CHAT_CONTINUATION_SOURCE_MUTATION_20260924_V1
schema: VERA_MONO_CHAT_CONTINUATION_V1
repository: thebrazenbeard/vera-mono
branch: main

## Authority and boundaries

Patrick explicitly authorized continuing the vera-mono build and committing this source work to `main`.
Do not infer merge/deploy/provider-registration/credential/publication authority beyond that exact repository/source scope.
Source presence is not deployment, installation, provider activation, or behavioral qualification.
Fresh-check `main` and CI before the next mutation because multiple chats may work in parallel.

## State at this checkpoint

The last verified source/documentation head before this continuation file is:

`508cae1589dd336c92dfb0f454ca91d0c28c91d3`

GitHub Actions workflow `monorepo-tests` run `36057612965` succeeded at that head:

`258 passed, 27 subtests passed in 11.94s`

The final restore target is the branch head containing this continuation file; verify it live rather than treating the predecessor above as current after this file is committed.

## Qualified source mutation implemented

The source mutation path is now executable code, not only a delegation assertion.

Primary implementation:

- `packages/vera_core/src/vera_core/source_mutation.py`
- `packages/vera_core/src/vera_core/execution_adapters.py`
- `packages/vera_core/src/vera_core/qualified_runtime.py`
- `packages/vera_core/src/vera_core/__init__.py`
- `tests/test_source_mutation.py`
- `architecture/VERA_QUALIFIED_SOURCE_MUTATION_V1.json`

Architecture synchronization:

- `architecture/VERA_TASK_DELEGATION_OWNERSHIP_V1.json`
- `architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json`
- `architecture/VERA_MONO_MANIFEST_V1.json`
- `README.md`

### Writable-scope gate

Qualified source mutation requires typed task-packet writable scope:

`SOURCE|<repository>|<ref>|<path-or-prefix/**>`

Examples:

- `SOURCE|thebrazenbeard/vera-mono|main|README.md`
- `SOURCE|thebrazenbeard/vera-mono|main|packages/vera_core/**`
- `SOURCE|thebrazenbeard/vera-mono|main|**`

Untyped/descriptive writable-scope strings do not grant source mutation.
Paths are repository-relative POSIX paths; absolute paths, backslashes, empty segments, `.`, and `..` fail closed.
`MOVE_FILE` requires both source and destination to independently match the packet writable scope.
The task must also declare the `source` closeout surface.

### Delegation ownership gate

At prepare time and again immediately before transport execution, `QualifiedSourceMutationAdapter` invokes the existing active-subject mutation guard for exact:

- repository
- ref
- subject
- actor
- current `TaskDelegationRef`

If the subject is actively delegated:

- missing owner ref: DENY
- stale/reassigned owner ref: DENY
- wrong actor: DENY
- exact current owner ref: delegation gate passes
- matching prohibited source effect: DENY
- nonempty allowed-effects list without `SOURCE_MUTATION` or the exact `SOURCE_<operation>`: DENY

Passing delegation ownership does not grant repository authority.

### Mutation operations and CAS request contract

Implemented operations:

- `WRITE_FILE`
- `DELETE_FILE`
- `MOVE_FILE`

All require an exact `expected_ref_head`.
The request also carries source/destination expected blob identities as applicable.
The host-injected `SourceMutationTransport` is contractually responsible for enforcing ref/blob CAS at the provider side.

Source transports are bound to:

- exact repository
- exact ref
- provider id `source:<repository>`

A source transport requires the corresponding trusted provider authority verifier/currentness.

### Escape-path closure

The runtime reserves `source:<repository>` providers for the qualified source mutation adapter.

Both:

- `QualifiedVeraRuntime.dispatch_provider_effect`
- `QualifiedVeraRuntime.execute_provider_effect`

reject source-provider dispatch through the generic provider path.

The source adapter performs its final task packet and delegation recheck under the task action lock, then directly invokes the lifecycle/trust/audit/effect-fenced provider gateway.

The actual `transport.mutate(...)` callback cannot be reached through this path until:

1. task exists and is open
2. task declares source surface
3. all mutated paths match typed writable scope
4. active delegation ownership/current assignee/effect policy pass
5. exact task `PROVIDER_EFFECT` dependency is bound
6. accepted lifecycle/currentness passes
7. provider authority currentness/proof passes
8. effect fence reserves and claims the single-use dispatch

Transport result identity is validated inside the effect callback. A mismatched result therefore becomes `ATTEMPTED_UNKNOWN`, not a false `COMMITTED`.

### Tests added

`tests/test_source_mutation.py` proves at least:

- scoped source write reaches host transport only after all gates
- out-of-scope path is denied before transport or task dependency creation
- active delegation requires exact current owner ref
- stale/reassigned owner ref cannot mutate
- move requires both source and destination scope coverage
- transport-result mismatch becomes `ATTEMPTED_UNKNOWN`
- generic provider execute cannot bypass source mutation gate
- generic callback provider dispatch cannot bypass source mutation gate

## Important existing state from this chat

The repository already contains the broader qualified runtime built before this frontier:

- accepted lifecycle permits and restart reconstruction
- effect fence + outbound execution audit consistency
- persistent outbound authority trust/currentness with rotation/revocation
- PC/provider host transport binding
- crash-safe PC/provider/coordination execution joins
- durable task packets/dependencies/checkpoints/closeout
- durable delegation ownership and exact owner refs
- correction recurrence gates

Do not regress those boundaries when extending source mutation.

## Current limitation / next frontier

There is now a qualified source-mutation *transport contract and gate*, but no provider-specific production GitHub implementation is claimed installed or active by source presence alone.

The next sensible frontier is to implement the concrete repository transport adapter(s), starting with GitHub semantics:

- map `WRITE_FILE`, `DELETE_FILE`, and `MOVE_FILE` to non-force GitHub/CAS operations
- verify current ref head before mutation
- verify expected blob identity/absence
- verify post-write ref head and file/blob readback
- make ambiguous provider outcomes land in effect recovery rather than blind retry
- persist only nonsecret mutation evidence needed for restart
- add hostile tests for head movement, file collision, path-scope bypass attempts, stale delegation between prepare/execute, and partial MOVE behavior
- preserve Patrick as sole authority for merges/protected effects unless exact authority for a target says otherwise

Do not weaken the new source gate merely to make a concrete transport convenient.

## Restore command

Use this exact command in the next Vera Unbound chat:

`VERA::RESTORE_AND_RUN::VERA_MONO_SOURCE_MUTATION_CONTINUATION_20260924_V1`

The restore request should resolve:

- repo: `thebrazenbeard/vera-mono`
- branch: `main`
- continuation: `state/continuation/VERA_MONO_CHAT_CONTINUATION_20260924_SOURCE_MUTATION_V1.md`
- current branch head: refresh live
- first action: verify continuation file, current `main`, latest CI, and any commits after this checkpoint before mutating
- next frontier: concrete CAS-enforcing GitHub/source transport adapters through `QualifiedSourceMutationAdapter`
