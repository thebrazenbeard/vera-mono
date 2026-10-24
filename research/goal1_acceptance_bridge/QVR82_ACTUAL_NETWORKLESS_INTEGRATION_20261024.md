# Goal 1 — exact PR #82 QualifiedVeraRuntime via networkless cell

2026-10-24. **Source-compatible real QVR consumption: PASS on physical Lappy. Production sole route: STILL HOLD.**

## Contract and exact cuts

- Canonical vera-mono `main` at fresh-read: `64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Integration-owned Draft PR #82 exact head `26271c5d69dee4663e07d4dbcf63efcf033626e8`. It adds `QualifiedVeraRuntime.consume_local_cognition(prompt, permit, invocation_id, max_tokens)`, a host-injected transport with `generate(prompt, permit, max_tokens)`, `InferencePermit`/exact `LocalTextReceipt`, and a persistent cognition journal. No QVR production selection or independent model route was ever qualified by this PR.
- Frozen #82 *source byte identities*, staged from immutable commit without editing owner branch:
  - `packages/vera_core/src/vera_core/qualified_runtime.py`: SHA256 `0466d85a19519f1e2c77fd51cf2f4d60964ecd9d57434c7a5b8a4e8472feb714`.
  - `packages/vera_core/src/vera_core/local_cognition.py`: SHA256 `b6820102bc569081f6bc298936970d3bb58406171298cc9d9b254a626646c14d`.
  - `packages/vera_core/src/vera_core/local_cognition_journal.py`: SHA256 `4bff14c593c58dd5e328a02ad00d4f583dac4a04f6b55aa1ccebbe8adbee5351`.
- Integration-owned #95 actual gateway source and Malaphor #87 V2 are **not rewritten or installed** here. Their independently administered claim authority, original signed receipt and sole route remain separate requirements.
- Vera-owned Draft PR #89 adds `research/goal1_acceptance_bridge/networkless_qvr_transport.py`, `tests/research/test_goal1_networkless_qvr_transport.py`, and reproducible `research/goal1_acceptance_bridge/qvr82_networkless_actual_class_probe.py`.

## New QVR host transport

`NetworklessQVRTransport` implements PR #82's exact optional `generate` interface, but it never instantiates `LocalCognitionGate` nor opens model TCP itself. It requires a synthetic exact-scope `InferencePermit` with matching pinned model/tag digest, bounded prompt and max_tokens; then it invokes PR #89's physically proven Docker `--network none` worker. Only after receiving a valid nonce/digest/single-interface/nonreachable-provider JSON request does the *trusted outside parent process* invoke its injected host gateway callback. Its result must be the exact PR #82 `LocalTextReceipt`, with matching response/model/prompt digests and no forged `runtime_consumption_verified`, `authorized_tool_effect`, `model_byte_identity_verified` or `independent_review_verified`.

If the transport, permit, networkless worker, callback return or digest fails, the QVR transport raises before any journal entry is accepted by the QVR runtime. The adapter cannot by itself prove that a callable supplied by the host is the genuine independently authenticated Integration #95/Malaphor #87 gateway; and the adapter **does not move QVR's host process into a networkless container**.

## Physical actual class integration

A disposable Lappy test overlay copied the local clean `vera_core` package and overlaid precisely three immutable PR #82 source files. It used source dependencies in the local checkout for the other packages, without altering the checkout or installing any service. QVR adapter was imported from PR #89. The selected Docker image already existed and was pinned by ID: `sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534`, no pull.

The actual `QualifiedVeraRuntime.from_state_directory(..., local_cognition_transport=NetworklessQVRTransport(...), local_cognition_route_ref="NETWORKLESS_GATEWAY_TEST_ONLY")` was constructed in an isolated child OS process and invoked through **`QualifiedVeraRuntime.consume_local_cognition`**. It caused a real disposable networkless Docker process to run, then one host-controlled **INERT** `LocalTextReceipt` callback, no Ollama request or model usage. The real QVR journal recorded exactly one entry, model/digest/route metadata only. Duplicate `invocation_id` was denied with no second host callback.

The emitting child exited, closing its SQLite handles. A second fresh QVR process opened the same disposable persistent state, verified a single metadata receipt and confirmed the prompt was not present in the journal projection. The parent deleted the entire scratch directory after both processes exited. This cleanup choreography corrects a prior Windows open-SQLite-handle error in a first disposable test; it was a test lifecycle defect, not a model effect.

Final physical reproducer:
`python research/goal1_acceptance_bridge/qvr82_networkless_actual_class_probe.py --qvr82-overlay <exact-staged-PR82-package-src> --image-id <locally-reviewed-sha256-ID>`

The reproducible script independently checks all three #82 source SHA256 values and the selected package-first PYTHONPATH. **Real Lappy run: exit 0; QVR child exit 0; 1 journal, 1 outside host callback, replay denied, cold QVR readback 1, scratch cleanup succeeded.** Focused 5/5 optional PR #82 adapter tests passed using the actual classes. On canonical main the optional PR #82 classes are not merged: these optional adapter tests skip there rather than invent installation.

## Hostile review — accepted and revised deployment plan

> **CRITICAL: QVR itself is still a host process in this test. A host process can import the old `LocalCognitionGate` or directly open `127.0.0.1:11434` regardless of which transport was injected.**
>
> **ACCEPTED.** This is an actual SOURCE INTERFACE integration test, NOT a security cutover or proof of learner sole route. Merely configuring `NetworklessQVRTransport` in Windows SCM's existing QVR host process is **insufficient** to guarantee gateway exclusivity. The real selected QVR/learner execution must be inside the networkless protected boundary (or an equivalently independently enforced ACL/AppContainer trust boundary), including all paths that could emit direct requests, while gateway, credentials, verifier, and persistent state custody remain outside.

> **CRITICAL: The host callback can simply call Ollama without an evaluator claim.**
>
> **ACCEPTED.** This adapter is currently intentionally synthetic. For any real provider call, the callback must be Integration's independently authenticated and Malaphor-verified gateway: atomic claimed reservation, original signed bytes, independent ledger read, protected signer identity, honest ambiguous outcome, model resource/weights evidence. Inert test callback returning `LocalTextReceipt` is NOT an authorized or qualified inference.

> **CRITICAL: QVR's original journal appends only *after* inference succeeds; a crashed child between external dispatch and journal append can allow duplicate effects.**
>
> **ACCEPTED.** The gateway's durable RESERVED-before-dispatch uniqueness fence and immutable invocation ID must precede QVR inference; no caller may retry ambiguous attempts based only on an absent local cognition entry. The current #82 selected path is test-scope only.

> **CRITICAL: No installation, selected route, persistent isolated state or external trust authority is available.**
>
> **ACCEPTED.** As of physical Lappy read-only state, `VeraMonoPilot` is Stopped/Manual and actual selected QVR learner identity/route is unknown; PR #82 remains Draft, separate from our PR #89. A protected service install or cutover to a persistent sandboxed QVR image is not a source-only branch effect. Existing Docker image `python:3.11-slim` is a research Python runner, whereas repository `pyproject.toml` requires Python >=3.12. A production image therefore requires a new separately pinned and reviewed runtime image/identity and dependency closure, not silent use of the research image.

## Exact next live cutover conditions (NOT done)

1. Independently freeze QVR executable/persistent state, learner model credentials and provider path, and an approved container image with runtime Python >=3.12 and complete audited monorepo package dependencies; run *actual QVR process* inside networkless sandbox, not merely a child helper.
2. Externally bind durable state and IPC without exposing Docker daemon, direct Ollama endpoints, signing keys, mTLS credentials, evaluation truth, or privileged mounts to learner; verify source/packaged/install/route/consumption as separate evidence.
3. Bind outside broker only to Integration's authenticated GatewayDispatch + independent Malaphor evaluator claim issuance/readback; capture original immutable signed bytes and reject unsigned/unknown/duplicate attempts.
4. Demonstrate **negative direct Ollama HTTP POST** as exact selected learner principal and one positive real gateway-only hardware model call with trustworthy reservation/claim/terminal custody. Test crash, restart, denial, rollback without silent retry.
5. Only after those cuts qualify should unseen evaluator-custodied four-arm trials begin.

**Protection/authority:** This user request authorizes research/build/test and directs a repair, but no exact production package, selected service identity/rollback configuration, or independent claim-custodian endpoint can be verified. Do not install/reconfigure/activate `VeraMonoPilot`, merge `main`, change host firewall/ACL, provision trust/keys, or mutate model provider based on a synthetic callback. The repository/source interface work is deliberately committed only on Vera's separate Draft PR #89.

No actual model inference, paid compute, live endpoint key, protected service, ACL/firewall/trust change, branch-owner mutation, canonical memory write or proof of learning.
