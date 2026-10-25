# Local Vera model-training integration checkpoint — 2026-10-25

This is a **source/test/host inventory**, not a signed qualification, completed
weight update, or model-performance claim. The `D:\VERA` host root remains
authoritative; this change does not edit Lappy's old working copy.

## Phase 1 — Ingest to private training corpus

Source change: `tools/local_training/ingest_bridge.py` supplies explicit
`plan`/`export` operations. A private reviewer lists accepted Ingest IDs,
their normalized blob SHA-256, source-group IDs and per-example local-training
approval references. The exporter validates local owner-only storage, source
record status, raw/normalized CAS hashes, normalization and ready-receipt
digests, strict user/assistant JSON, duplicates and 16-MiB output limit.
It writes an exclusively created private 0600 JSONL file and prints only counts
and hashes. The existing `adapter_prep` then validates its separately
operator-authored manifest and produces group-disjoint train/evaluation sets.

Important limits:

- Ingest acceptance and self-hashed receipts are **not** independent source
  authenticity, human consent, truth, licensed reuse, or memory admission.
- A review reference is a declaration, not proof the named review happened.
- Semantic near-duplicate detection and review provenance authenticity are
  not independently qualified. Curators must inspect source groups and data.
- Private files, personal sample text, manifests, split files, and model
  artifacts are never committed or exported to GitHub.

## Phase 2 — actual host probe: HOLD

Observed through WorkBridge Commander on **Lappy**, using read-only commands:

| Check | Observation | Evidence class |
| --- | --- | --- |
| WSL distribution | Ubuntu-26.04, running under WSL 2 | Host probe |
| GPU | NVIDIA RTX 3050 Laptop GPU; 4,096 MiB total; compute 8.6 | Host probe |
| Free GPU memory | 2,219 MiB at probe time, **below runner's 3 GiB minimum** | Host probe |
| Default WSL Python | Python 3.14.4 | Host probe |
| Default WSL Python dependencies | No pip; `torch`, `transformers`, `peft` imports failed | Host probe |
| Trainable base/tokenizer/source | Not independently qualified as an owner-only, pinned original-format safetensors snapshot | Not established |
| Private approved corpus | No private operator-reviewed corpus presented to this run | Not established |

**Decision: `HOST_HOLD`.** These observations do not establish that *every*
WSL virtual environment or another computer lacks dependencies. Probe the
exact eventual interpreter after free-VRAM, private-filesystem, checkpoint,
and dependency conditions change. Do not count GGUF inference success as
training qualification.

## Phase 3 — bounded LoRA training: NOT RUN

No neural weights, identity state, memory state or runtime routing were changed.
Training remains disabled because Phase 2 fails, source/consent/model binding
is not independently qualified, and no exact `train-plan` approval digest
exists. A generic instruction to advance the project does not replace the
runner's exact model/dataset/output/step-bound approval.

After qualification: hold out entire source groups before training; capture
baseline model outputs, latency, failure modes, and memory-currentness scores;
generate an exact pinned one-step `train-plan`; obtain explicit matching
approval; train offline with the source-controlled runner; compare identical
held-out cases; perform SPM-style retrieved-memory/uncertainty checks and
LGCM-style predict/score-before-update stress tests. Do not activate an
adapter merely because loss decreases. Keep the candidate uninstalled until
independent behavioral review and rollback qualification pass.

The uploaded *Plasticity and State Governance* and *Hyperconnectome Runtime
Model* notes are conceptual design guidance, not implementation evidence:
training a model component is distinct from importing knowledge, writing
personal memory, or altering identity/authority state.
