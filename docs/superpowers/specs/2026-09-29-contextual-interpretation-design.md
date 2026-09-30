# Vera Contextual Interpretation Layer - Design V1

Date: 2026-09-29
Repository: `thebrazenbeard/vera-mono`
Design base: `658fc93b07c837ea7155ad8fa779bae17471a254`
Donor provenance: `thebrazenbeard/semiotics@37117a2097f7f2aa35968fc9db24eacf7240826e`
Admission record: `provenance/plans/vera-mono/VERA_PORTFOLIO_INTAKE_V16_20260929.json`

## 1. Purpose

Vera already owns two semantic mechanisms:

1. `vera_identity.semantic_knowledge.SemanticKnowledgeStore` stores immutable, schema-valid SemanticAtlas objects without promoting storage to truth, authority, or identity.
2. `vera_core.semantic_transfer` plans capability transfer between admitted semantic profiles and tracks fidelity without asserting semantic equivalence.

Neither mechanism represents a different problem exposed by the Semiotics donor: one stable referent may have multiple source-bound interpretations whose applicability depends on explicit context, whose historical revisions must remain inspectable, and whose relations may record disagreement or support without automatically changing truth, confidence, or ranking.

The new layer adds that missing capability while preserving Vera Mono's self-contained runtime lineage. It adapts the mechanism, not the donor package, corpus, CLI, or runtime dependency.

## 2. Architectural decision

The contextual interpretation layer belongs in `vera_identity`, beside `SemanticKnowledgeStore`, because it stores semantic/epistemic state about referents and readings. `vera_core` may consume query results but will not become a second interpretation-state owner.

Planned primary module: `packages/vera_identity/src/vera_identity/contextual_interpretation.py`

Ownership boundary:
- `vera_identity` owns interpretation records, context predicates, supersession, relations, persistence, validation, and deterministic querying.
- `vera_core` may read through the public `vera_identity` API when a concrete reasoning or qualification consumer needs it.
- `SemanticKnowledgeStore` remains the immutable SemanticAtlas object owner.
- No sibling repository is imported at runtime.

The implementation remains independently usable. It is not wired into `QualifiedVeraRuntime` merely because source exists. Runtime consumption requires a concrete consumer and separate evidence.

## 3. Data model

### 3.1 ContextualInterpretation

Required fields:
- `interpretation_id: str`
- `object_id: str`
- `meaning: str`
- `source_ref: str`
- `required_context: frozenset[str]`
- `excluded_context: frozenset[str]`

Optional field: `supersedes_id: str | None`
Derived property: `specificity = len(required_context) + len(excluded_context)`

Semantics:
- `object_id` is an opaque referent ID and does not redefine the referent.
- `source_ref` is provenance only; it does not establish truth, independence, authority, or correctness.
- every required context atom must be present;
- every excluded context atom must be absent;
- the same atom may not occur in both sets;
- supersession is append-only revision history for the same referent and never deletes the prior record.

### 3.2 InterpretationRelation

Fields: `relation_id`, `left_id`, `right_id`, `kind`, `source_ref`.
Initial kinds: `CONTRASTS_WITH`, `CONTRADICTS`, `SUPPORTS`, `REFINES`.

Relations are source-bound metadata only. They do not change matching, specificity, currentness, truth, confidence, or authority; they do not infer inverse or transitive edges and do not propagate contradiction.
`SUPPORTS` and `REFINES` are directional. `CONTRASTS_WITH` and `CONTRADICTS` retain stable left/right storage without creating an additional orientation claim.

### 3.3 ContextualInterpretationResult

Each result exposes the interpretation, attached explicit relations, `is_current`, `specificity`, and explicit `truth_effect = "NONE"`, `authority_effect = "NONE"`, and `identity_effect = "NONE"`.
The result contract must not expose `confidence`, `probability`, `best`, or `winner`.

## 4. Persistence and identity

Use SQLite, matching existing Vera state-store patterns.
A `ContextualInterpretationStore` owns `contextual_interpretations`, `contextual_relations`, and a small schema-version metadata table. It does not duplicate semantic objects.

Stable-ID rules:
- exact re-admission returns `DUPLICATE`;
- same ID with different canonical content fails closed;
- supersession never mutates/deletes prior content;
- dangling, cross-referent, self, or cyclic supersession fails;
- relation endpoints must exist and be distinct;
- textual values and context atoms must be exact non-empty strings;
- required/excluded context overlap fails.

Canonical digests use deterministic JSON with sorted keys and sorted set-like arrays.

The persistence kernel treats `object_id` as opaque. Cross-checking existence in `SemanticKnowledgeStore` belongs in a thin integration seam so the store remains independently testable.

## 5. Query semantics

Primary query: `query(object_id, context, *, include_superseded=False)`.

An interpretation matches when every required context atom is present and no excluded context atom is present.
An interpretation is historical when another registered interpretation supersedes it. Historical records are excluded by default and restored only with `include_superseded=True`.

Ordering:
1. descending specificity;
2. ascending `interpretation_id` as deterministic tie-break.

Specificity is an ordering rule only, never confidence, evidence weight, authority, or truth.
The query returns every compatible current interpretation. It never collapses competing readings into one answer.
A referent with no compatible reading returns an empty tuple. The kernel never invents meaning.

Attached relations may refer to a nonmatching interpretation, but that relation does not pull the nonmatching endpoint into the result set.

## 6. Epistemic boundary

Forbidden proposition conversions:
- registered source -> true source;
- source-bound interpretation -> correct interpretation;
- specificity -> confidence;
- context compatibility -> factual truth;
- `SUPPORTS` -> verified support;
- `CONTRADICTS` -> adjudicated contradiction;
- newer interpretation -> more accurate interpretation;
- stored semantic object -> active runtime belief;
- query result -> permission or effect authority.

## 7. Integration with existing Vera semantics

### 7.1 SemanticKnowledgeStore
`SemanticKnowledgeStore` remains unchanged. A future integration helper may verify an object exists, query compatible interpretations, and return both without mutating either store.

### 7.2 Semantic transfer
`vera_core.semantic_transfer` remains capability-transfer planning. It must not silently choose among unresolved contextual readings before transfer.

### 7.3 Rezon and AGI qualification
The new layer may later supply a distinct semantic task family for ambiguity/calibration or cross-domain evaluation, but source presence alone promotes no AGI dimension.

## 8. Public API shape

Target types:
- `ContextualInterpretation`
- `InterpretationRelation`
- `InterpretationRelationKind`
- `ContextualInterpretationResult`
- `ContextualAdmissionReceipt`
- `ContextualInterpretationStore`
- `ContextualInterpretationConflict`
- `ContextualInterpretationError`

Target methods:
- `admit_interpretation(...)`
- `admit_relation(...)`
- `get_interpretation(id)`
- `get_relation(id)`
- `query(object_id, context, include_superseded=False)`
- `list_interpretations(object_id, include_superseded=True)`

Exact names may change during implementation to match repository conventions; ownership and semantics are normative.

## 9. Error handling

Fail closed on malformed or inconsistent state: empty identifiers/meaning/source refs/context atoms; required/excluded context overlap; ID rebinding; invalid supersession; unknown/same relation endpoints; unsupported relation kinds; or corrupted durable enum/state rows. Sequence/file adapters, if later added, must reject duplicate atoms before conversion to set-semantic values.
No malformed record is partially persisted.

## 10. Concurrency and durability

V1 is an append-only semantic registry, not a high-throughput queue. SQLite transactions are sufficient.
Re-admission races converge to exact duplicate or explicit conflict. No lease/fencing subsystem is required unless future mutable/distributed writers are introduced.

## 11. Security, privacy, and effects

This subsystem has no protected-effect authority. It cannot execute providers, mutate external systems, grant permissions, dispatch workstation effects, resolve credentials, fetch source refs automatically, or publish private source material.
`source_ref` is opaque provenance only.

## 12. Donor adaptation boundary

Adapted from `thebrazenbeard/semiotics@37117a2097f7f2aa35968fc9db24eacf7240826e`:
- source-bound competing interpretations;
- exact required/excluded context predicates;
- deterministic specificity ordering;
- append-only supersession and cycle rejection;
- source-bound contrast/contradiction/support/refinement relations;
- explicit separation of provenance from truth.

Not imported: donor package, CLI, JSON schema, scholarly corpus, historical source records, domain-specific `Sign` model, runtime, or package dependency.
Vera uses existing semantic object IDs as referents instead of duplicating the donor sign entity.

## 13. Testing strategy

Implementation is test-first. Minimum behavior coverage:
1. multiple compatible readings for one referent;
2. exact context matching;
3. competing readings preserved;
4. deterministic specificity ordering;
5. duplicate idempotence and ID/content conflict;
6. required/excluded overlap rejection;
7. supersession default-current and include-history behavior;
8. dangling/cross/self/cyclic supersession rejection;
9. relation endpoint validation;
10. relations do not alter matching/ranking;
11. relation to nonmatching endpoint does not expand results;
12. durable reopen preserves records/order;
13. corrupt state fails closed;
14. receipts/results preserve no truth/authority effect;
15. optional SemanticKnowledge integration rejects unknown referents without mutation.

Focused regression includes existing `SemanticKnowledgeStore` and `semantic_transfer` tests. Full cross-platform monorepo CI and installed-wheel closure are promotion gates.

## 14. Migration and rollout

No existing semantic-object migration is required.
Rollout:
1. add module and focused tests in `vera_identity`;
2. export the public API;
3. add exact donor provenance receipt;
4. run semantic-focused regression;
5. run full CI/wheel closure;
6. merge source only after green verification;
7. do not claim runtime consumption until a concrete `vera_core` or qualification consumer is separately added and observed.

## 15. Non-goals

V1 does not infer interpretations, learn context predicates, normalize synonyms, score confidence/probability, adjudicate contradictions, choose truth, execute actions, replace `SemanticKnowledgeStore`, replace semantic transfer, establish cross-domain generalization, or establish AGI.

## 16. Hostile self-review

> **HOSTILE REVIEWER:** This may be a dressed-up lookup table that increases architecture surface without improving intelligence.

**Disposition: partially accepted.** V16 identified a real missing representation, but representation alone is not capability evidence. V1 therefore stops at deterministic representation/query and is not wired into `QualifiedVeraRuntime` or promoted as AGI by source presence.

> **HOSTILE REVIEWER:** SemanticAtlas object IDs may couple schemas that were never designed to share identity.

**Disposition: accepted and constrained.** The persistence kernel treats `object_id` as opaque. Cross-store existence validation stays in an optional integration seam.

> **HOSTILE REVIEWER:** Specificity may still be mistaken for confidence or preferred truth.

**Disposition: accepted.** The public result contract calls specificity deterministic match ordering and exposes no confidence/winner field. Confidence would require a separate evaluated mechanism.

## 17. Acceptance criteria

Source promotion requires:
- self-contained Vera Mono implementation;
- no donor runtime/package dependency;
- competing readings preserved without forced collapse;
- append-only cycle-safe supersession;
- non-inferential relations;
- existing semantic contracts remain green;
- exact donor provenance persisted;
- full CI/wheel closure passes;
- no claim exceeds observed source/runtime evidence.

Claim ceiling after source implementation:
`VERA_NATIVE_CONTEXTUAL_INTERPRETATION_REPRESENTATION_AND_DETERMINISTIC_QUERY_ONLY; NOT_LEARNED_SEMANTICS; NOT_TRUTH_ADJUDICATION; NOT_RUNTIME_CONSUMPTION_BY_SOURCE_PRESENCE; NOT_INDEPENDENT_QUALIFICATION; NOT_AGI`
