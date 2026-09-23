from __future__ import annotations

import re

from .model import TargetSpec


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).casefold()


def target_forms(target: TargetSpec) -> tuple[str, ...]:
    forms = list(target.literal_forms or (target.query_original,))
    forms.extend(target.normalized_forms)
    forms.extend(target.aliases)
    seen: dict[str, str] = {}
    for form in forms:
        n = normalize_text(form)
        if n and n not in seen:
            seen[n] = form
    return tuple(seen.values())


def literal_match(text: str, target: TargetSpec) -> str | None:
    for form in target.literal_forms or (target.query_original,):
        if form in text:
            return "EXACT"
    normalized = normalize_text(text)
    for form in target_forms(target):
        if normalize_text(form) in normalized:
            return "NORMALIZED"
    return None
