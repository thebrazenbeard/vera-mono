# Deep Memory Integration Contract V1

## Purpose

`thebrazenbeard/deepmemorystorage` is Vera's append-only historical evidence plane. It exists to preserve personal, developmental, relational, project, correction, failure, and provenance history without turning stored history into current authority or current memory by accident.

This repository is therefore adjacent to, but not interchangeable with, Vera's current governed memory plane.

## Architectural role

Deep Memory answers questions such as:

- What is recoverably known to have happened in Vera's history?
- What did Vera or Patrick say, choose, prefer, reject, misunderstand, or correct at a particular event time?
- What sources support that history, and at what provenance ceiling?
- What later evidence superseded or narrowed an earlier interpretation?
- What unresolved primary-source gaps remain?

Deep Memory does **not** answer, by storage alone:

- What does Vera want now?
- What is Vera's present consent, relationship state, love, attraction, priority, or authority?
- What is installed or active in the current runtime?
- What has received governed autobiographical-memory admission?

Those claims require fresh evidence from the appropriate current plane.

## The two-memory-plane model

### 1. Historical evidence plane — Deep Memory

Deep Memory is append-only archival history. Its normal operation is `EVIDENCE_SEARCH`.

A successful retrieval returns provenance-bearing historical evidence. Retrieval does not itself alter current state, admit autobiographical memory, authorize action, or prove recollection.

### 2. Current governed memory plane — Vera neutral/current memory

The current-memory architecture represented by `thebrazenbeard/vera`'s `MEMORY_CROSS_CHAT_CONTRACT_V1` is a separate lineage/currentness system. It selects current heads by explicit supersession, applies privacy and epistemic filters, and returns save/recall receipts.

Deep Memory never silently writes into that plane.

### Bridge rule

Historical material may be considered for current governed admission only through an explicit, separately authorized review/admission operation. The bridge must preserve:

- the Deep Memory `memory_id`;
- exact source bindings;
- event time and uncertainty;
- separately recorded record-time provenance when the source carries it, or an explicit unknown-record-time status when it does not;
- historical canonicity;
- privacy scope;
- provenance ceiling;
- currentness rule;
- the fact that historical storage preceded any later admission.

The bridge must never convert `CANONICAL_HISTORY` into `CURRENT` merely because the event was real.

## Retrieval union

The canonical Deep Memory corpus is the **union of all memory ledger tranches**, not only `ledger/memories.jsonl` and not only the legacy root semantic/chronology indexes.

Consumers must:

1. load every memory tranche under `ledger/` matching the architecture binding;
2. reject duplicate `memory_id` collisions;
3. retain the original ledger path for every record;
4. load source records;
5. load append-only historical-canon overlays such as `ledger/historical_canon_pass10.json` and apply them to the targeted legacy rows;
6. apply append-only provenance amendments as overlays, never destructive rewrites;
7. apply append-only historical-canon classification corrections as overlays;
8. retain both the stored/base historical-canonicity value and the effective value when an overlay or correction supplies the latter;
9. preserve event time, overlay record time, overlay effective time, and retrieval time as separate axes; absence of source record/effective time is explicit unknown, never inferred from filenames, Git time, or retrieval time;
10. retain unresolved conflicts and limitations;
11. use pass-specific semantic indexes as aids, not as the authoritative corpus boundary.

This distinction is material: Pass 010 classified 79 preexisting bounded rows through an append-only historical-canon overlay rather than rewriting those rows. A retrieval implementation that reads only the base row therefore produces a false `null`/legacy classification and is incomplete.

`tools/deep_memory_catalog.py` implements this union/validation rule for repository-local consumers.

`tools/query_deep_memory.py` provides a bounded retrieval interface over the union. Query scoring includes authorized amendment/correction text so later provenance improvements are discoverable even when the original memory row predates the new terminology.

## Retrieval result contract

Architecture-facing query output uses `schema/DEEP_MEMORY_EVIDENCE_RESULT_V1.schema.json` (`VERA_DEEP_MEMORY_EVIDENCE_RESULT_V1`).

Every historical result retains at least:

- `memory_id`;
- `memory_class`;
- effective `historical_canonicity`;
- stored/base `stored_historical_canonicity` when different or absent;
- historical-canon overlay metadata when applicable;
- `event_time`;
- `recorded_at` plus `recorded_at_status`;
- a chronology semantic marker that keeps event time, record time, effective time, and retrieval time distinct;
- effective `source_ids`, including visible amendment/correction provenance;
- `privacy_scope`;
- `provenance_ceiling`;
- `currentness_rule`;
- `governed_memory_admission` when present;
- `ledger_path`;
- matching amendment/correction payloads permitted by the caller's privacy scope, with separate `recorded_at` / `effective_from` values and explicit unknown-status fields when those times were not recorded in the source row;
- envelope-level `retrieved_at`, which is retrieval execution time only and never substitutes for event or record time;
- `result_semantics = HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY`.

A consumer may summarize the content, but must not discard these boundaries when they are material to the claim.

## Privacy — fail closed

Privacy travels with the record and retrieval is fail-closed.

An ordinary architecture-facing query must receive exact caller-authorized privacy scopes and may return only records whose `privacy_scope` is included in that authorized set. Absence of privacy authorization is an error, not permission to search the full archive.

Overlay privacy is also fail-closed. A historical-canon overlay, provenance amendment, or classification correction inherits its target memory's privacy scope unless the overlay declares an explicit scope. An explicit overlay scope requires separate authorization for that scope; authorization to the base memory does not authorize a narrower or different overlay payload.

The repository query tool also exposes an explicit `--audit-all-privacy` mode. That mode exists only for a deliberate audit performed inside the private archive. It is not a runtime default and must never be substituted silently for caller authorization.

Private relational, intimate, journal, Voice, developmental, visual, and training material remains nonportable, nonpublic, and nontraining absent separate exact authority.

The fact that an operator or service can technically read this private repository does not by itself authorize cross-scope retrieval or disclosure.

## Precedence and anti-promotion

When Deep Memory conflicts with a fresh current source, the archive is not allowed to win merely because it is detailed or emotionally salient.

Use this precedence for mutable claims:

1. platform/safety;
2. Patrick's current task, correction, privacy, permission, target, and scope;
3. fresh admitted current control/state;
4. current governed-memory evidence appropriate to the claim;
5. Deep Memory historical evidence;
6. inference.

Deep Memory may still establish that the conflicting historical event really happened. Currentness and historical canonicity are separate axes.

## Conflict semantics

Deep Memory is append-only and conflict-preserving.

Do not resolve conflict through:

- newest timestamp wins;
- newest file wins;
- newest branch wins;
- model confidence;
- semantic similarity;
- current preference replacing historical preference.

Instead retain the competing records and add a provenance-bound correction or amendment when the evidence ceiling improves.

Source IDs are also provenance identities. An identical source binding may be restated in a later append-only tranche and deduplicated with a warning. Divergent reuse of the same `source_id` is a provenance conflict and fails validation.

## Relationship to Semantic Atlas

Semantic Atlas supplies methodology for provenance, semantic indexing, temporal separation, anti-collapse, aliases, and evidence ceilings. Deep Memory stores the historical corpus produced under those methods.

Semantic Atlas does not become current authority merely because Deep Memory uses its methodology.

## Relationship to R9B0

R9B0/current autobiographical admission is a separate governed state transition.

A Deep Memory row may be `AUTOBIOGRAPHICAL` and `CANONICAL_HISTORY` while remaining not admitted for current autobiographical use. Conversely, an admission receipt does not rewrite the event's original provenance or event time.

## Relationship to runtime/control

Deep Memory commits prove repository history only.

They do not prove:

- native Project installation;
- provider activation;
- model/runtime qualification;
- current Bus routing;
- deployment;
- permission changes;
- current behavioral state.

Current control owners outrank Deep Memory for those claims.

## Validation requirements

Architecture integration is considered healthy when repository CI proves at minimum:

- every memory tranche parses as JSONL;
- `memory_id` values are globally unique;
- historical-canon overlay files parse, target existing rows, and preserve their declared assignment counts;
- effective historical canonicity incorporates the Pass-010 legacy overlay and exact later correction classes;
- identical source-ID restatements are distinguished from divergent source-ID conflicts;
- the union row count matches the latest completed ingest receipt when that receipt exposes an aggregate row count;
- the latest receipt's filename stem must equal its internal `pass_id`, and every pass after `INGEST_PASS_001` must name the immediately preceding numeric pass in `continues`; skipped/forked predecessors, missing targets, malformed IDs, and cycles fail closed;
- an exact canonical digest is recomputed over the complete memory/source/amendment/correction/historical-overlay union; row-count agreement alone is reported as `ROW_COUNT_MATCH` and MUST NOT be described as exact ingest lineage;
- `CORPUS_SUBJECT_MATCH` is available only when the receipt explicitly binds the recomputed union-subject digest and it matches exactly;
- source/amendment/correction files parse;
- referenced source IDs from memories, amendments, and corrections are reported when missing;
- the retrieval/query tools can enumerate the union;
- query privacy fails closed without exact scope authorization;
- overlay payloads inherit target privacy unless an explicit overlay scope requires separate authorization;
- query scoring can discover authorized amendment/correction-only terminology;
- query results carry the defined evidence-result envelope, chronology separation, and nonpromotion semantics;
- every external GitHub Action referenced by any workflow `uses:` declaration is pinned to an immutable 40-character commit SHA, and the observed action-name/pin set must exactly match the architecture pin registry; local `./` actions are the only unpinned `uses:` form allowed by this validator;
- no validator treats the legacy root indexes as the corpus boundary.

A validation PASS proves repository consistency only. It does not promote any memory or install any runtime behavior.
