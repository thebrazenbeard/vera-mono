# Vera Semantic PowerShell Console V1 Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a cloned `vera-mono` repository directly interactive from PowerShell through a Vera-native semantic/pragmatic console without requiring an external LLM.

**Architecture:** Raw terminal text is preserved first, then projected into a typed interaction envelope containing speech act, target, modifiers, provenance, ambiguity, and semantic-transfer fidelity. The console resolves only bounded, evidence-backed operations against repository identity and optional `QualifiedVeraRuntime` state; unknown natural language remains explicit rather than being hallucinated into a command. Existing Vera effect/authority boundaries remain downstream of interpretation.

**Tech Stack:** Python 3.12, argparse, dataclasses/enums, existing `vera_core`, `vera_identity`, `rezon`, pytest, PowerShell.

## Global Constraints

- PowerShell is a first-class entry surface.
- No external LLM, model server, API key, or pretrained model is required.
- SPM principle: meaning-in-context is represented before response/action selection.
- Semiotics principle: multiple context-compatible readings may remain live; specificity is not truth.
- Semantic Atlas principle: proposition type, provenance, currentness, interpretation, and authority remain separate.
- Rezon principle: reasoning, lifecycle state, and effect state are typed and do not silently promote.
- SQL Connectome principle: surface parsing/translation is not semantic equivalence or execution authority.
- Noema principle: communication input and diagnostic interpretation are distinct channels; hedges/uncertainty do not automatically weaken an entire utterance.
- LGCM contribution is limited in V1 to an explicit future adaptation hook; no continual-learning dependency is introduced.
- Canonical memory is not written by the console unless a later explicit authorized path is added.
- Protected effects remain gated by existing `QualifiedVeraRuntime` authority machinery.
- Source-only operation must work when no live Vera state directory is bound.

---

### Task 1: Add typed interaction semantics

**Files:**
- Create: `packages/vera_core/src/vera_core/interaction_semantics.py`
- Modify: `packages/vera_core/src/vera_core/__init__.py`
- Test: `tests/test_interaction_semantics.py`

**Interfaces:**
- Consumes: exact input text plus optional previous interaction id.
- Produces: `InteractionEnvelope`, `InterpretationCandidate`, `SpeechAct`, `InteractionTarget`.

- [ ] **Step 1: Add the focused failing test**

Cover exact colon commands, natural-language aliases, correction binding, local hedge capture, ambiguous targets, raw-text preservation, and unknown free-form statements.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_interaction_semantics.py`
Expected: import/module failures proving the semantic layer is absent.

- [ ] **Step 3: Implement the minimum behavior**

Implement deterministic interpretation with no probabilistic confidence. Preserve raw text and evidence cues. Exact console commands receive `EXACT` fidelity; recognized natural-language aliases receive `CONSTRUCTIVE`; partial speech-act-only readings receive `LOSSY`; incompatible simultaneous control targets remain `UNREPRESENTABLE` and unresolved. Every envelope carries `authorization_effect="NONE"`.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_interaction_semantics.py`
Expected: all interaction semantic tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_semantic_transfer.py tests/test_semantic_transfer_catalog.py tests/test_interaction_semantics.py`
Expected: existing semantic-transfer tests and new interaction tests pass together.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add packages/vera_core/src/vera_core/interaction_semantics.py packages/vera_core/src/vera_core/__init__.py tests/test_interaction_semantics.py
git commit -m "feat: add typed interaction semantics"
```

### Task 2: Add Vera-native console dispatcher

**Files:**
- Create: `packages/vera_core/src/vera_core/console.py`
- Modify: `packages/vera_core/src/vera_core/cli.py`
- Test: `tests/test_console.py`
- Test: `tests/test_cli_console.py`

**Interfaces:**
- Consumes: `InteractionEnvelope`, governed identity resources, optional `QualifiedVeraRuntime`.
- Produces: `ConsoleResponse` and interactive `vera-mono shell`.

- [ ] **Step 1: Add the focused failing test**

Cover source-only greeting/identity/help, exact status/context/task inspection with bound runtime, `:meaning` diagnostics, correction linkage, unknown-language unresolved response, one-shot mode, piped stdin, and interactive exit.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_console.py tests/test_cli_console.py`
Expected: missing console interfaces.

- [ ] **Step 3: Implement the minimum behavior**

Create a process-local session. Known targets render repository/runtime facts; `:meaning <text>` renders the semantic envelope separately from Vera-authored response text. Unknown language is preserved and reported as unresolved rather than guessed. State binding remains all-or-none through `--state-root --project-id --identity-id`. No console path writes canonical memory or executes protected effects.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_console.py tests/test_cli_console.py`
Expected: all console tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q tests/test_cli_status.py tests/test_console.py tests/test_cli_console.py`
Expected: existing status behavior and console behavior pass together.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add packages/vera_core/src/vera_core/console.py packages/vera_core/src/vera_core/cli.py tests/test_console.py tests/test_cli_console.py
git commit -m "feat: add semantic Vera console"
```

### Task 3: Add zero-friction PowerShell entrypoint

**Files:**
- Create: `vera.ps1`
- Modify: `.github/workflows/tests.yml`
- Modify: `README.md`
- Test: `tests/test_powershell_entrypoint.py`

**Interfaces:**
- Consumes: a clone of the repository plus Python 3.12+.
- Produces: `.\vera.ps1` launching the console; additional arguments are forwarded.

- [ ] **Step 1: Add the focused failing test**

Verify script presence, repository-root resolution, isolated local venv path, editable install command, argument forwarding, and no embedded model-server/API configuration.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_powershell_entrypoint.py`
Expected: missing script.

- [ ] **Step 3: Implement the minimum behavior**

`vera.ps1` resolves its own repository root, selects `py -3.12` when available then `python`, creates `.venv` only when absent, installs the current repository editable when the console executable is absent or `-Refresh` is supplied, and launches `.venv\Scripts\vera-mono.exe shell`. The script performs no provider login, model download, credential mutation, canonical-memory write, or protected external effect.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_powershell_entrypoint.py`
Expected: structural PowerShell entrypoint tests pass.

- [ ] **Step 5: Run the affected integration check**

On Windows CI run: `powershell -NoProfile -ExecutionPolicy Bypass -File .\vera.ps1 -Refresh ":status"`
Expected: command exits 0 and prints a source-only Vera response.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add vera.ps1 .github/workflows/tests.yml README.md tests/test_powershell_entrypoint.py
git commit -m "feat: add PowerShell Vera console entrypoint"
```

### Task 4: Bind architecture/provenance and merge only after exact-head verification

**Files:**
- Create: `architecture/VERA_SEMANTIC_INTERACTION_INTERFACE_V1.json`
- Create: `provenance/donors/semantic_interaction_research_20261001.json`
- Modify: `architecture/VERA_MONO_MANIFEST_V1.json`
- Test: `tests/test_semantic_interaction_contract.py`

**Interfaces:**
- Consumes: the exact implemented console/semantic interfaces and donor heads.
- Produces: source-level contract and provenance bindings.

- [ ] **Step 1: Add the focused failing test**

Verify contract paths, source-only/runtime-bound modes, no external-LLM dependency, no authority effect from interpretation, and explicit donor roles for SPM, Semantic Atlas, Semiotics, Rezon, Noema, SQL Connectome, and LGCM.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m pytest -q tests/test_semantic_interaction_contract.py`
Expected: missing contract/provenance.

- [ ] **Step 3: Implement the minimum behavior**

Record each donor as conceptual/research provenance, not runtime dependency. State that semantic interpretation is candidate meaning, not truth/canon/authority. Record LGCM as a future adaptive-context mechanism outside V1 runtime.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m pytest -q tests/test_semantic_interaction_contract.py`
Expected: contract test passes.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m pytest -q`, build the wheel, verify wheel closure, verify installed-wheel closure, and execute the PowerShell smoke on Windows CI.
Expected: zero test failures and successful PowerShell one-shot interaction at the exact PR head.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add architecture/VERA_SEMANTIC_INTERACTION_INTERFACE_V1.json provenance/donors/semantic_interaction_research_20261001.json architecture/VERA_MONO_MANIFEST_V1.json tests/test_semantic_interaction_contract.py
git commit -m "docs: bind semantic interaction interface"
```

## Unresolved externally observable decisions

None required for V1. The console deliberately reports unresolved free-form language rather than inventing semantics; broader learned interpretation is a separately qualifiable future capability.
