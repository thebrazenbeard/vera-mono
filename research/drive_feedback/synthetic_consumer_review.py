"""Offline-only DRIVE -> MESO/Volition compatibility review.

This file is deliberately outside the installed Vera packages. It cannot
authenticate a witness, admit a MESO observation, or complete a Volition goal.
Every result is HOLD; passing structural checks only exposes a synthetic
candidate for review. Never wire this module into a running consumer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from hashlib import sha256
import json
import re


MAX_AGE_MS = 60_000
MAX_FUTURE_SKEW_MS = 5_000
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class SyntheticNeedCandidate:
    """Untrusted review data, not an admitted MESO NeedObservation."""

    event_id: str
    need_id: str
    measured_level: float
    observed_at_ms: int
    evidence_digest: str
    effect_authority: bool = False


@dataclass(frozen=True, slots=True)
class ConsumerReview:
    status: str
    reason: str
    candidate: SyntheticNeedCandidate | None = None
    effect_authority: bool = False


def review_synthetic_outbox(
    item: object,
    observation: object | None = None,
    admission: object | None = None,
    *,
    now_ms: int | None = None,
    current_need_revision: int | None = None,
) -> ConsumerReview:
    """Check *structural* compatibility without granting downstream authority.

    The DRIVE v1 outbox lacks a historical absolute level, full observer
    witness custody, exact goal/choice bindings, Volition target and positive
    goal revision, and consumer acknowledgements. For a current need revision,
    an explicitly provided matching original observation can produce a
    synthetic review candidate. Old or replayed events cannot do so.

    Neither a caller-supplied observation/admission nor a SHA-256 comparison
    proves external source authentication. Consequently there is intentionally
    no READY, ACCEPT, or APPLY state, even for a structurally matching input.
    """

    def hold(reason: str) -> ConsumerReview:
        return ConsumerReview("HOLD", reason)

    if item is None or observation is None or admission is None:
        return hold("MISSING_SOURCE_RECORD")
    if type(now_ms) is not int or not 0 < now_ms < 2**63:
        return hold("UNTRUSTED_OR_INVALID_CLOCK")
    if type(current_need_revision) is not int or current_need_revision < 0:
        return hold("MISSING_CURRENT_NEED_REVISION")
    if (
        getattr(admission, "status", None) != "ADMITTED"
        or getattr(admission, "replayed", None) is not False
    ):
        return hold("NOT_FRESHLY_ADMITTED")
    observed_at = getattr(observation, "observed_at_ms", None)
    if type(observed_at) is not int or not 0 < observed_at < 2**63:
        return hold("INVALID_OBSERVATION_TIME")
    if not now_ms - MAX_AGE_MS <= observed_at <= now_ms + MAX_FUTURE_SKEW_MS:
        return hold("OBSERVATION_NOT_FRESH")
    if not is_dataclass(observation) or isinstance(observation, type):
        return hold("INVALID_SOURCE_OBSERVATION")
    if any(
        type(getattr(observation, field, None)) is not str
        or _IDENTIFIER.fullmatch(getattr(observation, field, "")) is None
        for field in ("event_id", "need_id")
    ):
        return hold("INVALID_SOURCE_IDENTIFIERS")
    evidence_digest = getattr(observation, "evidence_digest", None)
    if type(evidence_digest) is not str or _DIGEST.fullmatch(evidence_digest) is None:
        return hold("INVALID_SOURCE_EVIDENCE_DIGEST")
    try:
        digest = sha256(
            json.dumps(
                asdict(observation), sort_keys=True, separators=(",", ":"),
                allow_nan=False, ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError, OverflowError):
        return hold("INVALID_SOURCE_OBSERVATION")
    next_revision = getattr(observation, "expected_need_revision", None)
    if type(next_revision) is not int or not 0 <= next_revision < 2**63 - 1:
        return hold("INVALID_SOURCE_NEED_REVISION")
    next_revision += 1
    if not all((
        getattr(record, "event_id", None) == observation.event_id
        for record in (item, admission)
    )) or not all((
        getattr(record, "claim_sha256", None) == digest
        for record in (item, admission)
    )) or not all((
        getattr(record, "need_revision", None) == next_revision
        for record in (item, admission)
    )) or getattr(item, "need_id", None) != getattr(observation, "need_id", None):
        return hold("SOURCE_OUTBOX_BINDING_MISMATCH")
    if (
        getattr(item, "goal_credit", None) is not getattr(admission, "goal_credit", None)
        or getattr(item, "goal_credit_reason", None) != getattr(admission, "goal_credit_reason", None)
    ):
        return hold("GOAL_CREDIT_BINDING_MISMATCH")
    if current_need_revision != next_revision:
        # Reading the current projection after another receipt cannot recover
        # the level belonging to this older outbox item.
        return hold("OUTBOX_LEVEL_SUPERSEDED")
    level = getattr(observation, "absolute_post_level", None)
    if type(level) not in (float, int) or not 0 <= level <= 1:
        return hold("INVALID_NEED_LEVEL")
    if getattr(observation, "unit", None) != "normalized":
        return hold("INCOMPATIBLE_NEED_UNIT")
    return ConsumerReview(
        "HOLD",
        "NO_INDEPENDENT_WITNESS_OR_DOWNSTREAM_ADMISSION",
        SyntheticNeedCandidate(
            event_id=observation.event_id,
            need_id=observation.need_id,
            measured_level=float(level),
            observed_at_ms=observed_at,
            evidence_digest=observation.evidence_digest,
        ),
    )
