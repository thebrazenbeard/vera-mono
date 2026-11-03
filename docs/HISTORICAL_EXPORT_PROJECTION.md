# Staged export → historical evidence (source-only)

`vera_memory.historical_export_projection` provides a pure, bounded projection
for **already staged** rows from historical exports. It does not read Downloads,
open OneDrive placeholders, parse archives, verify rights, authenticate review
receipts, write memories, or update runtime currentness.

An upstream **private** process must independently establish provenance and
rights, review personal content, and authenticate the requested privacy scope
and source IDs before this projection is used. Strings named
`review_authority_ref` and `review_receipt_ref` are references **only**;
their presence is not approval. A self-labelled export `status: approved`
cannot be an admission grant. The output keeps its provenance ceiling
`UNVERIFIED_EXPORT_SOURCE`, canonicity `UNRESOLVED_HISTORY`, and currentness
rule `HISTORICAL_ONLY_NO_CURRENTNESS_CLAIM` regardless of caller claims.

For example, an authorized private caller can construct
`StagedExportEvidence` with exact source ID, content SHA-256, row ID, privacy
scope, review references, text and three separately represented historical
times (explicit `None` for unknown). Then call `project_staged_exports` with
explicitly authorized source IDs, privacy scopes, and a retrieval timestamp.
The result is a `HistoricalEvidenceResult` with
`current_memory_effect=NONE` and `authorization_effect=NONE`.

The API enforces at most 1,024 rows, at most 8,192 UTF-8 bytes of text per
row, 512-byte source/row IDs and review references, 128-byte privacy scope
names, and 64-byte time fields (all measured in UTF-8). Authorization inputs
are limited to 256 source IDs and 64 privacy scopes, with duplicate rejection.
The adapter also enforces unique `(source_id, item_id)` pairs, consistent
source digest binding, and exact scope filtering. It makes no network or
storage calls. Content,
source names, sizes and even hashes can be personally identifying: keep
instances and output private. Do **not** put projection results into public
Git repositories or feed them into TrainingDay without a separate admission
decision. Synthetic tests exercise the boundary; no OneDrive or Windows host
qualification is implied.
