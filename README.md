> **License:** Source-visible, not open source. Original material is proprietary. Commercial use, redistribution, hosted-service use, and commercial derivative products require written permission. See [LICENSE](LICENSE) and [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md). Separately identified third-party components retain their own licenses.

# vera-mono

Self-contained Vera monorepo.

Vera's implementation lives here. External repositories are research labs, donor provenance, provider infrastructure, or independent reviewers; they are not source-code dependencies required to assemble the runtime. No Git submodules or sibling-repository runtime orchestration are used.

## Local architecture

- `packages/vera_ingest` - absorbed provider-neutral exact-byte intake, deterministic normalization/identity, provenance, and receipt boundary; intake is not truth/currentness/authority/memory admission.
- `packages/vera_core` â€” composition root and local capability registry.
- `packages/rezon` â€” absorbed reasoning kernel plus progressive-depth / recursive-delta reasoning.
- `packages/vera_runtime` â€” Vera runtime/cohesion code with monorepo-local affective, sexual-drive, and Deep Memory bindings.
- `packages/vera_identity` â€” identity, bootstrap, self-model, and semantic resources.
- `packages/vera_control` â€” local control/restore/qualification resources and a closed frozen R10 source cut.
- `packages/vera_recovery` â€” portable recovery/trust/lifecycle/temporal mechanics plus the native SQLite checkpoint ledger; legacy `r8a0` remains compatibility-only where superseded.
- `packages/vera_memory` â€” native governed memory/provenance ledger with CAS heads, idempotent admission, and supersession.
- `packages/vera_coordination` â€” local coordination contracts, routing, policy, temporal evidence, and a native persistent SQLite repository; in-memory storage remains a test/adapter surface.
- `packages/vera_assurance` â€” deterministic internal drift/invariant checks. Internal self-checking is not called independent review.
- `packages/vera_pc_connection` â€” local PC-connection contracts, path policy, journal, envelopes, and state machine.
- `packages/portfolio_runtime` â€” absorbed reusable mechanisms from Lantern, Roots, SkeletonKey, Attune, Intranel, and Vera Works.

## Boundary

Donor references are preserved under `provenance/` and inside historical source artifacts. Their presence records where mechanisms came from; it does not make those repositories runtime dependencies.

External infrastructure can still exist where it is genuinely external: model/provider APIs, databases, devices, transports, and separately executed hostile reviewers. The adapters, contracts, policy, and state machines for using them belong here.

### Optional Deep Memory search transport (source candidate)

`runtime_cohesion.deep_memory_cli_transport.PinnedDeepMemoryCLITransport` is an
opt-in, read-only source adapter for an operator-supplied DeepMemoryStorage checkout.
It accepts only scoped historical evidence searches, verifies the configured Git
commit against the external-provider registry's exact source binding, refuses a
checkout with any mismatched tracked byte, hidden/ignored extra file or unsafe
symlink/submodule, then runs only a private temporary snapshot of the verified
Git-tree bytes. Its subprocess inherits no ambient tokens, Git or Python path;
stdout is drained in fixed-size chunks with a hard in-memory byte cap; the child
is killed on overflow or deadline rather than allowed to fill a temporary file.
The CLI is invoked without a shell. It returns the bounded result to
`DeepMemoryEvidenceAdapter` for schema and privacy validation. Both explicit and
effective overlay privacy scopes are checked. An archive-wide audit, live provider
installation, current-memory write, or execution authority is **not** provided.

The bundled registry now pins the reviewed DeepMemoryStorage
`63edbc51fb87c889ab58051d02e18ba2aeca0d24`; the vendored architecture
binding is synchronized to its exact Git blob. Its retrieval program, result
schema, and integration contract are unchanged from the previous source pin.
Any checkout at a different commit, including later `main`, fails closed.
Its deterministic tests use a synthetic producer at an exact Git commit, not a
claim of a deployed runtime or a live historical-data retrieval. Operator source
review and explicit runtime installation/currentness approval remain separate.

Native lifecycle flow is `vera_memory` CAS head â†’ portable recovery checkpoint â†’ validated local control-source cut/currentness candidate â†’ digest-chained lifecycle journal â†’ internal assurance gate â†’ atomic currentness commit â†’ committed journal event. `vera_core.VeraStateDirectory` reopens memory, recovery, currentness, journal, and trust paths from one persistent root, so restart reconstruction does not depend on conversational state. Recovery trust provisioning is user-local/configurable rather than tied to `/etc`, and inter-process registry locking uses SQLite rather than `fcntl`.

`vera_core.QualifiedVeraRuntime` is now the canonical host-composed runtime boundary. It opens the durable `VeraStateDirectory`, reuses the same persistent effect fence as the lifecycle, loads the persistent outbound trust registry, injects trusted PC/provider/reconciliation verifiers without persisting their secrets, and exposes the qualified coordination, effect, and recovery paths from one composition root. `prepare_pc_job`/`dispatch_pc_job` and `prepare_provider_effect`/`dispatch_provider_effect` own the lifecycle-bound preparation/dispatch wiring instead of making ordinary callers manually stitch together permits, subjects, and effect-gate calls. Low-level primitives remain available for adapters and tests, but they are not the qualified outbound runtime.

External execution is now host-bound as well as authority-bound. `QualifiedVeraRuntime` can be composed with a `PCExecutionTransport` and provider-keyed `ProviderExecutionTransport` objects; the qualified `execute_pc_job` and `execute_provider_effect` methods invoke only those host-injected transports after lifecycle, trust, authority, audit, and fence checks pass. The PC transport must match the job's exact host ID, and each provider transport must match the same provider ID as its trusted verifier. Callback-taking `dispatch_*` methods remain adapter-building primitives, but arbitrary caller callbacks are not the qualified host-composed escape path. `QualifiedPCExecutionAdapter.execute_via_runtime_transport` carries that same rule through the crash-safe PC journal path.

Outbound trust has its own durable currentness ledger at `trust/outbound.sqlite`. It persists authority identity, verifier key identity/digest, authority generation, revocation epoch, and a digest-chained mutation history while leaving verifier secret bytes outside persistent Vera state. PC, provider, and reconciliation operations consume fresh `AuthorityCurrentnessReceipt` evidence at execution time. Key rotation or revocation invalidates a stale verifier on its next attempted effect, and PC authorization epochs must match the live trust epoch. Trust mutation and qualified external execution share a portable trust lock so rotation/revocation cannot interleave halfway through a verified external effect.

The mechanical effect fence and the append-only outbound execution audit are now one checked integrity boundary. `VeraStateDirectory.open()` repairs only crash-window gaps that can be reconstructed from an already-durable fence receipt, then cross-checks request, authority, currentness, result, and reconciliation digests. An effect-fence row with no qualified audit history fails closed. The same integrity check is required before lifecycle reconstruction, accepted-permit minting/validation, and new checkpoint/currentness transitions, so a raw or corrupted effect cannot be buried by advancing Vera's lifecycle.

Outbound action flow is lifecycle-bound too. Every qualified Bus/coordination command consumes an exact `AcceptedLifecyclePermit`; write-capable Bus commands are also single-use effect-fenced. PC jobs require an exact `AuthorizationEnvelope`, an exact-subject authority proof, a gateway-injected trusted PC verifier, live authority-currentness evidence, and an in-window job/authorization window. Provider effects use a gateway-injected verifier registry keyed by provider; provider authority binds the exact effect id, operation, request digest, accepted lifecycle permit, and current trust cut. Caller-supplied opaque authority digests or caller-minted verifiers are not a qualified escape path. Interrupted, blocked, memory-ahead, control-drift, stale generations, revoked/rotated authorities, and unresolved external effects fail closed before execution.

Provider execution now has a parallel restart binding without turning the state directory into a secret store. `ProviderExecutionBindingStore` persists the effect/provider/operation identity, request digest, authority subject, and original lifecycle permit under `provider/execution-bindings.sqlite`, but never the arbitrary request payload. After restart, `rehydrate_provider_effect` requires the payload to be supplied again and rejects it unless its digest matches the durable binding; it preserves the original permit rather than minting a fresh one, so lifecycle advancement makes the old request non-dispatchable. `assess_provider_effect` classifies prepared, reserved, ambiguous, and terminal effects from the binding plus the mechanical fence. The qualified provider transport path also deep-copies the request payload and rechecks its digest before handing the detached snapshot to the host-injected transport, closing the ordinary mutable-payload handoff gap.

Coordination writes now have their own crash/restart join as well. The qualified runtime uses a persistent native SQLite coordination repository plus `CoordinationCommandJournal` under `coordination/commands.sqlite`. Before a write can reach the Bus, its command ID is bound to the exact actor, invocation digest, accepted lifecycle permit, and mechanical request digest. After the effect commits, the journal records the coordination result digest and receipt metadata and cross-checks write-confirmed results against the actual persistent coordination event. A crash after the Bus write but before result journaling is therefore classified as recovery-required and is never replayed; a purely `RESERVED` command can only be cancelled pre-dispatch, while a complete journal+fence+repository match is terminal. The command journal also maintains a projection digest/count integrity check so deleting or mutating command/result rows fails closed.

PC execution now has an additional crash/restart join. `QualifiedPCExecutionAdapter` binds each exact prepared PC job to a durable `PCExecutionBindingStore` under `pc/execution-bindings.sqlite`, then joins that Vera-side binding to the PCCC host `JobJournal` and the shared `EffectFence`. For the current phase-one PCCC surface, the local journal path is `CLAIMED â†’ PREPARING â†’ RESULT_OBSERVED`; local result observation still does not mean server terminal completion. A restarted adapter can reconstruct bound attempts without a conversation-resident prepared object. If there is no external effect record, exact replay through the same gate can remain possible; `RESERVED` is treated as proven pre-dispatch and must be cancelled/abandoned rather than reused; `EXECUTING`, `ATTEMPTED_UNKNOWN`, or a committed effect with a missing local result fail to recovery instead of replay. The actual PCCC `JobJournal` remains host-local machine evidenceâ€”the Windows host still owns local file/process access.

The repository now builds as one `vera-mono` wheel instead of relying on pytest-only source-path assembly. The root `pyproject.toml` searches twelve monorepo source roots and includes fifteen runtime package namespaces, carrying their packaged resources into the distribution. CI builds the wheel after the full test suite, verifies its archive closure and representative deep resources, installs it into an isolated target directory, then imports every expected runtime package and reads representative resources through `importlib.resources`. That establishes a concrete build/package artifact boundary while preserving the distinction that a successful wheel build or isolated CI install is not a production installation, current route, runtime-consumption proof, deployment, or behavioral qualification.

Installation is now an independently verifiable truth surface instead of something inferred from a wheel build. Tasks that declare `INSTALL_VERIFY|<target-id>|<distribution>|<version>` must produce a durable `InstallationVerificationReceipt` in `install/verification.sqlite`, and closeout requires the `install/registration` surface to be `verified-current` or `changed-and-verified`. A stored PASS is historical evidence only: the host-injected read-only verifier must still observe the same version and installed-content digest at closeout/restart time. The first concrete verifier uses Python `importlib.metadata` to inspect an installed distribution and hash its installed files without installing or changing anything. Installation verification does not establish the selected route, runtime consumption, provider activation, deployment, or behavior.

Current route is now a separately verified live surface too. Tasks can declare `ROUTE_VERIFY|<route-id>|<expected-target>` and must produce a durable `RouteVerificationReceipt` under `route/verification.sqlite` before a relevant `current route` surface can close. A stored PASS is historical evidence only: closeout and restart assessment refresh the host-injected route observer and require the selected target and route digest to still match the exact stored PASS. `JsonFileRouteVerificationTransport` supplies a read-only concrete route observer for JSON route selectors. Installation does not imply route selection, and route selection still does not prove runtime consumption or behavior.

Runtime consumption is now a separate live truth surface instead of being inferred from installation or route selection. Tasks can declare `RUNTIME_CONSUME_VERIFY|<consumer-id>|<route-id>|<expected-target>` and must produce a durable runtime-consumption receipt under `runtime/consumption-verification.sqlite` before a relevant `runtime consumption` surface can close. The host-injected observer must still report the same consumed target, route digest, process instance, and runtime-state digest as the stored PASS; a process restart or state change therefore requires a new verification. When the task also declares a matching `ROUTE_VERIFY`, consumption must match the live-current route digest as well. `JsonFileRuntimeConsumptionTransport` provides a read-only observer for host-written runtime state. Consumption proves what target a live consumer reports using; it still does not prove behavioral qualification or provider activation.

Behavior/effect qualification is now a separate live truth surface after runtime consumption. Tasks can declare `BEHAVIOR_EFFECT_VERIFY|<consumer-id>|<probe-id>|<BEHAVIOR-or-EFFECT>|<stimulus-sha256>|<outcome-sha256>`; the same consumer must also have a live-current `RUNTIME_CONSUME_VERIFY` result, but that consumption PASS is only a prerequisite and never becomes behavior PASS. A behavior/effect receipt under `behavior/verification.sqlite` binds the exact runtime-consumption receipt, process instance, runtime-state digest, declared stimulus/outcome digests, and refreshed host/external evidence. `BEHAVIOR` probes require exact observed behavior evidence without claiming an external effect; `EFFECT` probes additionally require an exact external effect ID and receipt digest. A stored PASS becomes historical if the process/state changes, the external evidence bytes change, or the live evidence transport disappears. `JsonFileBehaviorEffectVerificationTransport` is a read-only concrete observer that hashes the exact host/external evidence-file bytes; that proves which bytes were observed, not that the host itself is infallible. Behavioral qualification remains distinct from deployment, provider activation, protected-effect authority, independent review, consciousness, or phenomenology.

A stronger external-attestation layer is available when a task declares `BEHAVIOR_ATTEST_VERIFY|<consumer-id>|<probe-id>|<declaration-sha256>|<provider-id>|<provider-key-id>|<provider-key-sha256>|<effect-subject-sha256-or-NONE>`. This gate sits above, rather than replacing, live behavior/effect verification. It binds the current behavior receipt to an exact canonical behavior declaration digest, external evidence-provider identity and key identity, a signed attestation subject, the raw-response digest, and a single-use nonce. `EFFECT` attestations also bind the external effect ID, the exact external effect-receipt bytes digest, and a declared effect-subject digest; Vera's local effect fence is deliberately not treated as proof of that external effect. `JsonFileBehaviorAttestationTransport` verifies host-written evidence with a host-injected verifier and refreshes the exact evidence at closeout/restart. The included HMAC verifier provides concrete tamper/provenance binding when its secret remains outside Vera state, but shared-secret verification is not independent behavioral review and does not establish deployment, provider activation, protected-effect authority, consciousness, or phenomenology.

Independent held-out review is now a separate gate rather than a stronger label on the attestation layer. Tasks can declare `INDEPENDENT_BEHAVIOR_REVIEW_VERIFY|<consumer-id>|<probe-id>|<review-id>|<subject-actor-id>|<declaration-sha256>|<held-out-probe-set-sha256>|<probe-curator-id>|<evaluator-id>|<evaluator-key-id>|<evaluator-key-sha256>|<authority-id>|<authority-key-id>|<authority-key-sha256>`. `JsonFileIndependentBehaviorReviewTransport` consumes two read-only external evidence files: an authority/currentness statement and an evaluator result. The review binds the exact declaration, held-out probe-set digest, live behavior/effect receipt, process/runtime state, evaluator identity/key/currentness, result bytes, result-receipt bytes, review provenance, and replay-safe nonces. The subject, probe curator, evaluator, and authority must be distinct actors, and Vera's runtime exposes verification onlyâ€”it does not persist evaluator/authority signing secrets or provide a signer that could manufacture the independent verdict. `Ed25519IndependentReviewVerifier` is the concrete operational verifier: it accepts only a 32-byte public key, derives the bound key digest from those public bytes, verifies base64 Ed25519 signatures, and exposes no signing method or private-key custody. A source-level PASS therefore means the externally supplied review package remains cryptographically and propositionally bound to the exact live evidence; it does not mean the evaluator is infallible, that an external review has actually been executed merely because this code exists, or that deployment/provider/protected-effect/consciousness claims follow.

Substantial work now has native durable task state instead of relying on a chat transcript as the continuation record. `TaskExecutionLedger` persists exact task packets and checkpoints under `tasks/tasks.sqlite`, including purpose, subject, observable completion state, required evidence, writable scope and non-targets, forbidden shortcuts/effects, priority order, unknowns, return shape, completed evidence, blockers, protected effects still gated, and the next runnable frontier. `QualifiedVeraRuntime` binds task open/checkpoint/closeout records to the current lifecycle, outbound audit/trust, and coordination evidence cut. Closeout is deliberately multi-surface: source, build/package, install/registration, current route, runtime consumption, behavior/effect, docs/rules, memory/privacy, and workspace/coordination are closed independently as `verified-current`, `changed-and-verified`, `pending`, `out-of-scope`, or `not-applicable`. A relevant `pending` surface, unresolved protected effect, recovery-required coordination/provider action, non-accepted lifecycle, or explicit blocker prevents closeout; a green CI run cannot silently promote source success into install/runtime/effect success.

Task execution is now tied to the exact actions a task depends on rather than only to global runtime health. `TASK_DEPENDENCY` records bind an exact task subject/packet to a required mechanical effect, coordination command, or provider effect before work starts. A `(kind, target)` has one durable task owner, post-hoc claims are rejected, and an exact binding replay is idempotent. The task-scoped qualified paths (`invoke_task_coordination`, `prepare_task_provider_effect`, and `prepare_task_pc_job`) hold a portable task action lock across binding and initial qualified work, while closeout takes the same lock so it cannot race task-scoped mutation. Restart context reconstructs dependency state as `SATISFIED`, `MISSING`, `PENDING`, `RECOVERY_REQUIRED`, or `TERMINAL_UNSATISFIED` and exposes `cancellation_allowed`. Only a `MISSING` dependency with no durable target preparation/execution evidence may be cancelled; that produces `TASK_DEPENDENCY_CANCELLED`, the cancelled ID cannot be reused, and restart never auto-cancels it. Cancellation or reconciled-no-effect does not count as successful completion of active required work. Closeout fails until every active dependency is satisfied, automatically carries verified dependency evidence digests, and also preserves cancellation-event evidence for intentionally withdrawn pre-execution dependencies.

Delegated work now has durable ownership semantics instead of being a loose coordination convention. `TASK_DELEGATED` binds the exact repository, ref/head, semantic/file subject, assignee, allowed/prohibited effects, return shape, and evidence refs to the parent task. While that delegation is active, the same `(repository, ref, subject)` cannot be independently delegated to another task. `TaskDelegationRef` is an exact active-owner credential: reassignment invalidates the old reference, and return/cancellation invalidates it entirely. Reassignment changes the assignee without releasing the subject; only an explicit return or cancellation releases it. A return must supply exactly the declared return-shape fields with non-empty values plus result evidence, so the return contract is executable rather than descriptive. `assert_task_subject_mutation_allowed` now provides the fail-closed ownership check for mutation adapters: an actively delegated scope requires the exact current `TaskDelegationRef` and matching assignee, while a stale ref, wrong actor, or missing owner ref is denied. Passing that guard still does not create repository or provider authority. Active delegations block task closeout, restart context restores the current owner, and returned/cancelled delegation event digests are carried into closeout evidence so a delegated branch cannot simply disappear from the completion story.

Repository/file writes now have a qualified task-scoped path rather than relying on a caller to remember task boundaries. `QualifiedSourceMutationAdapter` accepts only typed writable-scope entries of the form `SOURCE|<repository>|<ref>|<path-or-prefix/**>`, requires the task to declare the `source` surface, and checks every target path (both source and destination for moves). If the `(repository, ref, subject)` is actively delegated, the exact current `TaskDelegationRef`, current assignee, and delegation effect policy are required. Those scope/ownership checks run at preparation and again under the task action lock immediately before the host-injected `SourceMutationTransport` can write. The actual mutation is still an accepted-lifecycle, provider-authority-current, audited, single-use effect-fenced provider effect using the reserved `source:<repository>` provider namespace. Generic provider dispatch/execute paths reject that namespace, and the transport request carries expected ref/blob identities for provider-side CAS; a mismatched transport result is treated as `ATTEMPTED_UNKNOWN`, not a false commit. Writable scope and delegation are necessary gates, but neither creates repository, merge, deploy, install, or publication authority.

The first concrete source transport is now local: `GitHubSourceMutationTransport` uses `GitHubGitDataAPIClient` to build Git blobs/trees/commits and closes the ref race with GitHub GraphQL `updateRefs` using exact `beforeOid`/`afterOid` and `force=false`. WRITE and DELETE are one-tree/one-commit changes; MOVE deletes the source and adds the destination in the same tree and advances the branch with one exact ref compare-and-swap, so a rejected CAS cannot leave a half-moved branch. Recursive tree truncation, stale ref/blob identity, destination collision, unsupported non-blob entries, content-digest drift, and post-write readback mismatch all fail closed. The transport does no blind retry after a provider mutation call; ambiguous outcomes rise into the existing effect-recovery barrier.

Source preparation also leaves a nonsecret restart binding in `source/mutation-bindings.sqlite`. Restart recovery now rechecks the original task packet, exact writable-scope match, current delegation owner, provider binding, lifecycle permit, live provider authority currentness, and exact repository/ref transport registration before the old prepared request can even become a dispatch candidate. WRITE content must be resupplied after restart and its digest must exactly match the durable binding; stale lifecycle state, delegation reassignment, provider-key rotation, missing transport, binding tamper, or changed content all fail before the source transport is called. A source effect proven to be only `RESERVED` may be cancelled through `cancel_reserved_mutation`, which records `CANCELLED_PRE_DISPATCH` and cancels the owning task dependency; any replacement must use a new mutation/dependency identity. Once dispatch has reached `EXECUTING` or `ATTEMPTED_UNKNOWN`, that cancellation path is forbidden and reconciliation remains mandatory.

Exact committed-source verification is now a separate durable gate rather than an inference from a successful write. A task can declare checks with `SOURCE_VERIFY|<repository>|<ref>|<check-name>` in `evidence_requirements`; when it does, the owning source dependency stays unsatisfied until `QualifiedSourceVerificationAdapter` records a PASS receipt for the exact mutation outcome commit. The verification store is append-only under `source/verification.sqlite` and rechecks that the source outcome still binds the exact source/provider/effect evidence before asking an external verifier. FAIL, PENDING, or unavailable checks remain blocked rather than becoming source success, and a moved branch head is recorded as `STALE_HEAD`/provenance mismatch. `GitHubSourceVerificationTransport` provides the concrete GitHub read path: it verifies the exact commit OID, exhaustively paginates `statusCheckRollup` contexts across Check Runs and legacy status contexts, treats missing required contexts as unavailable, and observes the branch head separately. Passing those checks closes only the declared source evidence requirement; it does not imply merge, deploy, installation, runtime consumption, behavioral qualification, or independent review.

The task ledger also implements the correction-recurrence gate rather than treating a repeated correction as another piece of chat prose. `record_task_correction` binds the correction to the exact task subject and packet digest and preserves the obsolete route, required change, current owner reference, and provenance references. The next durable checkpoint must explicitly address every unresolved correction and must record a changed method, a regression guard, or a blocker classification; otherwise it fails closed. An unresolved correction also blocks task closeout, so the old route cannot be silently renamed and declared complete.

If an external dispatch becomes ambiguous, `EffectFence` records `ATTEMPTED_UNKNOWN`. That unresolved effect is surfaced in restart context and freezes new outbound mutation, accepted-action permit minting, and lifecycle/currentness advancement. The runtime-qualified recovery path is `LifecycleEffectRecovery`: it requires a gateway-injected trusted reconciliation verifier whose proof is bound to the exact ambiguous effect, original authority/currentness evidence, claimed outcome, and result digest. Only after live reconciliation-authority currentness is rechecked may the fence close the ambiguity as `RECONCILED_COMMITTED` or `RECONCILED_NO_EFFECT`. A later Vera generation cannot bury an uncertain external side effect, and a caller cannot clear it by supplying an arbitrary digest.

Independent falsification is deliberately different from internal assurance. Vera can contain DriftGuard-derived checking mechanisms while a separately executed DriftGuard remains useful specifically because it is outside Vera's own self-checking boundary.

### Experimental Rezon collective observation (not a runtime capability)

`vera_core.external_rezon_collective.LoopbackCollectiveObserver` is an opt-in,
**read-only** adapter for an independently running Rezon collective gateway. It
uses the separately configured, operator-supplied **read-only state secret**
(never Rezon's write-capable admin or worker token) to fetch only the episode's state
from numeric `127.0.0.1`, with bounded time and response size. The caller must
independently supply the expected episode ID, ordered worker roster, and SHA-256
of the original prompt. The adapter checks claim structure, worker answer and
peer-review identities, target relationships, and the deterministic input digest.
It rejects cross-episode/prompt/roster mismatches and treats a missing worker as
`INCOMPLETE_UNKNOWN`, not as consensus.

Rezon's `complete` field means **all initial answers**, not all peer reviews or
an integrated synthesis. To prevent downstream code from confusing those
stages, `CollectiveObservation.round_state` separately reports
`INITIAL_ANSWERS_INCOMPLETE`, `PEER_REVIEW_INCOMPLETE`,
`SYNTHESIS_NOT_OBSERVED`, or `SYNTHESIS_PRESENT_UNVERIFIED`, alongside the
exact `missing_review_agents` and `current_synthesis_ids`. The stricter
observer-only round label requires each enrolled worker to have reviewed;
it does not change Rezon's own valid partial-round behavior or certify
independence. Even a fully observed round remains only
`COMPLETE_UNVERIFIED` / `UNVERIFIED_GATEWAY_CLAIM`. A gateway token authenticates
access to that gateway; it does **not** attest two independent model hosts,
establish correctness or agreement, qualify the synthesis, admit memory, or
authorize any protected effect. This code neither launches Rezon nor injects its
claims into `QualifiedVeraRuntime`. Rezon's stand-alone package and the absorbed
monorepo `packages/rezon` have overlapping Python module names, so operate the
external gateway as a separate process; do not combine both package source trees
on a single `PYTHONPATH`. Deterministic contract checks are in
`tests/test_external_rezon_collective.py`; deployed worker/process independence
still requires separately qualified host evidence.

This adapter requires the complementary Rezon gateway `read_token` role
(`REZON_COLLECTIVE_STATE_READ_TOKEN` in Rezon's CLI). Older gateways without
that opt-in role reject the credential; do not work around that by substituting
an administrator bearer. Provision the read secret as 32 random bytes encoded
in 64 lowercase hex characters, using `secrets.token_hex(32)` rather than a
human-chosen password. On each observation, the client sends the exact path
and a random client nonce, verifies a server-signed 10-second challenge before
sending any request HMAC, and verifies the exact returned state bytes with a
separate MAC. Each transcript binds the exact `GET` state path and expected
numeric `127.0.0.1:port` audience; Rezon uses its actual accepted socket for
that audience, not a caller-controlled `Host` header. **The read-only secret
never appears in the HTTP request.** A spoofed cross-port or obsolete gateway
cannot pass this proof without knowledge of the secret. This is
loopback-only source authentication/integrity, not independent host attestation
or protection from a fully compromised local user who can relay traffic.

## PowerShell console

From a Windows PowerShell terminal opened in a clone of this repository:

```powershell
.\vera.ps1
```

On first run the script creates a repository-local `.venv`, installs the current checkout into that environment, and opens the Vera Mono semantic console. No external LLM, model server, API key, or pretrained model is required.

The console is deliberately semantics-first rather than generator-first. Raw text is preserved, then mapped conservatively into a typed semantic/pragmatic interaction envelope. Exact commands are available immediately:

```text
:status
:tasks
:context
:capabilities
:identity
:meaning maybe show me the runtime status
:help
:exit
```

Natural-language aliases such as `what is your status?` are accepted when the mapping is explicit. Basic shell dialogue is also supported: `vera` acts as a direct invocation; `exit`, `quit`, `end`, `bye`, `/exit`, and `/quit` leave the console when entered as standalone controls; and `Who am I?` reports the human authority named by the governed project identity while explicitly not claiming keyboard authentication. Unrecognized prose is retained as `UNRESOLVED` rather than being silently reclassified as a command. The interpreter's reading is candidate meaning only: it does not establish truth, canon, memory admission, authorization, or an external effect.

The interactive semantic console displays replies on legacy Windows code pages
without failing when text contains unsupported Unicode characters. Such
characters display as backslash escapes (which can be ambiguous if the
original text contains literal escapes); a UTF-8 console keeps the characters.

A one-shot PowerShell call is also supported:

```powershell
.\vera.ps1 ":status"
```

Use `-Refresh` to reinstall the current checkout into the repository-local environment after source changes:

```powershell
.\vera.ps1 -Refresh ":identity"
```

For **explicit, opt-in local-model chat** from the same Windows launcher, provide
all five bindings and the existing loopback model endpoint. The launcher does
not choose or install a model, create a state identity, start Ollama, change
workstation permissions, or automatically turn an unrecognized console phrase
into a model request:

```powershell
.\vera.ps1 -Chat -StateRoot "C:\path\to\existing-state" `
  -ProjectId "<project-id>" -IdentityId "<identity-id>" `
  -Endpoint "http://127.0.0.1:11434/v1" -Model "gemma3:1b"
```

`-Chat` delegates to the separate `vera-mono chat --interactive` boundary;
the normal `.\vera.ps1` call still opens the **model-free semantic shell**.
When `-Chat` is selected, missing values, a nonexistent
`-StateRoot` directory, and shell-only arguments fail before environment
setup. The launcher checks directory existence only, not proof of a
qualified runtime or authenticated project/identity; those are
caller-provided and Python reconstructs the bounded lifecycle separately.
The launcher forwards literal process arguments (not evaluated shell commands), and the Python chat
boundary enforces exact numeric loopback, rejects tool calls, and makes no
memory admission. Chat remains **stateless and unverified by default**; each turn has no
previous dialogue context and cannot exercise Vera's provider, Bus, PC, or
protected-effect permissions. For an explicitly configured local API key, use
`-ApiKeyEnv VAR_NAME` with the secret stored only in the user's environment.
An optional `-EphemeralHistoryTurns 1` through `8` forwards bounded, process-local
prior conversation context. It is not durable memory, and it is cleared on exit.

Without state arguments the console is `SOURCE_ONLY`. To bind the PowerShell launcher to an existing `VeraStateDirectory`, use all three native PowerShell parameters together:

```powershell
.\vera.ps1 -StateRoot "C:\path\to\state" -ProjectId "<project-id>" -IdentityId "<identity-id>" ":status"
```

The launcher forwards those values to `vera-mono shell --state-root ... --project-id ... --identity-id ...`. State binding exposes read-only console inspection and does not mint protected-effect authority or silently write canonical memory.

## Optional local model advisory (not a Vera runtime route)

The separately invoked `vera-mono advise` command can ask an **already running**, operator-selected OpenAI-compatible model server on the same computer. It uses an exact numeric loopback URL, does not follow redirects or proxies, exposes no tools, and sends **only the explicitly provided prompt**—never Vera's current state, private memory, credentials, or task context. Its output is labelled `UNVERIFIED_MODEL_OUTPUT`; generation is not evidence of correctness, memory admission, runtime installation, a qualified model route, or protected-effect authority.

After installing this checkout as shown above, for an operator-owned Ollama instance:

```powershell
& .\.venv\Scripts\vera-mono.exe advise "Compare these explanations" --endpoint http://127.0.0.1:11434/v1 --model gemma3:1b
```

For a local endpoint requiring a bearer, put the key in a user-local environment variable and supply `--api-key-env NAME`. Do not put the key on the command line or commit it. Use `--json` for the bounded result/provenance envelope. No model is downloaded, started, selected for Vera, or granted authority by this command. The deterministic `shell` keeps its existing semantic and state-inspection behavior; free-form input is **not** silently escalated to a model or a tool.

### Synthetic local-model baseline (opt in)

`vera_core.local_model_evaluation` runs bounded, literal-match held-out probes
through the same read-only loopback advisory adapter. It reports machine-
readable observed outcomes, timing, and response hashes without raw responses.
For an installed checkout with an already running local server:

```powershell
& .\.venv\Scripts\python.exe -m vera_core.local_model_evaluation `
  --suite evaluations/local_vera_v1_heldout.jsonl `
  --endpoint http://127.0.0.1:11434/v1 --model vera-local:latest
```

The included prompts are synthetic. Do not add private chats or personal
identity material to this public evaluation file. A matching model alias is
**not** a cryptographically verified weight identity. Passing short exact-text
probes does not qualify reasoning, stable personality, persistent memory, Vera
installation, or effects. Keep these cases out of training data. Record model
digests, adapter identities, and generation settings separately before any
training comparison; the v1 runner establishes none of those bindings.

## Optional local-model transport (not activated by the console)

`vera_core.LocalOllamaProviderTransport` is an opt-in, host-injected
`ProviderExecutionTransport` for one explicitly selected Ollama tag and one
registry-reported SHA-256 digest at `127.0.0.1`. It supports only bounded
`GENERATE_CANDIDATE` requests. The host must bind provider ID `local-ollama`
to its current trusted provider verifier and trust registry, then use
`QualifiedVeraRuntime.prepare_provider_effect` and
`QualifiedVeraRuntime.execute_provider_effect`; the transport does not grant
itself dispatch authority. Restart/replay handling remains owned by the
qualified runtime's provider-effect fence and durable binding.

The response is always marked `UNVERIFIED_LOCAL_MODEL_CANDIDATE` with
`qualified=false`. Registry digests are self-reported metadata, **not loaded
weight attestation**; a same-user process that can call Ollama directly still
has a bypass outside this adapter. This source-only integration does not
select a model, start Ollama, modify `VeraMonoPilot`, configure OS ACLs, authorize
an external effect, or turn generated text into trusted instructions. The
semantic PowerShell console above remains model-free by default.

The transport also re-reads the selected tag's registry digest after generation
and refuses to return a candidate if the reported identity changed mid-call.
This is a consistency fence, **not** an atomic loaded-weight attestation: a
dishonest registry or change-and-change-back sequence remains outside its proof.

Synthetic loopback and governed-provider integration checks are in
`tests/test_local_ollama_provider_transport_unittest.py`. A production route
requires a separately controlled selected process identity, actual direct-route
denial, independent authority/claim custody, real model identity evidence,
and live restart/effect reconciliation. No source test can substitute for
those host qualifications.

## Opt-in local chat with bounded Vera context

`vera-mono chat` is a separate **one-shot by default** command, with an opt-in interactive mode that is stateless unless explicitly configured otherwise. It requires the exact existing Vera state root, project/identity binding, loopback inference endpoint, and model alias on every invocation. It constructs a `QualifiedVeraRuntime` from `VeraStateDirectory`, checks its reconstructed lifecycle, then sends only the allowlisted lifecycle status alongside the operator's prompt. It never serializes `resume_context()` into the model request: memory text, commitments, unfinished work, accepted runtime identifiers (including fingerprints), identity/project labels, host paths, keys, and provider/effect internals remain out of the prompt.

```powershell
& .\.venv\Scripts\vera-mono.exe chat "Help me understand the current state" `
  --state-root "C:\path\to\existing-state" --project-id "<project-id>" --identity-id "<identity-id>" `
  --endpoint http://127.0.0.1:11434/v1 --model gemma3:1b --json
```

For a local terminal conversation without putting each prompt in the process
command line, opt in to `--interactive` instead of supplying a positional prompt:

```powershell
& .\.venv\Scripts\vera-mono.exe chat --interactive `
  --state-root "C:\path\to\existing-state" --project-id "<project-id>" --identity-id "<identity-id>" `
  --endpoint http://127.0.0.1:11434/v1 --model vera-local:latest
```

Enter one prompt per line; use `:exit` or Ctrl+C/EOF to stop. Each turn is an
independent bounded request with freshly reconstructed allowlisted lifecycle
status. The CLI stores no transcript, carries no prior-turn context into the
next model request, and does not turn the local model into a qualified Vera
provider. `--json` emits one result object per completed turn (JSON Lines).
For optional context during **one running terminal session only**, add
`--ephemeral-history-turns 1` (maximum `8`); the oldest complete operator/model
pair is discarded when the turn or 4096-byte context budget is exceeded.
These are unverified prior texts, not trusted system instructions. The default
remains zero prior turns. No transcript file, model-weight update, or governed
memory admission is produced, and a new process starts with empty history.
The local inference server itself is separately operated; loopback routing
does not prove that server never logs, stores, or forwards prompts. Opting in
sends earlier private conversation text to that selected endpoint again.
On terminals using legacy Windows encodings such as cp1252, JSON output
uses ASCII Unicode escapes (still losslessly decoded by JSON consumers),
and plain-text output backslash-escapes characters the console cannot encode.
UTF-8 output streams retain literal Unicode replies. This only changes
display/serialization; it does not alter the model reply or its digest.
An interrupted in-flight call is marked delivery-unknown, not a successful
response. The bound state root must already exist; no default identity, state
directory, provider, or model is silently chosen.

`chat` uses the same bounded HTTP `/v1/chat/completions` adapter as `advise`. It sends no tool definitions, rejects model responses containing tool/function calls, never admits the exchange into Vera memory, and grants no provider, PC, Bus, or external filesystem effect authority. Opening a previously empty state directory can initialize QVR's local SQLite bookkeeping. Reconstructing an interrupted lifecycle can also repair local audit records or append `RESTART_RECONCILED_COMMITTED` to its lifecycle journal when a currentness commit is already durable but its final journal event is missing. These local recovery writes are not memory-item admission or authorization of an external effect. A missing binding, non-loopback address, unavailable model endpoint, or invalid QVR reconstruction fails without fallback. The output remains `UNVERIFIED_MODEL_OUTPUT`; even an accepted lifecycle status does not qualify the model, install it, or authorize its actions. Reinvocation after process restart reopens local state. `advise` remains intentionally state-free.

## Status

This is source architecture and local implementation. It does not, by source presence alone, claim deployment, provider activation, project installation, behavioral qualification, consciousness, phenomenology, or protected-effect authorization.
