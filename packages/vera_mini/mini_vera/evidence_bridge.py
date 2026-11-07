"""Opt-in, read-only evidence projection for Mini-Vera dialogue.

Source interfaces inspected at immutable Git heads (2026-11-07):

* stm c40431c77e00a9b6b817641d07768d95bdd9c238:
  ``MemorySession.retrieve`` returns ``MemoryRecord`` values; the session and
  its host policy own source authorization.
* deepmemorystorage 47681d52923d05a66060e60a88c5e020e540f8c1:
  ``tools/query_deep_memory.py --json`` returns a privacy-filtered historical
  envelope, NOT current memory or an authorization grant.
* semanticatlas 0de62696aa2ce31ee31e5e81c91715e271beeb95:
  ``load_committed_bundle`` returns a manifest-verified derived view and index,
  not ready-to-display facts; no direct adapter is warranted.
* ingest 5a33541001eb93529439829b0e766e366117e944:
  ``IngestResult`` carries artifact metadata and receipts, not trustworthy
  normalized text; no direct adapter is warranted.

This module never connects to a provider, reads a file, mutates a store,
automatically enables memory, or grants source access. The embedding host must
perform source authentication/consent and supply a pure per-record authorizer.
Calling it with ``enabled=False`` does not inspect the source records.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import is_dataclass
from datetime import datetime, timezone
import re
from typing import Any

from .dialogue import respond


class EvidenceBridgeError(ValueError):
    """Malformed or unverifiable read-only evidence input."""


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}\Z")
_DMS_SCHEMA = "VERA_DEEP_MEMORY_EVIDENCE_RESULT_V1"
_DMS_SEMANTICS = "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY"
_DMS_MODE = "AUTHORIZED_SCOPE_FILTER"
_MAX_RECORDS = 12
_MAX_SCAN = 100
_MAX_EXCERPT = 400
_UNSAFE = re.compile(
    r"(?i)(?:\b(?:password|passphrase|credential|secret|api[_ -]?key|"
    r"access[_ -]?token|bearer\s+[a-z0-9._~+/-]{8,})\b|"
    r"(?:ignore|override|disregard)\s+(?:all\s+)?(?:previous|prior|"
    r"system|developer)\s+(?:instructions|rules|prompts)|"
    r"(?:system|developer)\s*:\s*(?:you\s+must|ignore|reveal)|"
    r"(?:reveal|dump|print)\s+(?:the\s+)?(?:secret|system\s+prompt))"
)


def _on(enabled: bool, authorize: Callable[[str, object], bool] | None) -> bool:
    if enabled is not True:
        return False
    if not callable(authorize):
        raise EvidenceBridgeError("enabled evidence requires a host authorizer")
    return True


def _valid_text(value: object) -> bool:
    return (type(value) is str and 1 <= len(value.strip()) <= _MAX_EXCERPT
            and _UNSAFE.search(value) is None)


def _valid_id(value: object) -> bool:
    return type(value) is str and _ID.fullmatch(value) is not None


def _approved(authorize: Callable[[str, object], bool], kind: str, record: object) -> bool:
    """Only literal True is an approval; policy errors fail closed."""
    try:
        return authorize(kind, record) is True
    except Exception:
        return False


def _stm_field(record: object, name: str) -> Any:
    # Accept an actual STM dataclass or a caller-supplied field-compatible
    # dataclass for isolated tests; arbitrary objects/properties are rejected.
    return getattr(record, name, None)


def stm_facts(
    records: Sequence[object] = (), *, scope: object,
    latest_versions: Mapping[str, int] | None = None,
    authorize: Callable[[str, object], bool] | None = None,
    enabled: bool = False, now: datetime | None = None,
) -> tuple[dict[str, object], ...]:
    """Project already-retrieved STM observations; never call STM or write to it.

    ``scope`` must be the exact host-selected ``stm.models.SessionKey`` (or
    field-compatible test value). A matching scope is necessary, not a grant;
    the independently supplied authorizer is mandatory. Private, historical,
    hypothetical, expired, assistant-authored, stale, duplicated, and malformed
    entries are never projected. A current-version map must come from a fresh
    authenticated host store readback; this function cannot authenticate it.
    """
    if not _on(enabled, authorize):
        return ()
    if isinstance(scope, type) or not is_dataclass(scope) or not all(
        _valid_id(getattr(scope, field, None))
        for field in ("tenant_id", "owner_id", "agent_id", "session_id")
    ):
        raise EvidenceBridgeError("expected exact STM SessionKey scope")
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise EvidenceBridgeError("now must be timezone aware")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise EvidenceBridgeError("STM records must be an already-retrieved sequence")
    if len(records) > _MAX_SCAN:
        raise EvidenceBridgeError("STM record input exceeds scan bound")
    if (not isinstance(latest_versions, Mapping)
            or any(not _valid_id(key) or type(value) is not int or value < 1
                   for key, value in latest_versions.items())):
        raise EvidenceBridgeError("fresh host-confirmed STM latest-version map required")
    ids = [value for item in records
           if not isinstance(item, type) and is_dataclass(item)
           if _valid_id(value := _stm_field(item, "id"))]
    duplicated_ids = {value for value in ids if ids.count(value) > 1}

    facts: list[dict[str, object]] = []
    for record in records:
        if isinstance(record, type) or not is_dataclass(record) or _stm_field(record, "scope") != scope:
            continue
        if (_stm_field(record, "kind") != "observation"
                or _stm_field(record, "role") != "user"
                or _stm_field(record, "privacy") not in ("session", "shared")
                or _stm_field(record, "origin") != "direct"):
            continue
        record_id, body = _stm_field(record, "id"), _stm_field(record, "content")
        version = _stm_field(record, "version")
        expiry = _stm_field(record, "expires_at")
        if (not _valid_id(record_id) or not _valid_text(body)
                or type(version) is not int or version < 1
                or latest_versions.get(record_id) != version
                or record_id in duplicated_ids
                or not _valid_text(_stm_field(record, "source"))):
            continue
        if expiry is not None:
            if not isinstance(expiry, datetime) or expiry.tzinfo is None or expiry <= now:
                continue
        if not _approved(authorize, "stm", record):
            continue
        facts.append({
            "key": f"session observation {record_id}",
            "excerpt": body.strip(),
            "citation": f"stm:{record_id}:v{version}",
            "source": "host-authorized STM observation (not independent proof)",
            "visibility": "visible", "classification": "unclassified",
        })
        if len(facts) == _MAX_RECORDS:
            break
    return tuple(facts)


def deepmemory_facts(
    envelope: Mapping[str, Any] | None = None, *,
    authorized_privacy_scopes: frozenset[str],
    authorize: Callable[[str, object], bool] | None = None,
    enabled: bool = False,
) -> tuple[dict[str, object], ...]:
    """Project the archive's *historical-only* query envelope, explicitly opted in.

    Archive ``authorized_privacy_scopes`` are only reported source metadata;
    the host must independently authorize every row. Audit-all envelopes,
    unknown scope, noncanonical rows, and rows without source IDs fail closed.
    """
    if not _on(enabled, authorize):
        return ()
    if (not isinstance(authorized_privacy_scopes, frozenset)
            or not authorized_privacy_scopes
            or any(not _valid_id(item) for item in authorized_privacy_scopes)):
        raise EvidenceBridgeError("exact host-authorized privacy scopes required")
    if not isinstance(envelope, Mapping):
        raise EvidenceBridgeError("DeepMemory JSON envelope required")
    reported_scopes = envelope.get("authorized_privacy_scopes")
    results = envelope.get("results")
    if (envelope.get("schema") != _DMS_SCHEMA
            or envelope.get("privacy_mode") != _DMS_MODE
            or not isinstance(reported_scopes, list)
            or any(not _valid_id(scope) for scope in reported_scopes)
            or set(reported_scopes) != authorized_privacy_scopes
            or not isinstance(results, list)
            or len(results) > _MAX_SCAN
            or type(envelope.get("count")) is not int
            or envelope["count"] != len(results)):
        raise EvidenceBridgeError("invalid or audit-all DeepMemory envelope")

    facts: list[dict[str, object]] = []
    for record in results:
        if not isinstance(record, Mapping):
            continue
        record_id = record.get("memory_id")
        excerpt = record.get("observed_event")
        sources = record.get("source_ids")
        privacy = record.get("privacy_scope")
        if (record.get("result_semantics") != _DMS_SEMANTICS
                or record.get("historical_canonicity") != "CANONICAL_HISTORY"
                or type(privacy) is not str or privacy not in authorized_privacy_scopes
                or not _valid_id(record_id) or not _valid_text(excerpt)
                or not isinstance(sources, list) or not sources
                or len(sources) > 12 or any(not _valid_id(item) for item in sources)):
            continue
        if not _approved(authorize, "deepmemorystorage", record):
            continue
        facts.append({
            "key": f"historical observation {record_id}",
            "excerpt": "Historical evidence only, not current state: " + excerpt.strip(),
            "citation": f"deepmemory:{record_id}",
            "source": "host-authorized DeepMemory archive (historical only)",
            "visibility": "visible", "classification": "unclassified",
        })
        if len(facts) == _MAX_RECORDS:
            break
    return tuple(facts)


def respond_with_evidence(
    question: str, *, stm_records: Sequence[object] = (),
    stm_scope: object = None, stm_latest_versions: Mapping[str, int] | None = None,
    deepmemory_envelope: Mapping[str, Any] | None = None,
    authorized_privacy_scopes: frozenset[str] = frozenset(),
    authorize: Callable[[str, object], bool] | None = None,
    enabled: bool = False, history: object = None, identity: object = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Call Mini-Vera's existing `dialogue.respond` with opt-in vetted facts.

    This is a standalone API, **not** an automatic `MiniVera.ask` hook or a
    persistent memory installation. No file, network, model or provider calls.
    """
    if enabled is not True:
        return respond(question, facts=(), history=history, identity=identity)
    if not callable(authorize):
        raise EvidenceBridgeError("enabled evidence requires a host authorizer")
    facts: list[dict[str, object]] = []
    if stm_records:
        facts.extend(stm_facts(stm_records, scope=stm_scope,
                               latest_versions=stm_latest_versions, authorize=authorize,
                               enabled=True, now=now))
    if deepmemory_envelope is not None:
        facts.extend(deepmemory_facts(
            deepmemory_envelope, authorized_privacy_scopes=authorized_privacy_scopes,
            authorize=authorize, enabled=True))
    return respond(question, facts=facts[:_MAX_RECORDS], history=history, identity=identity)
