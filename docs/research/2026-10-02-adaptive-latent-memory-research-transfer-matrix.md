# Adaptive Latent Memory Research and Transfer Matrix

Status: RESEARCH SYNTHESIS / SOURCE-BOUND DESIGN INPUT  
Date: 2026-10-02  
Primary implementation target: `vera-mono`  
Companion research targets: `mosaic`, `spm`, `rezon`, `lgcm`

## Problem

Large-model inference cost is not one thing. The relevant pressure surfaces include model weights, KV cache, activations/workspaces, prompt-prefill cost, and externally managed context/history. This work targets a family of related but separable mechanisms:

1. compress what units the expensive model computes over;
2. compress what historical state remains resident;
3. preserve exact backing information outside the compact active representation;
4. rehydrate only the detail required by a live task;
5. measure fidelity and resource savings separately.

The architecture must not report one kind of compression as proof of another. Reduced provider-visible context is not automatically reduced model weights or measured GPU memory. A lossy latent representation is not exact evidence.

## Research systems reviewed

### Byte Latent Transformer (BLT)

Source: https://arxiv.org/abs/2412.09871

Transferable mechanism:
- raw bytes can be grouped into dynamically sized latent patches;
- expensive model computation need not remain one-token-per-unit;
- information density can influence allocation of compute/resolution.

Do not infer:
- that Vera can modify a closed provider model;
- that BLT's patch representation can be dropped into an arbitrary pretrained Transformer without training.

### In-context Autoencoder (ICAE)

Source: https://arxiv.org/abs/2307.06945

Transferable mechanism:
- a long context can be represented by a smaller set of learned memory slots;
- compressed slots can directly condition a language model;
- compression should be evaluated on downstream usefulness, not only reconstruction.

Do not infer:
- that one fixed compression ratio is appropriate for every information class;
- that learned memory slots preserve exact source detail.

### Gist Tokens

Source: https://arxiv.org/abs/2304.08467

Transferable mechanism:
- reusable compact learned prompt state can replace repeatedly encoding a longer prompt;
- compact state may reduce repeated compute/storage.

Do not infer:
- that compression of stable instructions is equivalent to arbitrary episodic/history compression.

### Dynamic Memory Compression (DMC)

Source: https://arxiv.org/abs/2403.09636

Transferable mechanism:
- KV compression can be learned rather than fixed;
- appropriate compression ratio can differ by attention head and layer;
- model-internal compression requires model/runtime access and continued training.

Do not infer:
- that Vera's external context compression is equivalent to KV-cache compression.

### PyramidKV

Source: https://arxiv.org/abs/2406.02069

Transferable mechanism:
- useful retained context can differ by layer;
- uniform cache allocation across the network is not necessarily optimal;
- hierarchical information concentration motivates nonuniform resolution budgets.

Do not infer:
- that attention-selected cache retention is sufficient for exact evidence recovery.

### Latent Context Compilation

Source: https://arxiv.org/abs/2602.21221

Transferable mechanism:
- long context can be compiled into portable latent buffer tokens for a frozen base model;
- compact memory can be treated as an artifact separate from permanent model weights;
- fine-detail preservation must be tested explicitly at high compression.

Do not infer:
- that reported compression transfers unchanged to different models/tasks;
- that a latent buffer is exact source material.

### Cognitive Chunking / PIC

Source: https://arxiv.org/abs/2602.13980

Transferable mechanism:
- local/chunk-wise compression can be easier to train than indiscriminate whole-context compression;
- chunk structure offers natural units for selective later promotion.

Do not infer:
- that human-working-memory analogy establishes cognitive equivalence.

## Combined architecture

The cross-project hypothesis is:

```text
exact source/backing
        |
        v
local chunk / high-fidelity representation
        |
        v
compact semantic/predictive latent
        |
        v
aggressive abstraction
```

Consumers normally operate at the cheapest sufficient resolution. When a live reasoning or prediction task needs unavailable detail, the system issues a resolution fault and promotes only the implicated material.

Promotion must use a verified higher-resolution parent/backing object when an exact claim is required. A generative reconstruction may be useful as a hypothesis, but it cannot be labeled exact recovery merely because it is plausible.

## Repository ownership

### vera-mono

Owns:
- model-independent representation contracts;
- exact backing references and provenance;
- active/warm context budgeting;
- deterministic selective rehydration;
- provider-facing context assembly;
- fidelity/assurance boundaries.

Does not initially own:
- provider-internal hidden-state/KV compression;
- neural codec training.

### mosaic

Owns:
- parameter residency plus state residency accounting;
- cross-specialist compact handoff;
- end-to-end memory/latency/correction-burden experiments;
- empirical comparison of full history, structured state, multi-resolution state, and selective rehydration.

Key research claim to test:
A logical system can exceed currently resident model/state capacity without destroying continuity.

### spm

Owns:
- learned semantic/pragmatic latent representation;
- whether meaning-bearing state can be a primary computational coordinate system;
- compression-quality versus semantic/pragmatic fidelity experiments;
- later model-internal representations if evidence supports them.

Key research claim to test:
Semantic/pragmatic state can be denser and more useful than carrying equivalent token history.

### rezon

Owns:
- reasoning-triggered resolution faults;
- evidence-gap detection;
- selective promotion/retrieval planning;
- explicit failure when required resolution is unavailable.

Key research claim to test:
Reasoning can decide when compact state is insufficient without preloading all detail.

### lgcm

Owns:
- future predictive learned-compression experiment;
- whether a latent retains information useful under regime change and later recurrence;
- prequential evaluation of compression-induced forgetting.

Key research claim to test:
Compression can preserve future predictive utility rather than merely current reconstruction.

### noema

Deliberately untouched in this work.

Reason:
Noema currently preserves architectural independence from LLM/tokenizer/SPM assumptions. It is valuable as a later external falsifier: if a similar compression principle becomes useful there independently, that is stronger evidence than seeding the architecture into Noema now.

### hc-brain

Excluded by explicit owner correction for this workstream.

## Shared evaluation matrix

Every implementation/experiment should classify evidence along separate axes:

| Axis | Example measure |
| --- | --- |
| representation size | bytes, dimensions, tokens, slots |
| exact recovery | byte/text/source-bound correctness |
| semantic/task fidelity | downstream task success |
| correction burden | user/model corrections after compression |
| false reconstruction | plausible-but-unsupported recovered detail |
| rehydration cost | count, bytes/tokens, latency |
| active memory | host RAM and, when measured, GPU VRAM |
| compute | prefill/decode/forward latency or FLOPs proxy |
| persistence | restart/reload equivalence where relevant |
| generalization | changed queries/tasks/regimes after compression |

No one axis substitutes for another.

## Adversarial benchmark requirement

A compression benchmark must include "late relevance" cases:

1. information appears unimportant at compression time;
2. compressor produces a compact state;
3. later query makes the omitted detail decisive;
4. system must either rehydrate the exact backing detail or explicitly report insufficient fidelity.

This prevents the benchmark from rewarding a compressor that succeeds only because the evaluator asks predictable questions.

Additional cases:
- nearly identical identifiers;
- exact numeric values;
- code punctuation/whitespace where material;
- user correction/supersession;
- conflicting sources;
- stale compact state after source change;
- missing backing source;
- codec/version drift;
- prompt-injection-like text inside exact backing that must remain data rather than authority.

## Implementation order

1. Vera model-independent exact-backed multi-resolution substrate.
2. Rezon deterministic resolution-fault controller against that contract.
3. Mosaic deterministic residency/handoff comparison arm.
4. SPM benchmark and learned latent bottleneck experiment.
5. LGCM separately frozen learned predictive-compression experiment.
6. Only after measured wins: local/open-model KV or hidden-state compression experiments.

This ordering intentionally separates "can the semantics and recovery contract work?" from "can a neural codec reduce GPU state?" and prevents a large training run from becoming a prerequisite for basic falsification.
