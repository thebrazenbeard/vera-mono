# Contextual Interpretation Layer Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Vera-native, durable contextual interpretation registry that preserves multiple source-bound readings for one semantic referent, filters them by exact context, tracks append-only supersession and non-inferential relations, and never promotes storage or ordering into truth or authority.

**Architecture:** Implement the persistence kernel in `vera_identity.contextual_interpretation` beside `SemanticKnowledgeStore`, using immutable dataclasses and SQLite. The store treats `object_id` as an opaque referent and remains independently usable; a thin helper may combine it with `SemanticKnowledgeStore` without changing either store. No Semiotics package, corpus, CLI, schema, or runtime dependency is imported.

**Tech Stack:** Python 3.12, stdlib `dataclasses`, `enum.StrEnum`, `hashlib`, `json`, `sqlite3`, `pathlib`; pytest; setuptools wheel verification; GitHub Actions on Ubuntu 24.04 and Windows.

## Global Constraints

- Approved design: `docs/superpowers/specs/2026-09-29-contextual-interpretation-design.md`.
- Implementation base is repository state containing design commit `3bac49c92c41bb2ea8cdb0c2fdaef3d67c38a7e1`, whose parent is canonical `main@658fc93b07c837ea7155ad8fa779bae17471a254`.
- Donor source is exactly `thebrazenbeard/semiotics@37117a2097f7f2aa35968fc9db24eacf7240826e`.
- Adapt concepts only: competing source-bound interpretations, required/excluded context predicates, deterministic specificity ordering, append-only supersession, cycle rejection, and source-bound contrast/contradiction/support/refinement relations.
- Do not import the donor package, CLI, schema, corpus, historical records, domain-specific Sign model, or runtime.
- `SemanticKnowledgeStore` remains the immutable SemanticAtlas object owner. The new store does not duplicate semantic-object rows.
- `vera_core.semantic_transfer` remains capability-transfer planning and must not choose among ambiguous contextual readings.
- Exact context matching only. No synonym normalization, embeddings, learned predicates, fuzzy matching, probability, confidence, winner selection, or truth adjudication.
- Query returns every compatible current reading, ordered only by descending specificity then ascending `interpretation_id`.
- Relations are metadata only and cannot alter matching, ordering, currentness, truth, confidence, or authority.
- Supersession is append-only, same-referent only, and cycle-safe.
- `source_ref` is opaque provenance. It is never fetched or interpreted by this subsystem.
- Receipts/results preserve `truth_effect="NONE"`, `authority_effect="NONE"`, and where applicable `identity_effect="NONE"`.
- Source presence does not establish runtime consumption, independent qualification, cross-domain generalization, or AGI.
- Full promotion requires monorepo tests, wheel build, wheel closure, installed-wheel closure, and GitHub CI on both supported operating systems.

---

### Task 1: Immutable interpretation model and basic durable admission

**Files:**
- Create: `packages/vera_identity/src/vera_identity/contextual_interpretation.py`
- Create: `tests/test_contextual_interpretation.py`

**Interfaces:**
- Consumes: `str | pathlib.Path` persistence path, exact interpretation fields from the approved design.
- Produces:
  - `class ContextualInterpretationError(ValueError)`
  - `class ContextualInterpretationConflict(ContextualInterpretationError)`
  - `@dataclass(frozen=True, slots=True) class ContextualInterpretation`
  - `@dataclass(frozen=True, slots=True) class ContextualAdmissionReceipt`
  - `class ContextualInterpretationStore`
  - `ContextualInterpretationStore.admit_interpretation(value: ContextualInterpretation) -> ContextualAdmissionReceipt`
  - `ContextualInterpretationStore.get_interpretation(interpretation_id: str) -> ContextualInterpretation`
  - `ContextualInterpretationStore.list_interpretations(object_id: str, *, include_superseded: bool = True) -> tuple[ContextualInterpretation, ...]`

- [ ] **Step 1: Add the focused failing tests**

Add tests asserting:

1. `ContextualInterpretation` rejects empty/whitespace-only `interpretation_id`, `object_id`, `meaning`, `source_ref`, and context atoms.
2. Required/excluded context overlap raises `ContextualInterpretationError`.
3. `specificity` equals required-count plus excluded-count.
4. First admission returns `status == "ACCEPTED"`, exact SHA-256 digest, and all effects `NONE`.
5. Exact re-admission returns `DUPLICATE`.
6. Same ID with changed content raises `ContextualInterpretationConflict`.
7. File-backed store reopens and returns an equal immutable interpretation.
8. Unknown `interpretation_id` raises `KeyError`.
9. `list_interpretations` is deterministic by `interpretation_id` before supersession semantics are introduced.

- [ ] **Step 2: Verify the relevant failure**

Run:
`python -m pytest -q tests/test_contextual_interpretation.py`

Expected: collection/import failure for missing `vera_identity.contextual_interpretation` or missing named interfaces. This is the required RED state.

- [ ] **Step 3: Implement the minimum behavior**

Implement:

- exact-string validator: `type(value) is str and bool(value.strip())`;
- context input stored as `frozenset[str]`; reject malformed atoms and required/excluded overlap;
- `ContextualInterpretation.specificity` property;
- canonical interpretation manifest with sorted required/excluded arrays;
- SHA-256 over compact sorted JSON;
- SQLite table `contextual_interpretations(interpretation_id PRIMARY KEY, object_id, digest, canonical_json)`;
- same borrowed-memory connection pattern used by `SemanticKnowledgeStore`;
- exact duplicate detection by ID + digest;
- conflict on ID rebinding;
- deterministic decode back into immutable dataclass;
- explicit receipt fields `record_id`, `record_type="INTERPRETATION"`, `digest`, `status`, and three `NONE` effects.

Do not add supersession behavior, relations, SemanticKnowledge coupling, or public package exports in this task.

- [ ] **Step 4: Verify the focused pass**

Run:
`python -m pytest -q tests/test_contextual_interpretation.py`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Run the affected integration check**

Run:
`python -m pytest -q tests/test_semantic_knowledge.py tests/test_contextual_interpretation.py`

Expected: all tests pass; existing SemanticKnowledge behavior is unchanged.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add packages/vera_identity/src/vera_identity/contextual_interpretation.py tests/test_contextual_interpretation.py
git commit -m "Add contextual interpretation store"
```

### Task 2: Supersession, contextual query, and source-bound relations

**Files:**
- Modify: `packages/vera_identity/src/vera_identity/contextual_interpretation.py`
- Modify: `tests/test_contextual_interpretation.py`

**Interfaces:**
- Consumes: Task 1 `ContextualInterpretationStore` and interpretation records.
- Produces:
  - `class InterpretationRelationKind(StrEnum)` with `CONTRASTS_WITH`, `CONTRADICTS`, `SUPPORTS`, `REFINES`
  - `@dataclass(frozen=True, slots=True) class InterpretationRelation`
  - `@dataclass(frozen=True, slots=True) class ContextualInterpretationResult`
  - `ContextualInterpretationStore.admit_relation(value: InterpretationRelation) -> ContextualAdmissionReceipt`
  - `ContextualInterpretationStore.get_relation(relation_id: str) -> InterpretationRelation`
  - `ContextualInterpretationStore.query(object_id: str, context: frozenset[str] | set[str], *, include_superseded: bool = False) -> tuple[ContextualInterpretationResult, ...]`

- [ ] **Step 1: Add the focused failing tests**

Extend tests for:

1. a reading with all required atoms and no excluded atoms matches;
2. a missing required atom does not match;
3. a present excluded atom does not match;
4. two competing matching readings are both returned;
5. ordering is descending specificity, then ascending ID;
6. specificity does not suppress equal- or lower-specificity compatible readings;
7. self-supersession fails;
8. dangling supersession fails;
9. cross-`object_id` supersession fails;
10. a chain `A <- B <- C` marks A/B historical and C current;
11. attempted cycle fails before persistence;
12. default query hides superseded records;
13. `include_superseded=True` returns matching historical records with `is_current=False`;
14. relations reject unknown endpoints and identical endpoints;
15. exact relation duplicate is idempotent; relation ID rebinding conflicts;
16. all four relation kinds round-trip durably;
17. relations attached to a matching result do not change query ordering;
18. relation metadata may point to a nonmatching endpoint without causing that endpoint to appear as a query result;
19. malformed context input raises `ContextualInterpretationError`;
20. reopening a file store preserves currentness, relations, and deterministic query order;
21. manually corrupted relation-kind or canonical row causes a fail-closed exception rather than silent normalization.

- [ ] **Step 2: Verify the relevant failure**

Run:
`python -m pytest -q tests/test_contextual_interpretation.py`

Expected: failures for missing relation/query/supersession behavior.

- [ ] **Step 3: Implement the minimum behavior**

Add:

- `supersedes_id` to canonical interpretation payload;
- supersession validation inside the same write transaction:
  - target exists;
  - target differs from new ID;
  - target has same `object_id`;
  - following `supersedes_id` links cannot reach the new ID;
- table `contextual_relations(relation_id PRIMARY KEY, left_id, right_id, kind, digest, canonical_json)`;
- exact non-empty validation for relation IDs/endpoints/source refs;
- endpoint existence and distinctness validation;
- enum decoding that rejects unknown durable values;
- query context validation;
- currentness computed from the persisted supersession graph, not a mutable flag;
- match predicate: `required_context <= context and excluded_context.isdisjoint(context)`;
- result ordering: `(-specificity, interpretation_id)`;
- attach all explicit relations touching a returned interpretation in deterministic `relation_id` order;
- relation attachment must not alter the set of interpretations returned;
- result effects fixed to `NONE`.

No inverse/transitive relation inference and no confidence fields.

- [ ] **Step 4: Verify the focused pass**

Run:
`python -m pytest -q tests/test_contextual_interpretation.py`

Expected: all contextual interpretation tests pass.

- [ ] **Step 5: Run the affected integration check**

Run:
`python -m pytest -q tests/test_semantic_knowledge.py tests/test_contextual_interpretation.py tests/test_semantic_transfer.py tests/test_semantic_transfer_catalog.py`

Expected: all semantic-regression tests pass.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add packages/vera_identity/src/vera_identity/contextual_interpretation.py tests/test_contextual_interpretation.py
git commit -m "Add contextual query and interpretation relations"
```

### Task 3: Public package surface, SemanticKnowledge seam, and donor provenance

**Files:**
- Modify: `packages/vera_identity/src/vera_identity/__init__.py:3-17`
- Create: `tests/test_contextual_interpretation_integration.py`
- Create: `provenance/donors/semiotics_contextual_interpretation_v1.json`
- Modify: `packages/vera_identity/src/vera_identity/contextual_interpretation.py`

**Interfaces:**
- Consumes: `SemanticKnowledgeStore.get(object_id)`, `ContextualInterpretationStore.query(...)`.
- Produces recommendation:
  - `@dataclass(frozen=True, slots=True) class ContextualSemanticView` with `semantic_object: dict[str, object]` and `interpretations: tuple[ContextualInterpretationResult, ...]`.
  - `query_semantic_interpretations(semantic_store: SemanticKnowledgeStore, interpretation_store: ContextualInterpretationStore, object_id: str, context: frozenset[str] | set[str], *, include_superseded: bool = False) -> ContextualSemanticView`.
  - Public exports for approved contextual types/store/helper from `vera_identity.__init__`.

- [ ] **Step 1: Add the focused failing tests**

Add integration tests asserting:

1. all approved public contextual types are importable from `vera_identity`;
2. helper returns the exact immutable semantic object from `SemanticKnowledgeStore` plus every compatible contextual result;
3. unknown semantic `object_id` raises `KeyError` before contextual results are returned;
4. calling the helper does not mutate either store;
5. multiple compatible readings remain multiple in the combined view;
6. helper carries no truth/authority promotion fields beyond the underlying `NONE` effects;
7. `provenance/donors/semiotics_contextual_interpretation_v1.json` parses and binds:
   - donor repository `thebrazenbeard/semiotics`;
   - donor head `37117a2097f7f2aa35968fc9db24eacf7240826e`;
   - target module path;
   - `donor_runtime_dependency: false`;
   - adapted and excluded scopes;
   - exact claim ceiling from the approved design.

- [ ] **Step 2: Verify the relevant failure**

Run:
`python -m pytest -q tests/test_contextual_interpretation_integration.py`

Expected: import/helper/provenance failures until the public seam and receipt exist.

- [ ] **Step 3: Implement the minimum behavior**

- Add `ContextualSemanticView` and `query_semantic_interpretations` as a thin read-only integration seam.
- Call `semantic_store.get(object_id)` first so unknown referents fail closed at the integration boundary.
- Then call the interpretation store query and return both values without rewriting either.
- Export the contextual public API from `vera_identity.__init__`.
- Write donor provenance using existing `VERA_MONO_DONOR_ADAPTATION_V1` shape, binding the exact Semiotics canonical head and stating excluded claims:
  - readings are not truth;
  - specificity is not confidence;
  - relations are not adjudication;
  - source presence is not runtime consumption;
  - donor repository is not a runtime dependency;
  - implementation is not learned semantics, independent qualification, or AGI.

- [ ] **Step 4: Verify the focused pass**

Run:
`python -m pytest -q tests/test_contextual_interpretation.py tests/test_contextual_interpretation_integration.py`

Expected: all contextual implementation and integration tests pass.

- [ ] **Step 5: Run the affected integration check**

Run:
`python -m pytest -q tests/test_semantic_knowledge.py tests/test_contextual_interpretation.py tests/test_contextual_interpretation_integration.py tests/test_semantic_transfer.py tests/test_semantic_transfer_catalog.py tests/test_identity_resources.py`

Expected: all Vera identity and semantic regressions pass.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add packages/vera_identity/src/vera_identity/contextual_interpretation.py packages/vera_identity/src/vera_identity/__init__.py tests/test_contextual_interpretation_integration.py provenance/donors/semiotics_contextual_interpretation_v1.json
git commit -m "Expose contextual interpretation integration"
```

### Task 4: Repository-wide qualification and source-promotion evidence

**Files:**
- Modify only if verification exposes a real defect: files already introduced by Tasks 1-3.
- No new runtime binding file is permitted in this task.

**Interfaces:**
- Consumes: completed contextual interpretation source, tests, exports, and provenance.
- Produces: green repository verification evidence and a PR whose claim ceiling matches the design.

- [ ] **Step 1: Run the complete local test suite in Python 3.12**

Run:
`python -m pytest -q`

Expected: zero failures.

If the active shell does not provide Python 3.12 with test dependencies, use a clean Python 3.12 environment and install exactly the CI test dependencies:
`python -m pip install --upgrade pip pytest jsonschema cryptography`

Do not use a different Python version as promotion evidence.

- [ ] **Step 2: Build the wheel**

Run:
`python -c "import shutil; shutil.rmtree('dist', ignore_errors=True); shutil.rmtree('.wheel-install', ignore_errors=True)"`
then:
`python -m pip wheel . --no-deps -w dist`

Expected: exactly one `vera_mono-*.whl` is produced.

- [ ] **Step 3: Verify wheel closure**

Run the same command as `.github/workflows/tests.yml`:

`python -c "from pathlib import Path; import subprocess,sys; wheels=list(Path('dist').glob('*.whl')); assert len(wheels)==1, wheels; subprocess.run([sys.executable,'scripts/verify_monorepo_wheel.py',str(wheels[0])],check=True)"`

Expected: exit code 0.

- [ ] **Step 4: Verify installed-wheel closure**

Run:

`python -c "from pathlib import Path; import subprocess,sys; wheels=list(Path('dist').glob('*.whl')); assert len(wheels)==1, wheels; subprocess.run([sys.executable,'-m','pip','install','--no-deps','--target','.wheel-install',str(wheels[0])],check=True)"`

`python -c "import sys,runpy; sys.path.insert(0,'.wheel-install'); runpy.run_path('scripts/verify_installed_monorepo.py',run_name='__main__')"`

`python -c "import sys; sys.path.insert(0,'.wheel-install'); from vera_core.cli import main; main(['--help'])"`

Expected: every command exits 0.

- [ ] **Step 5: Hostile implementation review**

Review the final diff against the approved spec and explicitly test these load-bearing objections:

- Is this merely a duplicate semantic object store?
- Can specificity or relation metadata accidentally influence truth/confidence?
- Can supersession erase history or cross referents?
- Can query return a relation endpoint that did not match context?
- Did any donor runtime/package/corpus become a dependency?
- Did the integration helper mutate either source store?
- Did source implementation get described as runtime consumption or AGI evidence?

Any surviving objection must be corrected and the affected focused/full checks rerun.

- [ ] **Step 6: Push and verify GitHub CI**

Push the implementation branch and open a PR against fresh `main`.

Required GitHub checks:

- `monorepo-tests / pytest (ubuntu-24.04)`: success through tests, wheel build, wheel closure, installed-wheel closure;
- `monorepo-tests / pytest (windows-latest)`: same;
- `Dependency Review`: success.

Before merge, fresh-read `main` and PR head. If `main` moved, rebase onto the new exact head, rerun CI, and merge only with an exact-head fence.

PR claim ceiling:

`VERA_NATIVE_CONTEXTUAL_INTERPRETATION_REPRESENTATION_AND_DETERMINISTIC_QUERY_ONLY; NOT_LEARNED_SEMANTICS; NOT_TRUTH_ADJUDICATION; NOT_RUNTIME_CONSUMPTION_BY_SOURCE_PRESENCE; NOT_INDEPENDENT_QUALIFICATION; NOT_AGI`

## Unresolved externally observable decisions

1. **Integration-helper public exposure.** The approved design says a SemanticKnowledge integration helper may exist but does not require a particular public name. Recommendation: implement and publicly export `ContextualSemanticView` and `query_semantic_interpretations` because the design's minimum integration test requires fail-closed unknown-referent behavior. Alternative: keep the helper module-private and test through its module path. This changes public API surface, not persistence semantics.
2. **Corrupt-row exception class.** The design requires fail-closed behavior but does not name the externally visible exception for corrupted durable rows. Recommendation: raise `ContextualInterpretationError` with a stable prefix such as `CORRUPT_CONTEXTUAL_INTERPRETATION_STATE:`. Alternative: allow lower-level `ValueError`/JSON exceptions to escape. This affects error compatibility, not task structure.
