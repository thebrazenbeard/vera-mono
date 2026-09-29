"""Evidence-bound learned model of an observed software portfolio.

Discovery may populate observations, declared/executable configuration,
derived relations, and hypotheses. It may not manufacture authorization.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
from typing import Any


class PortfolioFactDisposition(StrEnum):
    OBSERVED_SOURCE = "OBSERVED_SOURCE"
    DECLARED_CONFIGURATION = "DECLARED_CONFIGURATION"
    EXECUTABLE_CONFIGURATION = "EXECUTABLE_CONFIGURATION"
    DERIVED_RELATION = "DERIVED_RELATION"
    HYPOTHESIS = "HYPOTHESIS"
    VERIFIED_RELATION = "VERIFIED_RELATION"
    AUTHORIZED_CAPABILITY = "AUTHORIZED_CAPABILITY"


@dataclass(frozen=True, slots=True)
class PortfolioSystemFact:
    fact_id: str
    kind: str
    key: str
    value: Any
    disposition: PortfolioFactDisposition
    provenance: str
    confidence: float = 1.0
    currentness: str = "OBSERVED_AT_DISCOVERY"

    def __post_init__(self) -> None:
        for label, value in (
            ("fact_id", self.fact_id),
            ("kind", self.kind),
            ("key", self.key),
            ("provenance", self.provenance),
            ("currentness", self.currentness),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if type(self.disposition) is not PortfolioFactDisposition:
            raise TypeError("disposition must be exact PortfolioFactDisposition")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(slots=True)
class PortfolioSystemModel:
    facts: list[PortfolioSystemFact] = field(default_factory=list)

    def add_discovered_fact(self, fact: PortfolioSystemFact) -> None:
        if type(fact) is not PortfolioSystemFact:
            raise TypeError("fact must be exact PortfolioSystemFact")
        if fact.disposition is PortfolioFactDisposition.AUTHORIZED_CAPABILITY:
            raise ValueError(
                "discovery cannot manufacture authorization; "
                "authorization requires a separate authority admission"
            )
        if any(existing.fact_id == fact.fact_id for existing in self.facts):
            raise ValueError(f"duplicate fact_id: {fact.fact_id}")
        self.facts.append(fact)

    @staticmethod
    def _row(fact: PortfolioSystemFact) -> dict[str, Any]:
        row = asdict(fact)
        row["disposition"] = fact.disposition.value
        return row

    @property
    def digest(self) -> str:
        rows = [
            self._row(fact)
            for fact in sorted(self.facts, key=lambda item: item.fact_id)
        ]
        canonical = json.dumps(
            rows,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "VERA_PORTFOLIO_SYSTEM_MODEL_V1",
            "facts": [
                self._row(fact)
                for fact in sorted(self.facts, key=lambda item: item.fact_id)
            ],
            "digest": self.digest,
            "authority_effect": "NONE",
        }
