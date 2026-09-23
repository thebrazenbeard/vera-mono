"""Fail-closed, externally authenticated temporal orientation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

from .canonical import canonical_sha256
from .signatures import public_key_id, verify_signature


class OrientationState(str, Enum):
    COMPLETE = "COMPLETE"
    COMPLETE_FROM_FRESH_SNAPSHOT = "COMPLETE_FROM_FRESH_SNAPSHOT"
    DEGRADED_BOUNDED = "DEGRADED_BOUNDED"
    STALE = "STALE"
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


CURRENT_TIME = "current_time"
SEMANTIC_TIME_DIMENSIONS = (
    "current_chat_time",
    "project_interaction_time",
    "durable_state_time",
    "event_time",
    "record_time",
    "retrieval_time",
)
REQUIRED_DIMENSIONS = (CURRENT_TIME, *SEMANTIC_TIME_DIMENSIONS)
SOURCE_MODES = {"CURRENT_SOURCE", "FRESH_BOUND_SNAPSHOT"}

# Only these bounded claim classes may authorize DEGRADED_BOUNDED.  The mapping is
# part of the contract, rather than a caller-provided free-form description.
CLAIM_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "event_timestamp": (CURRENT_TIME, "event_time"),
    "record_freshness": (CURRENT_TIME, "record_time", "retrieval_time"),
    "project_state_freshness": (
        CURRENT_TIME,
        "project_interaction_time",
        "durable_state_time",
        "retrieval_time",
    ),
}
_SCOPE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ClaimScope:
    scope_id: str
    claims: tuple[str, ...]

    def validate(self) -> None:
        if not isinstance(self.scope_id, str) or not _SCOPE_ID.fullmatch(self.scope_id):
            raise ValueError("claim scope ID is invalid")
        if not self.claims or len(self.claims) != len(set(self.claims)):
            raise ValueError("claim scope must contain unique claims")
        unknown = set(self.claims) - set(CLAIM_DIMENSIONS)
        if unknown:
            raise ValueError(f"claim scope contains unknown claims: {sorted(unknown)}")

    def required_dimensions(self) -> tuple[str, ...]:
        self.validate()
        required: list[str] = []
        for claim in self.claims:
            for dimension in CLAIM_DIMENSIONS[claim]:
                if dimension not in required:
                    required.append(dimension)
        return tuple(required)

    def as_dict(self) -> dict[str, object]:
        self.validate()
        return {"scope_id": self.scope_id, "claims": list(self.claims)}


def normalize_claim_scope(value: ClaimScope | Mapping[str, Any] | None) -> ClaimScope | None:
    if value is None:
        return None
    if isinstance(value, ClaimScope):
        value.validate()
        return value
    if not isinstance(value, Mapping) or set(value) != {"scope_id", "claims"}:
        raise ValueError("claim scope fields are missing or unknown")
    claims = value["claims"]
    if not isinstance(claims, (list, tuple)) or isinstance(claims, (str, bytes)):
        raise ValueError("claim scope claims must be a list")
    if any(not isinstance(item, str) or not item for item in claims):
        raise ValueError("claim scope claims must be nonempty strings")
    scope = ClaimScope(str(value["scope_id"]), tuple(claims))
    scope.validate()
    return scope


@dataclass(frozen=True)
class TimeEvidence:
    dimension: str
    value: str
    source: str
    source_kind: str
    observed_at: str
    source_digest: str
    source_key_id: str
    source_signature: str
    lower_bound: str | None = None
    upper_bound: str | None = None

    def signed_body(self) -> dict[str, str | None]:
        return {
            "dimension": self.dimension,
            "value": self.value,
            "source": self.source,
            "source_kind": self.source_kind,
            "observed_at": self.observed_at,
            "source_digest": self.source_digest,
            "source_key_id": self.source_key_id,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
        }

    def evidence_id(self) -> str:
        return canonical_sha256(self.as_dict())

    def validate(self, trusted_source_keys: Mapping[str, Mapping[str, Any]]) -> None:
        key = trusted_source_keys.get(self.source)
        if (
            key is None
            or public_key_id(key) != self.source_key_id
            or not verify_signature(self.signed_body(), self.source_signature, key)
        ):
            raise ValueError("time evidence source authentication mismatch")
        if self.dimension not in REQUIRED_DIMENSIONS:
            raise ValueError("unknown time dimension")
        if not self.source or not self.source_digest:
            raise ValueError("source and source digest are required")
        if self.source_kind != self.dimension:
            raise ValueError("time evidence source kind mismatch")
        if len(self.source_digest) != 64 or any(
            c not in "0123456789abcdef" for c in self.source_digest
        ):
            raise ValueError("source digest must be lowercase SHA-256")
        value = parse_time(self.value)
        observed = parse_time(self.observed_at)
        lower = parse_time(self.lower_bound) if self.lower_bound else None
        upper = parse_time(self.upper_bound) if self.upper_bound else None
        if (lower is None) != (upper is None):
            raise ValueError("bounded evidence requires both bounds")
        if lower and (lower > upper or value < lower or value > upper):
            raise ValueError("invalid temporal bounds")
        if observed < value - timedelta(minutes=5):
            raise ValueError("observation predates value")

    def as_dict(self) -> dict[str, str | None]:
        return self.signed_body() | {"source_signature": self.source_signature}


@dataclass(frozen=True)
class OrientationReceipt:
    state: OrientationState
    evaluated_at: str
    evidence_digest: str
    missing_dimensions: tuple[str, ...]
    stale_dimensions: tuple[str, ...]
    conflicted_dimensions: tuple[str, ...]
    invalid_dimensions: tuple[str, ...]
    claims_allowed: bool
    source_mode: str
    required_dimensions: tuple[str, ...]
    claim_scope: dict[str, object] | None
    claim_scope_digest: str | None
    bounded_claims_only: bool
    supporting_evidence_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "VERA_R8A0_TEMPORAL_ORIENTATION_RECEIPT_V3",
            "state": self.state.value,
            "evaluated_at": self.evaluated_at,
            "evidence_digest": self.evidence_digest,
            "missing_dimensions": list(self.missing_dimensions),
            "stale_dimensions": list(self.stale_dimensions),
            "conflicted_dimensions": list(self.conflicted_dimensions),
            "invalid_dimensions": list(self.invalid_dimensions),
            "claims_allowed": self.claims_allowed,
            "source_mode": self.source_mode,
            "required_dimensions": list(self.required_dimensions),
            "claim_scope": self.claim_scope,
            "claim_scope_digest": self.claim_scope_digest,
            "bounded_claims_only": self.bounded_claims_only,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
        }


class OrientationGate:
    def __init__(
        self,
        *,
        trusted_source_keys: Mapping[str, Mapping[str, Any]],
        max_age: timedelta = timedelta(minutes=10),
    ) -> None:
        if not trusted_source_keys:
            raise ValueError("trusted temporal source keys are required")
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        self.keys = dict(trusted_source_keys)
        self.max_age = max_age

    def evaluate(
        self,
        evidence: Iterable[TimeEvidence],
        *,
        now: datetime,
        required_dimensions: Iterable[str] = REQUIRED_DIMENSIONS,
        source_mode: str = "CURRENT_SOURCE",
        degraded_allowed: bool = False,
        claim_scope: ClaimScope | Mapping[str, Any] | None = None,
        response_scope: str | None = None,
    ) -> OrientationReceipt:
        if response_scope is not None:
            raise ValueError("free-form response_scope is unsupported; use claim_scope")
        if now.tzinfo is None:
            raise ValueError("now must include a timezone")
        if source_mode not in SOURCE_MODES:
            raise ValueError("unsupported source mode")
        now = now.astimezone(timezone.utc)
        required = tuple(dict.fromkeys(required_dimensions))
        scope = normalize_claim_scope(claim_scope)
        if not required or any(dimension not in REQUIRED_DIMENSIONS for dimension in required):
            raise ValueError("required dimensions are empty or unknown")
        if CURRENT_TIME not in required:
            raise ValueError("every temporal scope must require current_time")
        if scope is not None and set(required) != set(scope.required_dimensions()):
            raise ValueError("claim scope does not map exactly to required dimensions")

        grouped: dict[str, list[TimeEvidence]] = {}
        invalid: set[str] = set()
        rows: list[dict[str, str | None]] = []
        for item in evidence:
            grouped.setdefault(item.dimension, []).append(item)
            rows.append(item.as_dict())
            try:
                item.validate(self.keys)
            except ValueError:
                invalid.add(item.dimension)

        missing = tuple(sorted(set(required) - set(grouped)))
        stale: set[str] = set()
        conflict: set[str] = set()
        for dimension, items in grouped.items():
            valid = [item for item in items if dimension not in invalid]
            if len(valid) > 1:
                conflict.add(dimension)
            for item in valid:
                observed = parse_time(item.observed_at)
                value = parse_time(item.value)
                if now - observed > self.max_age or observed - now > timedelta(minutes=5):
                    stale.add(dimension)
                if dimension == CURRENT_TIME and abs(now - value) > self.max_age:
                    stale.add(dimension)
                if source_mode == "FRESH_BOUND_SNAPSHOT" and not (
                    item.lower_bound and item.upper_bound
                ):
                    invalid.add(dimension)

        full = set(required) == set(REQUIRED_DIMENSIONS)
        selected = [grouped[d][0] for d in required if len(grouped.get(d, ())) == 1]
        bounded = len(selected) == len(required) and all(
            item.lower_bound and item.upper_bound for item in selected
        )
        structured_bounded = degraded_allowed and scope is not None and bounded

        if conflict:
            state = OrientationState.CONFLICTED
        elif invalid or missing:
            state = OrientationState.UNKNOWN
        elif stale:
            state = OrientationState.STALE
        elif source_mode == "FRESH_BOUND_SNAPSHOT":
            if full:
                state = OrientationState.COMPLETE_FROM_FRESH_SNAPSHOT
            else:
                state = (
                    OrientationState.DEGRADED_BOUNDED
                    if structured_bounded
                    else OrientationState.UNKNOWN
                )
        elif full:
            state = OrientationState.COMPLETE
        else:
            state = (
                OrientationState.DEGRADED_BOUNDED
                if structured_bounded
                else OrientationState.UNKNOWN
            )

        allowed = state in {
            OrientationState.COMPLETE,
            OrientationState.COMPLETE_FROM_FRESH_SNAPSHOT,
            OrientationState.DEGRADED_BOUNDED,
        }
        scope_dict = scope.as_dict() if scope else None
        scope_digest = canonical_sha256(
            {"claim_scope": scope_dict, "required_dimensions": list(required)}
        ) if scope else None
        support = (
            tuple(item.evidence_id() for item in selected)
            if state is OrientationState.DEGRADED_BOUNDED
            else ()
        )
        return OrientationReceipt(
            state,
            now.isoformat(),
            canonical_sha256(rows),
            missing,
            tuple(sorted(stale)),
            tuple(sorted(conflict)),
            tuple(sorted(invalid)),
            allowed,
            source_mode,
            required,
            scope_dict,
            scope_digest,
            state is OrientationState.DEGRADED_BOUNDED,
            support,
        )


def evidence_from_mapping(
    rows: Mapping[str, Mapping[str, str | None]],
) -> list[TimeEvidence]:
    output: list[TimeEvidence] = []
    required = {
        "dimension",
        "value",
        "source",
        "source_kind",
        "observed_at",
        "source_digest",
        "source_key_id",
        "source_signature",
        "lower_bound",
        "upper_bound",
    }
    for dimension, row in rows.items():
        if set(row) != required or row["dimension"] != dimension:
            raise ValueError("time evidence fields or dimension mismatch")
        output.append(
            TimeEvidence(
                dimension,
                str(row["value"]),
                str(row["source"]),
                str(row["source_kind"]),
                str(row["observed_at"]),
                str(row["source_digest"]),
                str(row["source_key_id"]),
                str(row["source_signature"]),
                str(row["lower_bound"]) if row["lower_bound"] else None,
                str(row["upper_bound"]) if row["upper_bound"] else None,
            )
        )
    return output
