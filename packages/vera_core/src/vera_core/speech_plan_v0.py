"""A bounded semantic text-to-speech plan with an optional SAPI V0 adapter.

The plan is data. It neither interprets a model's text as instructions nor
confers voice identity, emotion, user contact, notification or runtime rights.
Its semantic intent is metadata, not a measurement of inner experience.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Callable
import unicodedata

from .voice_output_v1 import SpeechRequest, SpeechWave, render_sapi_wave


_INTENTS = frozenset({"inform", "question", "reflect"})
_STYLES = frozenset({"neutral", "warm", "dry", "deliberate"})


@dataclass(frozen=True, slots=True)
class SpeechPlanV0:
    """Model text and host-selected rendering hints; no effect authorization.

    The base Windows SAPI backend presently supports only neutral delivery.
    Other style tags are reserved for an independently qualified TTS adapter,
    and fail before synthesis on the V0 SAPI path.
    """

    text: str
    voice_name: str
    locale: str = "en-US"
    semantic_intent: str = "inform"
    delivery_style: str = "neutral"

    def __post_init__(self) -> None:
        SpeechRequest(self.text, self.voice_name)
        categories = [unicodedata.category(character) for character in self.text]
        # Reject bidi overrides, zero-width format controls, Unicode line
        # separators and lone surrogates before an audio/display boundary.
        if any(category in {"Cc", "Cf", "Cs", "Zl", "Zp"} for category in categories):
            raise ValueError("speech text must not contain formatting controls")
        if not any(category[0] in "LNPS" for category in categories):
            raise ValueError("speech text needs at least one visible character")
        if type(self.locale) is not str or self.locale != "en-US":
            raise ValueError("SAPI V0 admits only en-US locale")
        if type(self.semantic_intent) is not str or self.semantic_intent not in _INTENTS:
            raise ValueError("unsupported semantic intent")
        if type(self.delivery_style) is not str or self.delivery_style not in _STYLES:
            raise ValueError("unsupported delivery style")


@dataclass(frozen=True, slots=True)
class SpeechPlanResult:
    """A WAV receipt, not proof of intelligible speech or phone delivery."""

    wave: SpeechWave
    submitted_text: str
    semantic_intent: str
    prosody_control_applied: bool = False
    effect_scope: str = "LOCAL_SUBPROCESS_TO_IN_MEMORY_AUDIO_ONLY"


def plan_from_model_text(
    model_text: str,
    *,
    voice_name: str,
    semantic_intent: str = "inform",
    delivery_style: str = "neutral",
) -> SpeechPlanV0:
    """Use model output solely as speech data, never as voice/effect authority.

    Only the host caller selects the platform voice and intent/style annotations.
    No embedded JSON, markup or imperative in model_text is executed or parsed.
    """
    return SpeechPlanV0(
        text=model_text, voice_name=voice_name,
        semantic_intent=semantic_intent, delivery_style=delivery_style,
    )


def render_speech_plan_v0(
    plan: SpeechPlanV0,
    *,
    allow_local_synthesis: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
    timeout_s: float = 45.0,
) -> SpeechPlanResult:
    """Render a neutral speech plan via the existing strict Android WAV V0.

    This is a base-engine adapter and applies **no** prosody control.
    An injected runner supplies synthetic evidence only. Neither path plays or
    sends the resulting bytes to a phone or another person.
    """
    if type(plan) is not SpeechPlanV0:
        raise TypeError("exact SpeechPlanV0 required")
    plan.__post_init__()  # Defensive revalidation of forged frozen instances.
    if allow_local_synthesis is not True:
        raise PermissionError("local synthesis is default-denied")
    if plan.delivery_style != "neutral":
        raise NotImplementedError("prosody style needs a qualified TTS backend")
    wave = render_sapi_wave(
        SpeechRequest(plan.text, plan.voice_name),
        allow_local_synthesis=True,
        require_voice_wav_v0=True,
        runner=runner,
        timeout_s=timeout_s,
    )
    return SpeechPlanResult(
        wave=wave, submitted_text=plan.text, semantic_intent=plan.semantic_intent,
    )
