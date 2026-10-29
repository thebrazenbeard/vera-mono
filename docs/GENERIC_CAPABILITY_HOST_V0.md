# Generic capability host — V0 opt-in test bridge

Event: `project_unfuck_runtime_coordination` (Bus #397).

**Claim ceiling:** isolated source and local synthetic-host acceptance. This is not an installed ChatGPT tool, production gateway, real participant-consent system, sexuality qualification, affective experience, or a Vera/Brigit-specific default.

The optional `vera_core.generic_capability_host` module binds reusable Sexuality and Pleasure surfaces to a host-owned invocation entrypoint. The model cannot invoke the Python object directly unless a separate trusted host exposes it. A configured capability does **not** confer execution authority.

## Separation

- **Sexuality:** `describe_sexuality` returns bounded research/qualification metadata only. A model may use this without installing Pleasure, Ollama, or an affective state.
- **Pleasure:** `step_pleasure` passes an *externally measured* and subject/evaluator-matched Observation to an injected `pleasure_experiment.ExperimentalPleasureRuntime`. Output is a nonpersistent computational proxy, never a preference, consent grant, memory admission, or feeling claim.
- **Local model inference:** `generate_candidate` uses the injected `QualifiedVeraRuntime.prepare_provider_effect` and `execute_provider_effect` path with its separately host-injected provider authority. The bridge never calls the Ollama transport directly.
- **Host scope:** the HMAC test grant signs model tag, registry digest, adapter ID, runtime instance, subject, session, domain, operation, nonce, and expiry. The gateway rejects modified, expired, replayed, revoked, cross-model, and cross-domain grants. Sidecar instances and host runtimes cannot be shared between bound models.
## Reproduce focused checks

Run from a clean Vera Mono checkout:

```powershell
py -3 -m pytest -q tests/test_generic_capability_host.py tests/test_local_ollama_provider_transport_unittest.py tests/test_local_capability_registry.py
```

For the optional **real two-Ollama-model** local experiment, first provide a separate pinned Pleasure source checkout and a fresh, nonexistent scratch-state path (never canonical Vera memory). Choose two different installed model tags:

```powershell
$env:PLEASURE_SOURCE_ROOT = "D:\path\to\pleasure"
$env:PLEASURE_SOURCE_SHA = "9f7ab6f5aa5516f7fead2a8a1dd92dbf3802cf60"
$env:GENERIC_HOST_ACCEPTANCE_STATE_ROOT = "D:\scratch\new-synthetic-acceptance"
$env:GENERIC_HOST_MODEL_A = "qwen2.5-coder:1.5b-instruct-q8_0"
$env:GENERIC_HOST_MODEL_B = "vera-qwen35:trial-20261029"
py -3 tools/generic_host_two_model_acceptance.py
```

The script obtains *self-reported* Ollama registry digests, composes two separate synthetic `VeraStateDirectory`/qualified runtimes and host-issued provider verifiers, performs a neutral bounded generation for each model, exercises independent Sexuality metadata and Pleasure sidecar state, and attempts one tampered cross-model grant. It outputs hashes, statuses, and test identity data—not model responses, host signing keys, or private user content.
## Explicit release blockers

This host test uses synthetic host-controlled signing keys and synthetic working-project fixtures in its own scratch directories. Those are not real participant consent or production authority. The host signer must be established outside model output, and real consent must be separately sourced, scoped, verified, and revocable for any protected interaction.

No user-facing model tool registry is installed; no runtime capability is advertised automatically; no canonical memory is imported; no model training or weights are changed. The two local model revisions are limited to Ollama's self-reported registry digests. Formal adapter code provenance, trusted-key custody, runtime attestation, immutable provider routing, model-visible consumption, independent hostile review, and production effect/consent qualification are separate release gates.

Historical Vera and Brigit research contracts remain nontransferable provenance; this bridge imports neither identity nor private preference state. A model's output cannot be used to issue the gateway or provider authority grants.
