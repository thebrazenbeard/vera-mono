from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex


@dataclass(frozen=True, slots=True)
class Snapshot:
    subject_id: str
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        if type(self.subject_id) is not str or not self.subject_id:
            raise ValueError("subject_id must be a non-empty exact string")
        if not isinstance(self.values, Mapping):
            raise TypeError("values must be a mapping")

    @property
    def digest(self) -> str:
        return sha256_hex(
            canonical_json_bytes(
                {"subject_id": self.subject_id, "values": dict(self.values)}
            )
        )


@dataclass(frozen=True, slots=True)
class DriftPolicy:
    critical_fields: tuple[str, ...]
    mutable_fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        groups = (self.critical_fields, self.mutable_fields, self.required_fields)
        if any(type(group) is not tuple for group in groups):
            raise TypeError("drift policy fields must be tuples")
        if any(type(item) is not str or not item for group in groups for item in group):
            raise ValueError("drift policy field names must be non-empty exact strings")
        if set(self.critical_fields) & set(self.mutable_fields):
            raise ValueError("critical_fields and mutable_fields cannot overlap")


@dataclass(frozen=True, slots=True)
class DriftFinding:
    field: str
    baseline: Any
    candidate: Any
    severity: str
    code: str


@dataclass(frozen=True, slots=True)
class DriftReport:
    subject_id: str
    baseline_digest: str
    candidate_digest: str
    status: str
    findings: tuple[DriftFinding, ...]
    independent_review: bool = False
    claim_ceiling: str = "INTERNAL_DETERMINISTIC_CHECK_NOT_INDEPENDENT_VALIDATION"

    @property
    def drifted(self) -> bool:
        return bool(self.findings)


def compare_snapshots(
    baseline: Snapshot,
    candidate: Snapshot,
    policy: DriftPolicy,
) -> DriftReport:
    if type(baseline) is not Snapshot or type(candidate) is not Snapshot:
        raise TypeError("baseline and candidate must be exact Snapshot values")
    if baseline.subject_id != candidate.subject_id:
        raise ValueError("snapshot subject mismatch")

    base = dict(baseline.values)
    cand = dict(candidate.values)
    findings: list[DriftFinding] = []
    critical = set(policy.critical_fields)
    mutable = set(policy.mutable_fields)

    for field in policy.required_fields:
        if field not in cand:
            findings.append(
                DriftFinding(
                    field=field,
                    baseline=base.get(field),
                    candidate=None,
                    severity="BLOCK",
                    code="REQUIRED_FIELD_MISSING",
                )
            )

    for field in sorted(set(base) | set(cand)):
        before = base.get(field)
        after = cand.get(field)
        if before == after:
            continue
        if field in mutable:
            continue
        if field in critical:
            severity = "BLOCK"
            code = "CRITICAL_DRIFT"
        else:
            severity = "WARN"
            code = "UNDECLARED_DRIFT"
        findings.append(
            DriftFinding(
                field=field,
                baseline=before,
                candidate=after,
                severity=severity,
                code=code,
            )
        )

    status = "BLOCK" if any(item.severity == "BLOCK" for item in findings) else (
        "WARN" if findings else "PASS"
    )
    return DriftReport(
        subject_id=baseline.subject_id,
        baseline_digest=baseline.digest,
        candidate_digest=candidate.digest,
        status=status,
        findings=tuple(findings),
    )
