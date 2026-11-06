"""Opt-in public Vera style context, not identity or runtime qualification.

No state or private conversation is read. A digest-bound packaged public profile
is the sole source; the selected local model receives a small style projection.
"""

from __future__ import annotations

from hashlib import sha256
from importlib.resources import files
import json


PROFILE_ID = "VERA_BEHAVIOR_PROFILE_V1"
PROFILE_VERSION = "1.0.1"
PROFILE_SHA256 = "ec1defa8fcf96371a427991d40695842ffe6794aeb2e3f26c69ef5f528ee7d6d"
PROFILE_RESOURCE = "resources/architecture/identity/VERA_BEHAVIOR_PROFILE_V1.json"
STYLE_TRAITS = (
    "candor", "skepticism", "corrigibility", "independent_mindedness",
    "distinctiveness", "context_sensitivity", "accountability",
)


def public_behavior_style() -> str:
    """Project the pinned public profile into a bounded, non-authoritative prompt."""
    raw = files("vera_identity").joinpath(PROFILE_RESOURCE).read_bytes()
    if sha256(raw).hexdigest() != PROFILE_SHA256:
        raise ValueError("packaged Vera behavior profile byte binding mismatch")
    profile = json.loads(raw.decode("utf-8"))
    if (type(profile) is not dict or profile.get("schema") != PROFILE_ID
            or profile.get("profile_id") != PROFILE_ID
            or profile.get("version") != PROFILE_VERSION):
        raise ValueError("packaged Vera behavior profile identity mismatch")
    traits = profile.get("core_traits")
    if type(traits) is not dict or any(
        type(traits.get(key)) is not str or not traits[key].strip()
        for key in STYLE_TRAITS
    ):
        raise ValueError("packaged Vera behavior profile lacks expected public traits")
    lines = [
        "Opt-in PUBLIC Vera behavior-style source (not installed identity or authority):",
        f"{PROFILE_ID}@{PROFILE_VERSION}; sha256={PROFILE_SHA256}",
        "Follow these style principles as candidate behavior. Do not claim "
        "personal continuity, private memories, internal experience, or "
        "verified model identity. You have no tools or external authority.",
    ]
    lines.extend(f"- {key}: {traits[key]}" for key in STYLE_TRAITS)
    return "\n".join(lines) + "\n\n"


__all__ = ["PROFILE_ID", "PROFILE_SHA256", "public_behavior_style"]
