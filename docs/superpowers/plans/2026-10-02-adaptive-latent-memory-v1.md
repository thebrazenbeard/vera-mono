# Adaptive Multi-Resolution Latent Memory V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Vera Mono's first exact-backed multi-resolution context substrate with deterministic selective rehydration, provider-facing context assembly, and assurance that lossy representations never impersonate exact evidence.

**Architecture:** Durable representation records live beside, not inside, governed semantic-memory admission. Runtime code chooses active resolution under an explicit byte budget and selectively promotes only required blocks from verified backing bytes. `QualifiedVeraRuntime` exposes the composed substrate while existing memory, lifecycle, authority, provider, and effect boundaries remain unchanged.

**Tech Stack:** Python 3.12+, stdlib dataclasses/enum/sqlite3/hashlib/json, existing `portfolio_runtime.lantern.canonical` canonical JSON/digest helpers, pytest.

**Spec:** `docs/superpowers/specs/2026-10-02-adaptive-latent-memory-design.md`

## Global Constraints

- `LOSSY_REPRESENTATION != EXACT_EVIDENCE`.
- Exact-required requests fail closed unless exact backing bytes are verified against the bound source digest.
- Compression creates no truth, currentness, semantic-memory admission, authority, permission, or effect.
- V1 does not claim provider-internal tokenizer, hidden-state, KV-cache, or GPU-memory modification.
- No new runtime dependency is required.
- Existing qualified lifecycle/effect/provider boundaries remain unchanged.
- Deterministic identifiers bind source identity/digest, codec identity/version, resolution, and representation bytes.

## Review Focus

- A lossy block omits a detail later requested exactly: only verified backing bytes may satisfy the request.
- Backing bytes differ from the bound source digest: rehydration must fail closed before context assembly succeeds.
- Two blocks exist but only one needs promotion: the backing loader must be invoked only for that block.
- A compact or exact promotion exceeds the active budget: assembly must reject rather than silently truncate exact-required material.
- Codec/source metadata changes while representation bytes remain the same: block identity must change and stale identity must not alias.

---

### Task 1: Durable latent representation records

**Files:**
- Create: `packages/vera_memory/src/vera_memory/latent.py`
- Modify: `packages/vera_memory/src/vera_memory/__init__.py`
- Test: `tests/test_latent_memory.py`

**Interfaces:**
- Produces: `Resolution`, `LossClass`, `LatentBlock`, `LatentMemoryStore`, `LatentMemoryError`.
- `LatentBlock.create(...)->LatentBlock` computes deterministic identity.
- `LatentMemoryStore.put(block)->LatentBlock`, `get(block_id)->LatentBlock`, `all()->tuple[LatentBlock,...]`, `context()->dict[str, object]`.

- [ ] Write failing tests for deterministic identity, metadata-sensitive identity, durable round-trip, forged identity rejection, and exact-recoverable/source-reference validation.
- [ ] Run `pytest tests/test_latent_memory.py -q`; expected FAIL because the module does not exist.
- [ ] Implement the minimal dataclasses/enums and SQLite store.
- [ ] Run `pytest tests/test_latent_memory.py -q`; expected PASS.
- [ ] Commit.

### Task 2: Resolution requests and exact-backed rehydration

**Files:**
- Create: `packages/vera_runtime/src/runtime_cohesion/latent_context.py`
- Modify: `packages/vera_runtime/src/runtime_cohesion/__init__.py`
- Test: `tests/test_latent_context.py`

**Interfaces:**
- Consumes: Task 1 `LatentBlock`, `Resolution`.
- Produces: `RehydrationRequest`, `RehydrationResult`, `ContextCandidate`, `ContextAssemblyReceipt`, `LatentContextError`, `rehydrate_exact(...)`, `assemble_context(...)`.
- `backing_loader(source_ref: str) -> bytes` is host-injected and read-only.

- [ ] Write failing tests for exact-detail recovery, source-digest mismatch, selective single-block loading, no loader call for sufficient compact state, and budget failure.
- [ ] Run `pytest tests/test_latent_context.py -q`; expected FAIL.
- [ ] Implement deterministic promotion and context assembly using an explicit ordered priority tuple rather than an unqualified scalar score.
- [ ] Run `pytest tests/test_latent_context.py -q`; expected PASS.
- [ ] Commit.

### Task 3: Assurance boundary

**Files:**
- Create: `packages/vera_assurance/src/vera_assurance/latent_memory.py`
- Modify: `packages/vera_assurance/src/vera_assurance/__init__.py`
- Test: `tests/test_latent_memory_assurance.py`

**Interfaces:**
- Consumes: Task 1 records and Task 2 receipts.
- Produces: `LatentAssuranceFinding`, `LatentAssuranceReport`, `audit_latent_blocks(...)`, `audit_context_receipt(...)`.

- [ ] Write failing tests that detect lossy-as-exact laundering, source-detached records, receipt byte-count inconsistency, and accept successful exact-backed assembly.
- [ ] Run focused assurance tests; expected FAIL.
- [ ] Implement deterministic checks with no mutation or authority effect.
- [ ] Run focused assurance tests; expected PASS.
- [ ] Commit.

### Task 4: Compose into Vera state and QualifiedVeraRuntime

**Files:**
- Modify: `packages/vera_core/src/vera_core/state.py`
- Modify: `packages/vera_core/src/vera_core/qualified_runtime.py`
- Modify: `packages/vera_core/src/vera_core/__init__.py`
- Test: `tests/test_qualified_runtime.py`
- Create: `tests/test_latent_runtime_composition.py`

**Interfaces:**
- Adds `VeraStatePaths.latent_memory` at `memory/latent.sqlite`.
- Adds `VeraStateDirectory.latent_memory_store()->LatentMemoryStore`.
- Adds `QualifiedVeraRuntime.latent_memory`.
- Adds `QualifiedVeraRuntime.assemble_latent_context(candidates, *, active_budget_bytes, backing_loader)->ContextAssemblyReceipt`.

- [ ] Write failing tests for restart persistence, runtime composition, and unchanged governed memory-head semantics.
- [ ] Run focused tests; expected FAIL.
- [ ] Wire the store into state-directory and qualified-runtime construction and resume context.
- [ ] Run focused tests; expected PASS.
- [ ] Commit.

### Task 5: Late-relevance falsification corpus and measurement

**Files:**
- Create: `tests/fixtures/latent_context_cases.json`
- Create: `tests/test_latent_context_benchmark.py`
- Create: `scripts/measure_latent_context.py`
- Modify: `README.md`

**Interfaces:**
- Produces deterministic measurement JSON with source bytes, active bytes, rehydration bytes/count, exact-recovery result, and claim ceiling `VERA_MANAGED_CONTEXT_ONLY_NOT_GPU_VRAM`.

- [ ] Add cases for late-relevant color/number/code identifier, correction/supersession, conflicting source, missing backing, and irrelevant bulk text.
- [ ] Run benchmark test before the measurement helper; expected FAIL.
- [ ] Implement the measurement helper with no provider/network calls.
- [ ] Run all new latent-memory/context/assurance/composition/benchmark tests; expected PASS.
- [ ] Run `python scripts/measure_latent_context.py tests/fixtures/latent_context_cases.json`; retain exact output in a source-bound result artifact.
- [ ] Commit.

### Task 6: Full Vera Mono regression and packaging verification

**Files:** modify only if regressions attributable to this feature require fixes.

- [ ] Run the complete repository test suite.
- [ ] Build the wheel using the repository's existing build path.
- [ ] Inspect failures and repair only feature-caused regressions.
- [ ] Re-run complete tests and wheel verification.
- [ ] Record exact branch head and command/results; do not promote source/build PASS into installation/runtime/behavior PASS.

## Cross-repo continuation after Vera V1

After Vera Task 6 passes:

1. Rezon: implement typed `ResolutionFault` and deterministic selective-promotion planning.
2. Mosaic: add `MULTI_RESOLUTION_STATE` and `MULTI_RESOLUTION_REHYDRATE` P1 conditions and state-residency accounting.
3. SPM: add a separately frozen semantic-latent compression benchmark/training subject without modifying existing qualified adapter evidence.
4. LGCM: add only the separately frozen future predictive-compression experiment; do not modify LGCM-0 qualification semantics.
5. vera_model_training: preserve PR #70 as the training-strategy branch and add executable proxy/late-relevance exercises only after Vera's V1 contract is stable.
