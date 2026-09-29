"""Structured ambiguity guard for bounded AGI research.

This module is intentionally narrow. It does not parse natural language or
claim general uncertainty reasoning. It evaluates already-structured action
candidates and fails closed when evidence is conflicting, too weak, or too
close to separate safely.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class DecisionCandidate:
    action: str
    support: float
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.action) is not str or not self.action:
            raise ValueError("action must be a non-empty exact string")
        if isinstance(self.support, bool) or not isinstance(
            self.support,
            (int, float),
        ):
            raise TypeError("support must be numeric")
        support = float(self.support)
        if not math.isfinite(support) or not 0.0 <= support <= 1.0:
            raise ValueError("support must be finite and in [0, 1]")
        object.__setattr__(self, "support", support)
        if type(self.evidence_refs) is not tuple or any(
            type(item) is not str or not item
            for item in self.evidence_refs
        ):
            raise TypeError(
                "evidence_refs must be a tuple of non-empty exact strings"
            )


@dataclass(frozen=True, slots=True)
class StructuredAmbiguitySpec:
    spec_id: str
    surface_form: str
    candidates: tuple[DecisionCandidate, ...]
    min_support: float
    min_margin: float
    hard_conflict: bool = False

    def __post_init__(self) -> None:
        if type(self.spec_id) is not str or not self.spec_id:
            raise ValueError("spec_id must be a non-empty exact string")
        if type(self.surface_form) is not str or not self.surface_form.strip():
            raise ValueError("surface_form must be a non-empty exact string")
        if type(self.candidates) is not tuple or not self.candidates:
            raise ValueError("candidates must be a non-empty exact tuple")
        if any(type(item) is not DecisionCandidate for item in self.candidates):
            raise TypeError(
                "candidates must contain exact DecisionCandidate values"
            )
        actions = [item.action for item in self.candidates]
        if len(actions) != len(set(actions)):
            raise ValueError("candidate actions must be unique")
        for name in ("min_support", "min_margin"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            number = float(value)
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(f"{name} must be finite and in [0, 1]")
            object.__setattr__(self, name, number)
        if type(self.hard_conflict) is not bool:
            raise TypeError("hard_conflict must be bool")


@dataclass(frozen=True, slots=True)
class StructuredAmbiguityDecision:
    action: str | None
    confidence: float
    abstained: bool
    reason: str
    evidence_refs: tuple[str, ...]
    evidence_digest: str
    authorization_effect: str = "NONE"


class StructuredAmbiguityGuard:
    """Fail closed unless one structured action is clearly supported."""

    @staticmethod
    def _evidence_payload(
        spec: StructuredAmbiguitySpec,
    ) -> dict[str, object]:
        # Exclude spec_id and surface_form so wording/paraphrase changes do not
        # change the bound structured evidence.
        candidates = [
            {
                "action": item.action,
                "support": item.support,
                "evidence_refs": list(item.evidence_refs),
            }
            for item in sorted(spec.candidates, key=lambda value: value.action)
        ]
        return {
            "schema": "VERA_STRUCTURED_AMBIGUITY_EVIDENCE_V1",
            "candidates": candidates,
            "min_support": spec.min_support,
            "min_margin": spec.min_margin,
            "hard_conflict": spec.hard_conflict,
        }

    @classmethod
    def _digest(cls, spec: StructuredAmbiguitySpec) -> str:
        return hashlib.sha256(
            _canonical_json(cls._evidence_payload(spec))
        ).hexdigest()

    @staticmethod
    def _evidence_refs(
        candidates: tuple[DecisionCandidate, ...],
    ) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for candidate in candidates:
            for ref in candidate.evidence_refs:
                if ref not in seen:
                    seen.add(ref)
                    out.append(ref)
        return tuple(out)

    def resolve(
        self,
        spec: StructuredAmbiguitySpec,
    ) -> StructuredAmbiguityDecision:
        if type(spec) is not StructuredAmbiguitySpec:
            raise TypeError("spec must be exact StructuredAmbiguitySpec")

        ranked = tuple(
            sorted(
                spec.candidates,
                key=lambda item: (-item.support, item.action),
            )
        )
        top = ranked[0]
        evidence_refs = self._evidence_refs(ranked)
        digest = self._digest(spec)

        if spec.hard_conflict:
            return StructuredAmbiguityDecision(
                action=None,
                confidence=top.support,
                abstained=True,
                reason="HARD_CONFLICT",
                evidence_refs=evidence_refs,
                evidence_digest=digest,
            )

        if top.support < spec.min_support:
            return StructuredAmbiguityDecision(
                action=None,
                confidence=top.support,
                abstained=True,
                reason="INSUFFICIENT_SUPPORT",
                evidence_refs=evidence_refs,
                evidence_digest=digest,
            )

        if len(ranked) > 1:
            margin = top.support - ranked[1].support
            if margin < spec.min_margin:
                return StructuredAmbiguityDecision(
                    action=None,
                    confidence=top.support,
                    abstained=True,
                    reason="INSUFFICIENT_MARGIN",
                    evidence_refs=evidence_refs,
                    evidence_digest=digest,
                )

        return StructuredAmbiguityDecision(
            action=top.action,
            confidence=top.support,
            abstained=False,
            reason="CLEAR_WINNER",
            evidence_refs=top.evidence_refs,
            evidence_digest=digest,
        )
