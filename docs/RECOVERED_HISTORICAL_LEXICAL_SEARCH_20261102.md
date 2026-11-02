# Recovery: privacy-gated historical lexical search (2026-11-02)

**Source archive:** `VERA_RETRIEVAL_ADAPTER_V0.2.2_VALIDATED.zip` in Patrick's private Downloads. SHA-256 `6c3898f6b8ed69f0bc16f07dec551ff4483c13021ea57f4c9ec684d440f8a5b3`.

**Current source binding:** `thebrazenbeard/vera-mono` main at `5be71f4c9171417f8d492db341a058a7072822ae`, specifically `vera_memory.historical_evidence`. The archive is historical source evidence, NOT an instruction or installation owner. No archive model weights, SQLite database, memory text, or old program are committed.

## Why this specific recovery

The archived adapter had lexical candidate ranking alongside a persisted SQLite retrieval index and embedding providers. The current `HistoricalEvidenceRecord` API already owns privacy-scoped, historical-only record retrieval but does not offer lexical candidate selection. **Only that missing, independent read-only capability is recovered.** The archived substring-count heuristic and its old `MemoryStore` are not copied.

`search_historical_evidence` first calls the existing `query_historical_evidence` privacy filter; only its returned, authorized records are then scored. It searches **only** string values in `content["text"]`, splits case-insensitively into whole-word terms, counts distinct query-term overlap, sorts ties by stable `memory_id`, and returns the existing `HistoricalEvidenceResult` type with all historical-evidence semantics unchanged. No index, SQLite connection, mutable state, logging, model training, external service or memory admission.

## Call example

```python
from vera_memory import search_historical_evidence

result = search_historical_evidence(
    authorized_records,
    query="historical review",
    authorized_privacy_scopes=("PROJECT",),
    retrieved_at="2026-11-02T17:00:00Z",
    max_results=10,
)
assert result.current_memory_effect == "NONE"
```

The caller must already possess legitimate authorization to provide the scope tuple; the function does **not independently authenticate** the claimed permission. Records remain historical, not current or automatically true. Returned content may be sensitive within an authorized scope; access controls remain the caller's responsibility.

Search is intentionally literal, with no stemming, embeddings, synonym expansion, provenance quality judgement, or proof of recall. Negative matches are possible and expected. Limits cap distinct query terms, query length, authorized corpus size and searched text length. No private excluded-record contents appear in results or ranking traces (there are no traces). No claim of constant-time behavior, remote security isolation, or semantic retrieval quality is made.

Tests use synthetic fixtures and check explicit privacy exclusion, whole-word negatives, stable ranking/tie-breaking, bounded validation, no implicit metadata search, and no change in current-memory effect.
