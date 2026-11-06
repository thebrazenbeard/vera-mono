"""Bounded user-utterance evidence for donor proposals, not authorization.

All claims here are exact surface cues. No sentiment, probability, emotion,
memory admission, identity, source autonomy, or permission is inferred.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
import unicodedata

from vera_core.interaction_semantics import interpret_utterance


_ACTION = re.compile(
    r"^(?:please\s+)?(?P<verb>diagnose|write|draft|inspect|explain|list|show|analy[sz]e)\s+(?P<object>\S.*)$",
    re.I,
)
_CORRECTION = re.compile(r"^(?:no\s*[,.:!]\s*|actually\s*[,.:]?\s+|i\s+meant\s+|correction\s*:\s*)", re.I)
_PROHIBITED_LOOKUP = re.compile(
    r"\b(?:do\s+not|don't|dont|never|avoid|stop)\s+(?:\w+\s+){0,2}?(?:search|look\s+up|lookup|retrieve|fetch|browse)\b"
    r"|\bnot\s+to\s+(?:search|look\s+up|lookup|retrieve|fetch|browse)\b",
    re.I,
)
_STOP_PLAY = re.compile(r"^\s*(?:STOP_PLAY|stop\s+play(?:ing)?)\s*(?::\s*(?P<subject>.+))?$", re.I)
_DOUBLE_NEGATION = re.compile(r"\b(?:do\s+not|don't|dont|never|not)\s+not\s+", re.I)
_QUOTES = {'"': '"', '“': '”', '`': '`'}


@dataclass(frozen=True, slots=True)
class UtteranceEvidence:
    schema: str
    utterance_sha256: str
    parser_speech_act: str
    observed_speech_act: str
    action_lexeme: str | None
    literal_task_object: str | None
    correction_of: str | None
    lookup_prohibition: str
    stop_play: str
    same_referent_stop: bool
    provenance: str
    ambiguity: str | None
    authorization_effect: str = "NONE"
    memory_admission: str = "NONE"
    private_lookup_permission: str = "NONE"
    noema_discrepancy: None = None
    volition_intent: None = None
    humility_priors: None = None
    affect_valence: None = None

    def as_donor_evidence(self) -> dict[str, object]:
        """Typed host-side context; not five-donor callback scores."""
        return asdict(self)

    def as_five_donor_input(self) -> dict[str, object]:
        """Admissible observation for a future donor host, never scored values.

        Mono's existing five-donor callback contract requires a numeric Noema
        discrepancy. It must NOT be invoked with a made-up replacement.
        """
        return {
            "schema": "VERA_FIVE_DONOR_UNSCORED_INPUT_V1",
            "utterance_sha256": self.utterance_sha256,
            "observed_speech_act": self.observed_speech_act,
            "lexical_action": self.action_lexeme,
            "literal_task_object": self.literal_task_object,
            "claimed_correction_of": self.correction_of,
            "lookup_prohibition": self.lookup_prohibition,
            "host_stop_play_same_referent": self.same_referent_stop,
            "ambiguity": self.ambiguity,
            "noema": {"discrepancy": None},
            "meso-crct": {"intent": None},
            "volition": {"candidate_eligible": None},
            "empathy": {"response_policy": None},
            "pre-active": {"focus": None},
            "existing_five_donor_invocation_permitted": False,
            "reason": "GROUNDED_DONOR_SCORES_NOT_AVAILABLE",
            "authorization_effect": "NONE",
        }


def _outside_quotes(text: str) -> tuple[str, bool]:
    """Mask quoted words, including curly quotes; flag unbalanced quotes."""
    masked = list(text)
    closing: str | None = None
    for i, char in enumerate(text):
        if closing is not None:
            masked[i] = " "
            if char == closing:
                closing = None
        elif char in _QUOTES:
            closing = _QUOTES[char]
            masked[i] = " "
    return "".join(masked), closing is not None


def _safe_normalize(text: str) -> str:
    if type(text) is not str or not text.strip() or len(text) > 4096:
        raise ValueError("utterance must be a nonempty string of at most 4096 characters")
    # Surrogates, zero-width modifiers and control-character hiding are unsafe.
    if any(unicodedata.category(c) in {"Cs", "Cf", "Cc"} and c not in "\t\n\r" for c in text):
        raise ValueError("untrusted control, format or surrogate character")
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _task_from_exact_command(text: str) -> tuple[str | None, str | None]:
    match = _ACTION.fullmatch(text.strip())
    if not match:
        return None, None
    return match.group("verb").lower(), match.group("object").strip()


def observe_utterance(
    raw_text: str,
    *,
    prior_interaction_id: str | None = None,
    prior_task_object: str | None = None,
) -> UtteranceEvidence:
    """Observe only explicit discourse cues. Does not execute a task.

    Ambiguous or quoted input cannot create action/lookup permission. A
    supplied previous task is a caller claim, not an authenticated memory.
    """
    normalized = _safe_normalize(raw_text)
    parser = interpret_utterance(raw_text, previous_interaction_id=prior_interaction_id)
    exterior, unbalanced = _outside_quotes(normalized)
    direct = exterior.strip()
    ambiguity = "UNBALANCED_QUOTE" if unbalanced else None
    prohibition = "EXPLICIT" if _PROHIBITED_LOOKUP.search(direct) else "UNKNOWN"
    if _DOUBLE_NEGATION.search(direct):
        ambiguity = ambiguity or "AMBIGUOUS_NEGATION"
        prohibition = "UNKNOWN"
    stop = _STOP_PLAY.fullmatch(direct) if ambiguity is None else None
    correction = _CORRECTION.match(direct)
    body = direct[correction.end():].strip() if correction else direct
    action, task_object = _task_from_exact_command(body)
    if not action and direct and re.match(r"^(?:please\s+)?(?:diagnose|write|draft|inspect|explain|list|show|analy[sz]e)\b", direct, re.I):
        ambiguity = ambiguity or "INCOMPLETE_OR_QUOTED_COMMAND"
    if stop:
        action, task_object = _task_from_exact_command(stop.group("subject") or "")
        if stop.group("subject") and not action:
            ambiguity = ambiguity or "UNBOUND_STOP_SUBJECT"
    if correction and not prior_interaction_id:
        ambiguity = ambiguity or "CORRECTION_WITHOUT_ANTECEDENT"
    if unbalanced:
        action, task_object, stop = None, None, None
    match_previous = bool(
        stop and prior_task_object and task_object
        and task_object.casefold() == _safe_normalize(prior_task_object).casefold()
    )
    speech_act = (
        "STOP_PLAY" if stop else "CORRECTION" if correction else "REQUEST" if action
        else "QUESTION" if direct.endswith("?") else "UNKNOWN"
    )
    return UtteranceEvidence(
        schema="VERA_UTTERANCE_SURFACE_EVIDENCE_V1",
        utterance_sha256=hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        parser_speech_act=parser.speech_act.value,
        observed_speech_act=speech_act,
        action_lexeme=action,
        literal_task_object=task_object,
        correction_of=prior_interaction_id if correction else None,
        lookup_prohibition=prohibition,
        stop_play="EXPLICIT" if stop else "UNKNOWN",
        same_referent_stop=match_previous,
        provenance="EXACT_SURFACE_CUE_ONLY",
        ambiguity=ambiguity,
    )
