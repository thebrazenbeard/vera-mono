# Mini-Vera zero-weight composition candidate V1

**Status:** source-only experimental request composer. No model inference,
installation, memory admission, service registration, personal identity transfer,
or model-weight training is performed by this implementation.

## Why this exists

The local `vera-successor:0.8b-context` tag has been observed by a separate
Lappy read-only worker as a small Qwen3.5 model with a system-message wrapper,
not a separately learned Vera. That host observation must be reverified before
use; this repository does not attest its current model bytes or running state.

A prompt wrapper can imitate a voice. It cannot, by itself, satisfy Vera's
governed state, currentness, provenance, correction, or qualified effect rules.
This candidate makes a narrower claim: *an external host can reproducibly
construct a local-model request from exact public Vera behavior-source bytes
and a bounded operator-supplied state snapshot.*

The public identity files are consumed as source data, **not** as proof of the
current installed native Project control release. A source-hash mismatch fails
closed. The host must independently resolve current release bindings and
supersession before supplying the expected hashes.

## Pure composition interface

`tools/mini_vera/compose.py` requires:

- Exact expected SHA-256 of checked-in `VERA_PROJECT_IDENTITY_V1.json` and
  `VERA_BEHAVIOR_PROFILE_V1.json`;
- A UTF-8 `MINI_VERA_OPERATOR_STATE_V1` object, exact revision, and a separate
  32-byte host integrity key;
- A synthetic `MINI_VERA_SYNTHETIC_TURN_V1` object, with `scope=SYNTHETIC_ONLY`;
- An explicit local model tag and 64-character, operator-declared registry digest;
- An output path that must not already exist.

The state HMAC covers the canonical JSON object excluding `hmac_sha256`. A
state record is allowed only if it declares `WORKING_PROJECT`, `PUBLIC`,
`DATA_NOT_INSTRUCTION`, and `authority_effect=NONE`, and its source hash matches
its text. Records are constrained to eight entries of at most 384 UTF-8 bytes.
They are labeled unverified context data in the model-facing request. The host
must authenticate the signer, source/provenance review, clock/currentness,
privacy, and admission separately; the mere presence of an HMAC does **not**
authenticate Patrick's permission or grant any authority. Replaying an older
snapshot with a matching caller-supplied revision is not prevented by the HMAC.

Output `MINI_VERA_COMPOSED_REQUEST_V1` includes:

1. A two-message, deterministic `inference` payload with a bounded projection
   of the checked public identity version, statement, temperament, objectives,
   behavior version and trait definitions, plus synthetic user/project-context
   JSON. A substantive projected source change alters request bytes; other
   unprojected source fields remain provenance only.
2. SHA-256 commitments to request bytes, public identity/profile, typed state,
   turn, and the declared model registry digest.
3. An evidence statement: `SOURCE_COMPOSED_ONLY`, `model_calls=0`,
   `memory_admission=NOT_PERFORMED`, `authority_effect=NONE`, and
   `behavioral_qualification=NOT_TESTED`.

`--model` is a label, not a verified checkpoint. The host must independently
pin the served model blob/digest, transport, sampling, and any Qwen thinking
mode setting; this composer does not call Ollama. Calling a model or executing a
provider effect must use `vera_core.QualifiedVeraRuntime` with its host-provided
verifier/trust/transport fence or a separately qualified experiment boundary.
Directly calling `LocalOllamaProviderTransport` is not a substitute.

## Adversarial and cross-process source tests

From a clean `vera-mono` source tree, run:

```sh
python -m unittest tests.test_mini_vera_composition -v
```

The thirteen fixture tests cover deterministic composition, source drift,
forged parsed-object substitution against authentic pinned raw bytes,
actual source-to-model request coupling for changed projected identity and
behavior traits, snapshot revision mismatch, HMAC tampering/wrong key, private/autobiographical
or effect-bearing record rejection, explicit data-not-instruction placement,
synthetic-only input, duplicate JSON rejection, and separate-process cold
recomposition. A stale record is rejected only when the host supplies a newer
expected revision; no external source of revision authority is provided here.

The fake-source and synthetic prompt tests do **not** show that an 0.8B model
will obey the hierarchy, correctly interpret context, remember information
without the host providing it, or produce Vera-consistent independent behavior.
Even JSON-quoted source text can influence a model as prompt injection, so the
model output remains untrusted and actionless without downstream policy gates.

## Required independent behavioral experiment

Compare, with a fixed exact model blob/seed/temperature/decoding policy:

1. Base Qwen3.5 0.8B without a Vera wrapper.
2. `vera-successor:0.8b-context` with its existing short system wrapper.
3. This composed request using **empty** project state.
4. This composed request using a valid, public synthetic project-state snapshot.
5. The same request after a new process cold-start using the same externally
   anchored revision; then deliberate stale, tampered, revoked, and contradictory
   snapshots.

Use blinded held-out prompts, counterbalanced arm order, group-level leakage
controls, and independent human/hostile semantics review. Report separately:
model-call receipts, response/latency effects, factual and project-currentness
accuracy, correction uptake, prompt-injection resistance, out-of-domain
generalization, the role of host-injected context, and what survives a process
restart with the source disconnected. Do not call a request SHA difference
learning. Do not treat a well-phrased first-person answer as identity transfer.

## Integration frontier

The production successor should replace this unqualified operator snapshot
with a **governed, currentness-bound read-only projection** from
`vera_memory.MemoryLedger` through `VeraStateDirectory`, preserving CAS heads,
privacy admission, supersession, revocation, and exact release-bound source
selection. Only the host may attach a real model/provider and separately
qualified tool/phone transport. Historical DeepMemory retrieval remains
evidence, not automatic autobiographical memory or present authority.

This proposal is compatible with Neuro-Sync's **Path C (zero-weight StateBus)**
as an explicitly mediated state transfer; no automatic ChatGPT→Ollama bridge is
installed or implied. It is deliberately **not** the Neuro-Sync weight-delta or
teacher-distillation path.
