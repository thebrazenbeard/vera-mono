# Vera Mono Chat Continuation — Source Transport V2

Schema: `VERA_MONO_CHAT_CONTINUATION_SOURCE_TRANSPORT_V2`

## Exact current checkpoint

Repository: `thebrazenbeard/vera-mono`  
Branch: `main`  
Head: `1137d71abc1a769984667a17b8a8aa4296321406`  
Verified workflow run: `36062517878`  
Verified result: **290 passed, 27 subtests passed**

This checkpoint records source/build state only. It does not imply deployment, provider activation, credential installation, protected-branch authority, or independent review.

## Implemented frontier

The qualified source mutation path now has a concrete GitHub transport and durable restart/recovery semantics.

`GitHubSourceMutationTransport` consumes the already-qualified `SourceMutationRequest` and performs Git object mutation through the host-injected `GitHubGitDataClient`. The concrete `GitHubGitDataAPIClient` uses REST for Git refs/commits/trees/blobs and GraphQL `updateRefs` for exact ref compare-and-swap with `beforeOid=expected_ref_head`, `afterOid=new_commit`, and `force=false`.

WRITE and DELETE are one-tree/one-commit changes. MOVE deletes the source and adds the destination in the same tree and advances the branch with one exact ref CAS. A failed CAS can leave unreachable Git objects, but it cannot partially move the branch.

The transport fails closed on stale ref heads, source/destination blob mismatch, unexpected destination collision, unsupported non-blob entries or file modes, recursive tree truncation, content-digest mismatch, GraphQL/HTTP failure, and post-write ref/blob readback mismatch. It performs no blind retry after provider-side mutation calls; ambiguity flows into the existing effect recovery barrier.

## Durable source restart binding

`SourceMutationBindingStore` persists nonsecret preparation evidence under:

`source/mutation-bindings.sqlite`

It binds:
- mutation/task/dependency identity
- task packet digest
- repository/ref/subject/actor
- operation/path/destination
- expected ref head and source/destination blob identities
- WRITE content digest only; source bytes are not persisted
- matched writable-scope entries
- exact delegation reference when present
- provider binding/request/authority-subject/lifecycle-permit evidence

`QualifiedSourceMutationAdapter.rehydrate_mutation` reconstructs an old prepared mutation only if the current task packet, writable scope, delegation ownership, provider binding, lifecycle permit, provider authority currentness, and exact repository/ref transport still match. WRITE content must be resupplied and match the durable content digest.

`SourceMutationRecoveryAssessment` surfaces those gates in restart context. Stale lifecycle state, delegation reassignment, provider-key rotation, missing transport, binding tamper, or changed content denies dispatch before source I/O.

## Safe pre-dispatch cancellation

`QualifiedSourceMutationAdapter.cancel_reserved_mutation` may cancel only an effect mechanically proven to remain `RESERVED`.

The cancellation:
1. rechecks the owning task, packet digest, writable scope, and current delegation owner;
2. verifies source/provider binding provenance;
3. requires exact `RESERVED` effect-fence state;
4. transitions the effect to `CANCELLED_PRE_DISPATCH`;
5. cancels the owning task dependency.

The mutation/effect identity is not reusable. A replacement needs a new mutation id and dependency id.

Once the effect is `EXECUTING` or `ATTEMPTED_UNKNOWN`, this cancellation path is forbidden and reconciliation remains mandatory.

## Authority and state boundaries

The source transport does not grant writable scope or delegation ownership. Task scope does not grant provider/repository authority. Provider authority does not create task scope. Source presence does not mean a token or transport is installed. No merge/deploy/install/publication authority is created by these mechanisms.

## Next frontier

Build an exact post-mutation verification gate before source-bearing task closeout:

- bind the committed source result to the exact new Git commit/ref head;
- retrieve CI/check-run status for that exact commit through a read-only host-injected verification adapter;
- persist a verification receipt tied to repository/ref/commit and required check identities;
- distinguish pending, passed, failed, stale-head, and unavailable verification;
- make task closeout require the exact verification dependency when its packet says source verification is required;
- never treat CI PASS as merge/deploy/install authority or independent review;
- retain an external independent-review route where required.

Refresh `main` and CI before mutating because parallel chats may advance the repository.
