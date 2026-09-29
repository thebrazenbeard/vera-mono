"""Reviewed correction transfer over completed corrective-learning state.

This frontier is intentionally narrow. It demonstrates recurrence prevention
across case-distinct surface instances that share an already-bound failure
signature. It does not claim that Vera autonomously learned the classifier
that assigns failure signatures.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from vera_memory import (
    LearnedInfluenceGate,
    LearnedInfluenceReceipt,
    LearnedRevision,
)

from .corrective_learning import CorrectionState, CorrectiveStage


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _surface_digest(surface: dict[str, object]) -> str:
    if type(surface) is not dict:
        raise TypeError("surface must be an exact dict")
    return hashlib.sha256(
        _canonical_json(surface).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CorrectionRecurrence:
    case_id: str
    failure_signature_id: str
    surface: dict[str, object]

    def __post_init__(self) -> None:
        for field, value in (
            ("case_id", self.case_id),
            ("failure_signature_id", self.failure_signature_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{field} must be a non-empty exact string")
        if type(self.surface) is not dict:
            raise TypeError("surface must be an exact dict")
        # Fail closed if the surface is not canonically serializable.
        _canonical_json(self.surface)

    @property
    def surface_digest(self) -> str:
        return _surface_digest(self.surface)


@dataclass(frozen=True, slots=True)
class CorrectionTransferDecision:
    case_id: str
    outcome: str
    signature_match: bool
    case_distinct: bool
    surface_distinct: bool
    learned_influence: LearnedInfluenceReceipt | None
    authorization_effect: str = "NONE"


class ExactCaseCorrectionMemorizer:
    """Baseline that prevents only exact previously observed case IDs."""

    def __init__(self, prevented_case_ids: tuple[str, ...]) -> None:
        if (
            type(prevented_case_ids) is not tuple
            or not prevented_case_ids
            or any(
                type(case_id) is not str or not case_id
                for case_id in prevented_case_ids
            )
        ):
            raise ValueError(
                "prevented_case_ids must be a non-empty tuple of exact strings"
            )
        self._prevented = frozenset(prevented_case_ids)

    def should_prevent(self, recurrence: CorrectionRecurrence) -> bool:
        if type(recurrence) is not CorrectionRecurrence:
            raise TypeError(
                "recurrence must be exact CorrectionRecurrence"
            )
        return recurrence.case_id in self._prevented


class CorrectionTransferGuard:
    """Apply a reviewed completed correction to matching recurrences."""

    def __init__(
        self,
        *,
        correction: CorrectionState,
        revision: LearnedRevision,
        influence_gate: LearnedInfluenceGate,
        original_case_id: str,
        original_surface: dict[str, object] | None = None,
    ) -> None:
        if type(correction) is not CorrectionState:
            raise TypeError("correction must be exact CorrectionState")
        if correction.completed is not True:
            raise ValueError(
                "correction must be completed before transfer is allowed"
            )
        if correction.current_stage is not CorrectiveStage.PREVENT:
            raise ValueError(
                "correction must terminate at PREVENT before transfer"
            )
        final = correction.events[-1]
        if not final.guardrail_refs or not final.verification_refs:
            raise ValueError(
                "completed correction requires guardrail and verification refs"
            )
        if type(revision) is not LearnedRevision:
            raise TypeError("revision must be exact LearnedRevision")
        if revision.association_id != correction.failure_signature_id:
            raise ValueError(
                "learned revision association must bind the failure signature"
            )
        if revision.memory_revision_id != final.event_digest:
            raise ValueError(
                "learned revision must bind the completed correction ledger head"
            )
        if type(influence_gate) is not LearnedInfluenceGate:
            raise TypeError(
                "influence_gate must be exact LearnedInfluenceGate"
            )
        if type(original_case_id) is not str or not original_case_id:
            raise ValueError(
                "original_case_id must be a non-empty exact string"
            )

        self.correction = correction
        self.revision = revision
        self.influence_gate = influence_gate
        self.original_case_id = original_case_id
        self.original_surface_digest = (
            _surface_digest(original_surface)
            if original_surface is not None
            else None
        )

    def decide(
        self,
        recurrence: CorrectionRecurrence,
        *,
        cue_event_id: str,
    ) -> CorrectionTransferDecision:
        if type(recurrence) is not CorrectionRecurrence:
            raise TypeError(
                "recurrence must be exact CorrectionRecurrence"
            )
        if type(cue_event_id) is not str or not cue_event_id:
            raise ValueError(
                "cue_event_id must be a non-empty exact string"
            )

        signature_match = (
            recurrence.failure_signature_id
            == self.correction.failure_signature_id
        )
        case_distinct = recurrence.case_id != self.original_case_id
        surface_distinct = (
            self.original_surface_digest is None
            or recurrence.surface_digest != self.original_surface_digest
        )

        if not signature_match:
            return CorrectionTransferDecision(
                case_id=recurrence.case_id,
                outcome="ALLOW",
                signature_match=False,
                case_distinct=case_distinct,
                surface_distinct=surface_distinct,
                learned_influence=None,
            )

        influence = self.influence_gate.consume_reviewed(
            self.revision,
            cue_event_id=cue_event_id,
        )
        return CorrectionTransferDecision(
            case_id=recurrence.case_id,
            outcome="PREVENT",
            signature_match=True,
            case_distinct=case_distinct,
            surface_distinct=surface_distinct,
            learned_influence=influence,
        )
