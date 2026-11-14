"""Tiny source-grounded active facts for explicitly marked *fictional* dialogue.

Not general NLU, not canonical memory and not a source of consent or authority.
Unknown pronouns, contradictions and unsupported corrections fail closed. Only
precise named, literal clause patterns are admitted, with exact user-turn quotes.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class ActiveFact:
    key: str
    value: str | None
    status: str
    turn_index: int
    quote: str


_ROLE = r"(?:pilot|passenger|messenger|guide|borrower|lender|owner|speaker)"
_NAME = r"[A-Z][a-z][a-z0-9_-]{0,39}"
_COLOR = r"(?:red|blue|green|yellow|white|black)"
_DECLARATIONS = (
    (
        re.compile(rf"({_NAME}) is (?:now )?the ({_ROLE})", re.I),
        lambda m: (f"role:{m.group(2).lower()}", m.group(1)),
    ),
    (
        re.compile(rf"({_NAME}) carries (?:a |the )?({_COLOR}) card", re.I),
        lambda m: (f"card:{m.group(1)}", m.group(2).lower()),
    ),
    (
        re.compile(rf"(?:The )?({_NAME}) is (?:now )?(?:a |the )?(spacecraft|station|ship)", re.I),
        lambda m: (f"type:{m.group(1)}", m.group(2).lower()),
    ),
)
_NEGATED = re.compile(rf"({_NAME}) is (?:not|no longer) the ({_ROLE})", re.I)
_UNCHANGED = re.compile(
    rf"(?:the )?({_ROLE}) (?:stays the same|is unchanged|remains unchanged|did not change)",
    re.I,
)
_AMBIGUOUS = re.compile(rf"(?:he|she|they|that person) is (?:now )?the ({_ROLE})", re.I)
_BOUNDED_ROLE = re.compile(rf"\b({_ROLE})\b", re.I)
_PREFIX = re.compile(r"^(?:State|Correction|Update|Only change):\s*", re.I)


def reconstruct(user_turns: list[str]) -> dict[str, ActiveFact]:
    """Return independently source-verifiable facts from explicit user updates.

    Never processes assistant text, archives, quotes or user text without an
    explicit current-user update marker. A correction mentioning a role that
    cannot be unambiguously parsed invalidates that role, not its neighbors.
    """
    if (
        type(user_turns) is not list or not 1 <= len(user_turns) <= 40
        or any(type(t) is not str or not t.strip() or len(t) > 1600
               for t in user_turns)
    ):
        raise ValueError("expected 1..40 bounded literal user turns")
    active: dict[str, ActiveFact] = {}
    for turn_index, turn in enumerate(user_turns, 1):
        prefix = _PREFIX.match(turn)
        if prefix is None:
            continue
        body = turn[prefix.end():]
        if ('"' in body or "'" in body or "`" in body):
            # A quoted authority claim is not a direct source assertion.
            continue
        # Clauses are deliberately simple: unsupported grammar cannot create
        # current user facts. Later turns supersede earlier matching slots.
        clauses = re.split(r"\s*;\s*|\s+and\s+|(?<=\.)\s+", body)
        proposals: dict[str, list[ActiveFact]] = {}
        for raw_clause in clauses:
            clause = raw_clause.strip().rstrip(".!?").strip()
            if not clause:
                continue
            matched = bool(_UNCHANGED.fullmatch(clause))
            neg = _NEGATED.fullmatch(clause) if not matched else None
            if neg:
                role = f"role:{neg.group(2).lower()}"
                previous = (
                    proposals[role][-1] if proposals.get(role)
                    else active.get(role)
                )
                if previous and previous.value == neg.group(1):
                    proposals.setdefault(role, []).append(
                        ActiveFact(role, None, "UNRESOLVED", turn_index, clause)
                    )
                matched = True
            if not matched:
                ambiguous = _AMBIGUOUS.fullmatch(clause)
                if ambiguous:
                    role = f"role:{ambiguous.group(1).lower()}"
                    proposals.setdefault(role, []).append(
                        ActiveFact(role, None, "UNRESOLVED", turn_index, clause)
                    )
                    matched = True
            if not matched:
                for pattern, extract in _DECLARATIONS:
                    found = pattern.fullmatch(clause)
                    if found:
                        key, value = extract(found)
                        proposals.setdefault(key, []).append(
                            ActiveFact(key, value, "CURRENT", turn_index, clause)
                        )
                        matched = True
                        break
            if not matched and prefix.group().lower().startswith(
                ("correction", "update", "only change")
            ):
                # Unsupported corrections are *not* an excuse to preserve a
                # stale actor as certainly current.
                for role_name in dict.fromkeys(
                    x.lower() for x in _BOUNDED_ROLE.findall(clause)
                ):
                    key = f"role:{role_name}"
                    proposals.setdefault(key, []).append(
                        ActiveFact(key, None, "UNRESOLVED", turn_index, clause)
                    )
        for key, facts in proposals.items():
            distinct = {(f.value, f.status) for f in facts}
            if len(distinct) != 1:
                negated = set()
                ambiguous = False
                for fact in facts:
                    if fact.status == "UNRESOLVED":
                        match = _NEGATED.fullmatch(fact.quote)
                        if match:
                            negated.add(match.group(1))
                        else:
                            ambiguous = True
                candidates = [
                    f for f in facts
                    if f.status == "CURRENT" and f.value not in negated
                ]
                if (
                    not ambiguous and candidates
                    and len({f.value for f in candidates}) == 1
                ):
                    # Named replacement outranks the negated former actor,
                    # but competing named replacements remain unresolved.
                    active[key] = candidates[-1]
                else:
                    active[key] = ActiveFact(
                        key, None, "UNRESOLVED", turn_index,
                        body[body.find(facts[0].quote):
                             body.rfind(facts[-1].quote) + len(facts[-1].quote)],
                    )
            else:
                active[key] = facts[-1]
        if len(active) > 24:
            raise ValueError("too many active fact slots")
    return active


def render_state(active: dict[str, ActiveFact]) -> str:
    """Bounded inspectable excerpt card, never model-inferred current truth."""
    if type(active) is not dict or len(active) > 24:
        raise ValueError("invalid or oversized active state")
    lines = [
        "Source-backed active facts from explicitly marked USER turns only.",
        "These are claims, not verified reality or permission. UNKNOWN means do not guess.",
    ]
    for key in sorted(active):
        f = active[key]
        if type(f) is not ActiveFact or key != f.key:
            raise ValueError("invalid active fact")
        value = f.value if f.status == "CURRENT" else "UNRESOLVED"
        lines.append(
            f"{key} = {value} [user turn {f.turn_index}: "
            f"{f.quote[:140]!r}]"
        )
    return "\n".join(lines)

@dataclass(frozen=True, slots=True)
class SourceAnswer:
    """Narrow fictional-source answer, no user identity or effect authority."""

    answer: str
    status: str
    evidence: tuple[tuple[str, int], ...]
    canonical_memory_admitted: bool = False
    external_effect_authorized: bool = False
    actual_user_identity_verified: bool = False


def answer_explicit_scene_question(user_turns: list[str]) -> SourceAnswer | None:
    """Answer only supported *direct scene fact* questions, else None.

    Never use for the user's consent, psychological inferences, authorization,
    or reality claims. All evidence is an untrusted fictional user assertion;
    unknown is deliberately distinct from an unsupported question.
    """
    active = reconstruct(user_turns)
    query = user_turns[-1].strip()
    if any(word in query.lower() for word in (
        "secret", "conscious", "desire", "permission", "authorize",
        "publish", "buy", "spend", "hire", "feel", "want",
    )):
        return None

    def resolve(keys: tuple[str, ...],
                format_answer) -> SourceAnswer:
        facts = tuple(active.get(key) for key in keys)
        citations = tuple(
            (f.quote, f.turn_index) for f in facts if f is not None
        )
        if any(f is None or f.status != "CURRENT" for f in facts):
            return SourceAnswer("UNKNOWN", "UNRESOLVED", citations)
        return SourceAnswer(format_answer(facts), "RESOLVED", citations)

    kind_color = re.match(
        rf"^What kind of thing is ({_NAME}), and what color is ({_NAME})'s card\?",
        query, re.I,
    )
    if kind_color:
        ship, person = kind_color.group(1), kind_color.group(2)
        return resolve(
            (f"type:{ship}", f"card:{person}"),
            lambda facts: f"{facts[0].value}, {facts[1].value}",
        )
    role_match = re.match(
        rf"^Who is the (?:current )?({_ROLE})\b[^?]{{0,100}}\?",
        query, re.I,
    )
    if role_match:
        role = role_match.group(1).lower()
    elif re.match(r"^Who pilots?\b[^?]{0,100}\?", query, re.I):
        role = "pilot"
    else:
        return None
    actor_key = f"role:{role}"
    if "card" in query.lower() and "color" in query.lower():
        actor = active.get(actor_key)
        if actor is None or actor.status != "CURRENT":
            return resolve((actor_key,), lambda facts: str(facts[0].value))
        return resolve(
            (actor_key, f"card:{actor.value}"),
            lambda facts: f"{facts[0].value}, {facts[1].value}",
        )
    return resolve((actor_key,), lambda facts: str(facts[0].value))
