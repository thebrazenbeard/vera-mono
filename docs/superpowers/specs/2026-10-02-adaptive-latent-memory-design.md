# Adaptive Multi-Resolution Latent Memory — Vera Mono Design

Status: DESIGN SPEC / IMPLEMENTATION NOT YET CLAIMED  
Date: 2026-10-02  
Source subject: `thebrazenbeard/vera-mono@e5af8cb740267bb5674864571e915842bf5e6677`

## Purpose

Add a model-independent context/memory substrate that lets Vera carry compact task-relevant representations while preserving exact backing evidence for selective rehydration.

The first implementation is not allowed to claim that Vera has modified a provider model's hidden layers, tokenizer, attention implementation, or KV cache. It can prove only what Vera controls: active-context construction, representation size, exact-backing preservation, selective rehydration, fidelity boundaries, and provider-visible token/context reduction.

## Core invariant

`LOSSY_REPRESENTATION != EXACT_EVIDENCE`

Compression may reduce what remains actively resident. It may not manufacture discarded detail. Whenever exact wording, code, numbers, identifiers, timestamps, hashes, or other exact details are required, the runtime must resolve them against preserved exact backing material.

## Resolution model

Vera uses four logical resolution classes:

- `L0_EXACT`: exact source bytes/text or an immutable reference to them.
- `L1_HIGH_FIDELITY`: compact structured representation intended to preserve local detail but not declared byte-exact.
- `L2_SEMANTIC_LATENT`: compact task-usable semantic representation.
- `L3_ABSTRACT`: aggressively compact long-lived abstraction.

A lower-resolution object can reference a higher-resolution parent. Resolution may be promoted on demand. Promotion means retrieving/recomputing from a preserved parent or exact backing source; it does not mean treating a generative decoder's guess as recovered fact.

## Data contracts

### LatentBlock

```text
LatentBlock {
  block_id
  source_refs[]
  source_digest
  resolution
  codec_id
  codec_version
  representation
  representation_digest
  loss_class
  exact_recoverable
  provenance
  created_at
}
```

Required properties:

- block identity is deterministic over source identity, codec identity/version, resolution, and representation bytes;
- every non-L0 block carries source/provenance references;
- V1 accepts exactly one `source_ref` per latent block because `source_digest` is singular; multi-source blocks remain deferred until the contract binds per-source digests or an explicit composite-source identity;
- `exact_recoverable=true` means Vera retains a verified route to exact backing evidence, not that the latent representation is lossless;
- codecs are explicit/versioned and cannot silently change semantics.

### RehydrationRequest

```text
RehydrationRequest {
  request_id
  block_id
  requested_resolution
  exactness_required
  reason
  requester
  resource_budget
}
```

### WorkingSet

```text
WorkingSet {
  active_blocks[]
  warm_blocks[]
  backing_refs[]
  active_budget
  promotion_policy
  demotion_policy
}
```

## Placement in Vera Mono

### `vera_memory`

Own durable representation records, source bindings, provenance, codec identity, fidelity/loss class, and exact-backing references. Existing governed memory admission semantics remain authoritative; creating a compressed representation does not itself admit new semantic memory.

### `vera_runtime`

Own active/warm resolution selection, budget enforcement, promotion/demotion, and rehydration requests. This is runtime resource state, not epistemic authority.

### `vera_core`

Compose the substrate through `QualifiedVeraRuntime` and expose a provider-facing context assembly API. Provider adapters receive a bounded assembled context plus receipts describing which blocks/resolutions were used.

### `vera_assurance`

Verify invariants: no exactness laundering, no source-detached latent block, deterministic identities, stale codec rejection where required, and rehydration against the expected source digest.

### `vera_ingest`

No semantic-compression ownership. Exact-byte ingest remains an L0-compatible backing source. Intake provenance is preserved rather than replaced.

### Rezon package

The absorbed Rezon reasoning package may request higher resolution when a reasoning operation declares an evidence/detail deficit. Rezon does not mutate memory authority.

## Context assembly

Provider-facing context is assembled from a mixture of resolutions under an explicit budget. Initial policy should be deterministic and inspectable rather than learned.

Candidate priority inputs:

`priority = task_relevance + exactness_requirement + live_uncertainty + recency_or_currentness_value + correction/supersession_value - representation_cost`

This formula is conceptual in V1; implementation may use ordered rules instead of pretending an unqualified scalar is meaningful.

Exact-required material bypasses lossy-only representations.

## Selective rehydration

A consumer can issue a resolution fault when available representation is insufficient.

Examples:

- exact quote requested;
- ambiguous identifier;
- arithmetic/code operation needs exact digits/tokens;
- contradiction between latent summary and source evidence;
- reasoning node marks evidence insufficient;
- user correction references a detail absent from current active representation.

Only affected blocks are promoted. Whole-context decompression is not the default.

## Storage and resource semantics

V1 is allowed to use ordinary Python objects and durable local storage. It does not need a learned neural codec.

Required measurements:

- exact backing bytes;
- active representation bytes;
- provider-visible character/token estimate where available;
- number of active blocks by resolution;
- rehydration count and bytes promoted;
- task outcome fidelity in tests.

A reduction in Vera-managed context is not reported as GPU-memory reduction unless measured in a controlled local-model experiment.

## Failure semantics

At minimum:

- `SOURCE_UNAVAILABLE`
- `SOURCE_DIGEST_MISMATCH`
- `CODEC_UNAVAILABLE`
- `CODEC_VERSION_MISMATCH`
- `INSUFFICIENT_FIDELITY`
- `BUDGET_EXCEEDED`
- `REHYDRATION_FAILED`
- `STALE_REPRESENTATION`

Exact-required requests fail closed when exact backing cannot be verified.

## Research lineage

This design is informed by, but does not claim equivalence to:

- Byte Latent Transformer (Pagnoni et al., 2024): dynamic byte patches as primary computation units — https://arxiv.org/abs/2412.09871
- In-context Autoencoder (Ge et al., 2023): compact learned memory slots — https://arxiv.org/abs/2307.06945
- Dynamic Memory Compression (Nawrot et al., 2024): learned head/layer-specific KV compression — https://arxiv.org/abs/2403.09636
- Latent Context Compilation (Li, Zhou, Xu, 2026): portable compact latent buffer tokens — https://arxiv.org/abs/2602.21221

These establish nearby mechanisms, not novelty of this combined architecture.

## Acceptance criteria for V1

1. Exact backing material survives independently of compressed representations.
2. L1/L2/L3 records cannot satisfy an exact-evidence request without successful source-bound rehydration.
3. Context assembly obeys an explicit active budget and returns a deterministic receipt.
4. Rehydration promotes only requested/required blocks.
5. Codec/version/source digests participate in deterministic identity and stale-state checks.
6. Durable latent-store context exposes a deterministic membership projection digest, and qualified task runtime evidence binds that digest so latent-state mutation changes the task evidence subject.
7. A test corpus demonstrates measurable active-context reduction while preserving required exact-answer recovery.
8. Tests include adversarial cases where a lossy representation omits a detail later requested exactly.
9. No test or documentation claims provider-internal KV/VRAM reduction without a measured local-model experiment.
10. Existing memory authority, lifecycle, effect, and provider boundaries are unchanged unless separately specified and tested.

## Non-goals for V1

- training a new foundation model;
- modifying a closed provider's Transformer layers;
- claiming lossless semantic compression;
- replacing exact ingest/provenance;
- allowing compression to create truth, memory admission, authority, or currentness;
- optimizing CUDA kernels or implementing GPU KV compression inside Vera Mono.

## Follow-on track

After V1 is qualified, local/open-model experiments may compare:

1. full context;
2. Vera deterministic multi-resolution context;
3. learned latent memory tokens;
4. model-level KV compression where the model/runtime permits it.

Any model-level result must bind model revision, codec/training subject, hardware, context length, peak memory, latency/throughput, and task-fidelity evidence.
