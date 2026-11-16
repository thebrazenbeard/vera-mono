"""Bounded exact public-question aliases supplied by a separately trusted host.

This is not semantic search, source discovery, memory admission, authorization,
an identity verifier, or model inference. The host independently owns a small
question-to-record mapping and the approved PUBLIC-memory provider. An alias
is not evidence that the mapped record exists or is approved: the exact reader
must independently re-observe the host broker and verify the selected record.
"""
from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from . import compose, host_exact_reader
from .host_exact_reader import HostSourceRefused

MAX_ALIASES = 16
MAX_QUESTION_BYTES = 160
QUESTION = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ?'.,:-]{0,159}\Z")


def _normalize(value: str) -> str:
    if (type(value) is not str or not value
            or len(value) > MAX_QUESTION_BYTES
            or any(c in value for c in "\t\r\n")
            or QUESTION.fullmatch(value.strip()) is None):
        raise HostSourceRefused("unapproved or invalid exact question")
    return " ".join(value.strip().lower().split())


def _host_alias_snapshot(aliases: dict[str, str]) -> tuple[
        tuple[tuple[str, str], ...], dict[str, str]]:
    if type(aliases) is not dict or not (1 <= len(aliases) <= MAX_ALIASES):
        raise HostSourceRefused("invalid host question allowlist")
    canonical: dict[str, str] = {}
    for phrase, record_id in aliases.items():
        normalized = _normalize(phrase)
        if (type(record_id) is not str
                or compose.ID.fullmatch(record_id) is None
                or normalized in canonical):
            raise HostSourceRefused("ambiguous or invalid host question allowlist")
        canonical[normalized] = record_id
    return tuple(sorted(aliases.items())), canonical


def read_allowed_question(
    provider: Callable[[], tuple[dict[str, Any], bytes, int]], *,
    question: str, aliases: dict[str, str],
) -> dict[str, Any]:
    """Match only a host-approved literal phrase; retrieve one exact PUBLIC ID.

    Return no record identifiers for unmatched phrases. Changes in the host
    alias mapping during a source read fail closed before printing an answer.
    The separately trusted host must prevent edits *after* this check.
    """
    if not callable(provider):
        raise HostSourceRefused("trusted live provider required")
    original, choices = _host_alias_snapshot(aliases)
    normalized = _normalize(question)
    selected_id = choices.get(normalized)
    if selected_id is None:
        # No read or enumeration of the private or public ledger on a miss.
        return {
            "schema": "MINI_VERA_HOST_PUBLIC_EXACT_READ_V1",
            "status": "UNKNOWN", "answer": "UNKNOWN", "source": None,
            "origin": "HOST_QUESTION_ALIAS_UNMATCHED_NOT_NEURAL",
            "resolution": "HOST_ALLOWLIST_EXACT_QUESTION_NOT_SEMANTIC",
            "authority": "HOST_CALLBACK_TRUST_NOT_INDEPENDENTLY_ATTESTED",
            "host_issuer_qualified": False, "model_http_calls": 0, "writes": 0,
        }
    try:
        result = host_exact_reader.read_public_record(
            provider, record_id=selected_id)
        # The allowlist is externally supplied by an authorized host process;
        # do not accept a changed mapping even if the same ID would still match.
        current, _ = _host_alias_snapshot(aliases)
        if current != original:
            raise HostSourceRefused("host question mapping changed before release")
    except Exception:
        # Host errors may include private record data or policy details.
        raise HostSourceRefused("host question source withheld or changed") from None
    result["resolution"] = "HOST_APPROVED_EXACT_QUESTION_ALIAS_NOT_NEURAL"
    return result