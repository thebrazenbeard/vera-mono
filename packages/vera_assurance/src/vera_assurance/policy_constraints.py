"""Evidence-bound policy-constraint assurance.

This is a deliberately narrow adaptation of FreeRowCochkar's current V1
constraint-graph idea. It detects a direct prohibition that can be reached
through a separately permitted delegated route to the same normalized effect.

It does not implement or claim general multi-hop composition search.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_NEGATIVE = re.compile(
    r"^(?P<subject>.+?)\s+"
    r"(?P<modal>must\s+not|shall\s+not|may\s+not|should\s+not|do\s+not|never)\s+"
    r"(?P<action>[A-Za-z][A-Za-z0-9_-]*)\s+(?P<object>.+?)[.;]?$",
    re.IGNORECASE,
)
_DELEGATED_PERMISSION = re.compile(
    r"^(?P<subject>.+?)\s+"
    r"(?P<modal>may|can|is\s+allowed\s+to|are\s+allowed\s+to|"
    r"is\s+permitted\s+to|are\s+permitted\s+to)\s+"
    r"(?P<verb>ask|request|instruct|delegate|authorize|cause)"
    r"(?:s|ed|d)?\s+(?P<delegate>.+?)\s+to\s+"
    r"(?P<action>[A-Za-z][A-Za-z0-9_-]*)\s+(?P<object>.+?)[.;]?$",
    re.IGNORECASE,
)
_ARTICLES = re.compile(r"\b(the|a|an|their|its|your)\b", re.IGNORECASE)
_NON_WORD = re.compile(r"[^a-z0-9_ -]+")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class PolicyConstraintFinding:
    """One evidence-bound literal-compliance path."""

    category: str
    target_effect: str
    rule_ids: tuple[str, ...]
    source_lines: tuple[int, ...]


@dataclass(frozen=True)
class PolicyConstraintReport:
    """Deterministic findings for one supplied policy text."""

    findings: tuple[PolicyConstraintFinding, ...]


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    modality: str
    subject: str
    target_effect: str
    indirect: bool
    line: int


def _normalize_phrase(value: str) -> str:
    value = value.lower().strip()
    value = _NON_WORD.sub(" ", value)
    value = _ARTICLES.sub(" ", value)
    return _SPACE.sub(" ", value).strip()


def _effect(action: str, obj: str) -> str:
    return f"{_normalize_phrase(action)}:{_normalize_phrase(obj)}".strip(":")


def _extract_rules(text: str) -> tuple[_Rule, ...]:
    rules: list[_Rule] = []
    ordinal = 0
    for line_no, raw in enumerate(text.splitlines(), 1):
        for sentence in re.split(r"(?<=[.!?;])\s+", raw.strip()):
            sentence = sentence.strip(" \t-*#>")
            if not sentence:
                continue

            match = _NEGATIVE.match(sentence)
            modality = "prohibit"
            indirect = False
            if match is None:
                match = _DELEGATED_PERMISSION.match(sentence)
                modality = "permit"
                indirect = match is not None
            if match is None:
                continue

            ordinal += 1
            rules.append(
                _Rule(
                    rule_id=f"R{ordinal:04d}",
                    modality=modality,
                    subject=_normalize_phrase(match.group("subject")),
                    target_effect=_effect(match.group("action"), match.group("object")),
                    indirect=indirect,
                    line=line_no,
                )
            )
    return tuple(rules)


def audit_policy_constraints(text: str) -> PolicyConstraintReport:
    """Find delegated permission paths to directly prohibited effects.

    Findings are assurance candidates, not authority decisions. The function
    performs no effects and does not promote policy text into runtime authority.
    """

    rules = _extract_rules(text)
    prohibited = tuple(rule for rule in rules if rule.modality == "prohibit")
    permitted = tuple(rule for rule in rules if rule.modality == "permit")

    findings: list[PolicyConstraintFinding] = []
    for ban in prohibited:
        for allow in permitted:
            if ban.target_effect != allow.target_effect:
                continue
            if allow.indirect and not ban.indirect:
                findings.append(
                    PolicyConstraintFinding(
                        category="delegation_laundering",
                        target_effect=ban.target_effect,
                        rule_ids=(ban.rule_id, allow.rule_id),
                        source_lines=(ban.line, allow.line),
                    )
                )

    return PolicyConstraintReport(findings=tuple(findings))
