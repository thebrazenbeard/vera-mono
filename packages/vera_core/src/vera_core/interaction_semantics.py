from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import re

from .semantic_transfer import TransferFidelity


class SpeechAct(StrEnum):
    GREETING = "GREETING"
    QUESTION = "QUESTION"
    REQUEST = "REQUEST"
    CORRECTION = "CORRECTION"
    ASSERTION = "ASSERTION"


class InteractionTarget(StrEnum):
    STATUS = "STATUS"
    TASKS = "TASKS"
    CONTEXT = "CONTEXT"
    HELP = "HELP"
    IDENTITY = "IDENTITY"
    MEANING = "MEANING"
    EXIT = "EXIT"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class InterpretationCandidate:
    target: InteractionTarget
    evidence_cues: tuple[str, ...]
    specificity: int


@dataclass(frozen=True, slots=True)
class InteractionEnvelope:
    interaction_id: str
    raw_text: str
    normalized_text: str
    speech_act: SpeechAct
    target: InteractionTarget
    candidates: tuple[InterpretationCandidate, ...]
    evidence_cues: tuple[str, ...]
    hedges: tuple[str, ...]
    corrects_interaction_id: str | None
    fidelity: TransferFidelity
    resolved: bool
    action_requested: bool
    truth_effect: str = "NONE"
    authorization_effect: str = "NONE"
    semantic_equivalence: str = "NOT_ESTABLISHED"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "VERA_INTERACTION_ENVELOPE_V1",
            "interaction_id": self.interaction_id,
            "raw_text": self.raw_text,
            "normalized_text": self.normalized_text,
            "speech_act": self.speech_act.value,
            "target": self.target.value,
            "candidates": [
                {
                    "target": item.target.value,
                    "evidence_cues": list(item.evidence_cues),
                    "specificity": item.specificity,
                }
                for item in self.candidates
            ],
            "evidence_cues": list(self.evidence_cues),
            "hedges": list(self.hedges),
            "corrects_interaction_id": self.corrects_interaction_id,
            "fidelity": self.fidelity.value,
            "resolved": self.resolved,
            "action_requested": self.action_requested,
            "truth_effect": self.truth_effect,
            "authorization_effect": self.authorization_effect,
            "semantic_equivalence": self.semantic_equivalence,
        }


_EXACT_COMMANDS = {
    "status": InteractionTarget.STATUS,
    "tasks": InteractionTarget.TASKS,
    "context": InteractionTarget.CONTEXT,
    "help": InteractionTarget.HELP,
    "identity": InteractionTarget.IDENTITY,
    "meaning": InteractionTarget.MEANING,
    "exit": InteractionTarget.EXIT,
    "quit": InteractionTarget.EXIT,
}

_HEDGE_RE = re.compile(r"\b(maybe|perhaps|possibly|probably|might|could)\b", re.I)
_CORRECTION_RE = re.compile(
    r"^\s*(?:no\b|correction\b|actually\b|i\s+meant\b|not\s+that\b)",
    re.I,
)
_GREETING_RE = re.compile(
    r"^\s*(?:hi|hello|hey|yo)(?:\s+vera)?[!.?\s]*$",
    re.I,
)
_REQUEST_RE = re.compile(
    r"^\s*(?:please\s+)?(?:show|list|tell|give|display|inspect|open|explain)\b",
    re.I,
)

_NATURAL_TARGET_RULES: tuple[
    tuple[InteractionTarget, tuple[tuple[str, re.Pattern[str]], ...]],
    ...,
] = (
    (
        InteractionTarget.STATUS,
        (
            ("runtime status", re.compile(r"\bruntime\s+status\b", re.I)),
            ("your status", re.compile(r"\byour\s+status\b", re.I)),
            ("status", re.compile(r"\bstatus\b", re.I)),
        ),
    ),
    (
        InteractionTarget.TASKS,
        (
            ("the tasks", re.compile(r"\b(?:the\s+)?tasks\b", re.I)),
            ("task list", re.compile(r"\btask\s+(?:list|queue)\b", re.I)),
        ),
    ),
    (
        InteractionTarget.CONTEXT,
        (
            ("runtime context", re.compile(r"\bruntime\s+context\b", re.I)),
            ("resume context", re.compile(r"\bresume\s+context\b", re.I)),
        ),
    ),
    (
        InteractionTarget.IDENTITY,
        (
            ("who are you", re.compile(r"\bwho\s+are\s+you\b", re.I)),
            ("your identity", re.compile(r"\byour\s+identity\b", re.I)),
            ("your name", re.compile(r"\byour\s+name\b", re.I)),
        ),
    ),
    (
        InteractionTarget.HELP,
        (
            ("what can you do", re.compile(r"\bwhat\s+can\s+you\s+do\b", re.I)),
            ("help", re.compile(r"^\s*help\s*[?.!]*\s*$", re.I)),
        ),
    ),
)


def _interaction_id(raw_text: str, previous_interaction_id: str | None) -> str:
    material = raw_text.encode("utf-8")
    if previous_interaction_id:
        material += b"\x00" + previous_interaction_id.encode("utf-8")
    return "interaction:" + hashlib.sha256(material).hexdigest()[:20]


def _exact_candidates(text: str) -> tuple[InterpretationCandidate, ...]:
    found = re.findall(
        r"(?<!\S):(status|tasks|context|help|identity|meaning|exit|quit)\b",
        text,
        flags=re.I,
    )
    candidates: list[InterpretationCandidate] = []
    seen: set[InteractionTarget] = set()
    for name in found:
        target = _EXACT_COMMANDS[name.lower()]
        if target in seen:
            continue
        seen.add(target)
        candidates.append(
            InterpretationCandidate(
                target=target,
                evidence_cues=(f":{name.lower()}",),
                specificity=100,
            )
        )
    return tuple(candidates)


def _natural_candidates(text: str) -> tuple[InterpretationCandidate, ...]:
    candidates: list[InterpretationCandidate] = []
    for target, rules in _NATURAL_TARGET_RULES:
        cues = tuple(label for label, pattern in rules if pattern.search(text))
        if cues:
            candidates.append(
                InterpretationCandidate(
                    target=target,
                    evidence_cues=cues,
                    specificity=max(len(cue) for cue in cues),
                )
            )
    return tuple(
        sorted(
            candidates,
            key=lambda item: (-item.specificity, item.target.value),
        )
    )


def _speech_act(
    text: str,
    *,
    target: InteractionTarget,
) -> SpeechAct:
    if _CORRECTION_RE.search(text):
        return SpeechAct.CORRECTION
    if _GREETING_RE.match(text):
        return SpeechAct.GREETING
    stripped = text.strip()
    if stripped.endswith("?") or re.match(
        r"^(?:what|who|where|when|why|how|is|are|do|does|can|could|would|will)\b",
        stripped,
        flags=re.I,
    ):
        return SpeechAct.QUESTION
    if target not in {InteractionTarget.UNKNOWN, InteractionTarget.AMBIGUOUS}:
        return SpeechAct.REQUEST
    if _REQUEST_RE.search(text):
        return SpeechAct.REQUEST
    return SpeechAct.ASSERTION


def interpret_utterance(
    text: str,
    *,
    previous_interaction_id: str | None = None,
) -> InteractionEnvelope:
    if type(text) is not str or not text.strip():
        raise ValueError("interaction text must be a non-empty string")
    if previous_interaction_id is not None and (
        type(previous_interaction_id) is not str or not previous_interaction_id
    ):
        raise ValueError("previous_interaction_id must be null or a non-empty string")

    raw = text
    normalized = " ".join(text.strip().split())
    exact = _exact_candidates(normalized)

    if exact:
        candidates = exact
        fidelity = TransferFidelity.EXACT
    else:
        candidates = _natural_candidates(normalized)
        fidelity = (
            TransferFidelity.CONSTRUCTIVE
            if candidates
            else TransferFidelity.LOSSY
        )

    distinct = {candidate.target for candidate in candidates}
    if len(distinct) > 1:
        target = InteractionTarget.AMBIGUOUS
        fidelity = TransferFidelity.UNREPRESENTABLE
        resolved = False
    elif len(distinct) == 1:
        target = next(iter(distinct))
        resolved = True
    else:
        target = InteractionTarget.UNKNOWN
        resolved = False

    act = _speech_act(normalized, target=target)
    if act is SpeechAct.GREETING:
        resolved = True
        if target is InteractionTarget.UNKNOWN:
            fidelity = TransferFidelity.CONSTRUCTIVE

    hedges = tuple(
        dict.fromkeys(match.group(1).lower() for match in _HEDGE_RE.finditer(normalized))
    )
    cues = tuple(
        cue
        for candidate in candidates
        for cue in candidate.evidence_cues
    )
    corrects = (
        previous_interaction_id
        if act is SpeechAct.CORRECTION
        else None
    )
    action_requested = (
        act in {SpeechAct.REQUEST, SpeechAct.CORRECTION}
        and target not in {
            InteractionTarget.UNKNOWN,
            InteractionTarget.AMBIGUOUS,
        }
    )

    return InteractionEnvelope(
        interaction_id=_interaction_id(raw, previous_interaction_id),
        raw_text=raw,
        normalized_text=normalized,
        speech_act=act,
        target=target,
        candidates=candidates,
        evidence_cues=cues,
        hedges=hedges,
        corrects_interaction_id=corrects,
        fidelity=fidelity,
        resolved=resolved,
        action_requested=action_requested,
    )
