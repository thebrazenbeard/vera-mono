"""Conservative lexical retrieval over already-authorized historical evidence.

Recovers the useful idea of lexical candidate ranking from the archived
v0.2.2 retrieval adapter without copying its old canonical SQLite kernel,
bypassing governance, creating persistent indexes, or changing current memory.

Not semantic search, not corroboration, and not authority for present facts.
"""
from __future__ import annotations

import re

from .historical_evidence import (
    HistoricalEvidenceRecord,
    HistoricalEvidenceResult,
    query_historical_evidence,
)

_MAX_QUERY_CHARS = 512
_MAX_QUERY_TERMS = 16
_MAX_AUTHORIZED_RECORDS = 4096
_MAX_TEXT_CHARS = 131072
_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


def _terms(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_PATTERN.findall(text.casefold()))


def search_historical_evidence(
    records: tuple[HistoricalEvidenceRecord, ...],
    *,
    query: str,
    authorized_privacy_scopes: tuple[str, ...],
    retrieved_at: str,
    max_results: int = 10,
) -> HistoricalEvidenceResult:
    """Return whole-token matches from the explicitly authorized evidence.

    Only the exact content['text'] field is searchable; a field-absent or
    non-string value is not indexed. Ranking counts matching distinct
    query terms, then breaks ties by stable memory_id. This rank is lexical
    relevance alone; it cannot change provenance, privacy, currentness,
    historical canonicity, or the source's evidentiary ceiling.

    Search always invokes the original privacy gate before inspecting text.
    No new authorization, memory write, file, index, embedding, or trace.
    """
    if type(query) is not str or not 1 <= len(query) <= _MAX_QUERY_CHARS:
        raise ValueError("lexical query must be a bounded exact string")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in query):
        raise ValueError("lexical query must not contain control characters")
    terms = _terms(query)
    if not terms or len(terms) > _MAX_QUERY_TERMS:
        raise ValueError("lexical query must contain 1..16 distinct word terms")
    if type(max_results) is not int or not 1 <= max_results <= 100:
        raise ValueError("max_results must be an exact integer 1..100")

    # This project's existing gate is the sole owner of authorization.
    visible = query_historical_evidence(
        records, authorized_privacy_scopes=authorized_privacy_scopes,
        retrieved_at=retrieved_at,
    )
    if len(visible.records) > _MAX_AUTHORIZED_RECORDS:
        raise ValueError("authorized historical evidence count exceeds bounded search")
    seen: set[str] = set()
    matches: list[tuple[int, str, HistoricalEvidenceRecord]] = []
    for record in visible.records:
        if record.memory_id in seen:
            raise ValueError("duplicate authorized historical evidence memory_id")
        seen.add(record.memory_id)
        if record.content is None:
            continue
        value = record.content.get("text")
        if type(value) is not str:
            continue
        if len(value) > _MAX_TEXT_CHARS:
            raise ValueError("authorized historical text exceeds bounded lexical search")
        overlap = len(terms.intersection(_terms(value)))
        if overlap:
            matches.append((-overlap, record.memory_id, record))
    matches.sort(key=lambda item: (item[0], item[1]))

    return HistoricalEvidenceResult(
        records=tuple(item[2] for item in matches[:max_results]),
        authorized_privacy_scopes=visible.authorized_privacy_scopes,
        retrieved_at=visible.retrieved_at,
    )
