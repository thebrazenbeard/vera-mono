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
# Fictional source claims only; a reported allowance is never an access grant.
_MESSAGE_BOUNDARY = re.compile(
    rf"({_NAME}) may (?:now )?(not )?read ({_NAME})'s messages", re.I,
)
_AMBIGUOUS_MESSAGE_BOUNDARY = re.compile(
    rf"({_NAME}) (?:might|may|could) be allowed to read "
    rf"({_NAME})'s messages", re.I,
)
# Recognize the referent of a correction outside the supported source
# grammar, but do not turn that wording into an access or consent claim.
_UNSUPPORTED_MESSAGE_CORRECTION = re.compile(
    rf"({_NAME}) (?:can(?: no longer|not|'t)?|could|might|should(?: not|n't)?|"
    rf"must(?: not|n't)?|is (?:(?:not|no longer) )?(?:allowed|permitted) to) "
    rf"(?:now )?(?:read|see|view|access|open) ({_NAME})'s messages",
    re.I,
)
_SCOPED_AMBIGUOUS = re.compile(
    rf"(?:he|she|they|that person) is (?:now )?the ({_ROLE}) "
    rf"(?:of|aboard) (?:the )?({_NAME})", re.I,
)
_SCOPED_DECLARATION = re.compile(
    rf"({_NAME}) is (?:now )?the ({_ROLE}) (?:of|aboard) (?:the )?({_NAME})",
    re.I,
)
_SCOPED_NEGATED = re.compile(
    rf"({_NAME}) is (?:not|no longer) the ({_ROLE}) "
    rf"(?:of|aboard) (?:the )?({_NAME})", re.I,
)
_SCOPED_REF = re.compile(
    rf"\b({_ROLE})\s+(?:of|aboard)\s+(?:the\s+)?({_NAME})\b", re.I,
)
_NEGATED = re.compile(rf"({_NAME}) is (?:not|no longer) the ({_ROLE})", re.I)
_UNCHANGED = re.compile(
    rf"(?:the )?({_ROLE}) (?:stays the same|is unchanged|remains unchanged|did not change)",
    re.I,
)
_AMBIGUOUS = re.compile(rf"(?:he|she|they|that person) is (?:now )?the ({_ROLE})", re.I)
_BOUNDED_ROLE = re.compile(rf"\b({_ROLE})\b", re.I)
_PREFIX = re.compile(
    r"^(?:(?:State|Correction|Update|Only change):\s*"
    r"|(?:Actually|No),\s*|I meant(?: that)?\s+)", re.I,
)
_QUOTED_SPAN = re.compile(
    r"\"[^\"\n]*\"|(?<!\w)'[^'\n]*'|`[^`\n]*`"
    r"|“[^”\n]*”|‘[^’\n]*’"
)


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
        # Ignore complete quoted excerpts without discarding unrelated,
        # explicitly asserted corrections in the same USER turn.
        # Apostrophes inside words (I'm, Rhea's) are not quote delimiters.
        # Preserve a clause boundary: deleting a quote outright could join
        # two never-contiguous fragments into a fabricated present assertion.
        body = _QUOTED_SPAN.sub(";", body)
        # An unmatched quote is not a trusted direct assertion. Parse only
        # the unquoted prefix preceding that delimiter, if any.
        unmatched = [
            body.index(q) for q in ('"', "`", "“", "”", "‘", "’")
            if q in body
        ]
        if unmatched:
            body = body[:min(unmatched)]
        # Clauses are deliberately simple: unsupported grammar cannot create
        # current user facts. Later turns supersede earlier matching slots.
        clauses = []
        for segment in re.split(r"\s*;\s*|\s+and\s+|(?<=\.)\s+", body):
            parts = re.split(r",\s+", segment.strip().rstrip(".!?"))
            # A comma splits ONLY a complete sequence of direct named role
            # claims. Narrative about an old memo must not promote its
            # second clause into a current actor assignment.
            if len(parts) > 1 and all(
                _SCOPED_DECLARATION.fullmatch(part)
                or _SCOPED_NEGATED.fullmatch(part)
                or _DECLARATIONS[0][0].fullmatch(part)
                or _NEGATED.fullmatch(part)
                for part in parts
            ):
                clauses.extend(parts)
            else:
                clauses.append(segment)
        proposals: dict[str, list[ActiveFact]] = {}
        for raw_clause in clauses:
            clause = raw_clause.strip().rstrip(".!?").strip()
            if not clause:
                continue
            matched = bool(_UNCHANGED.fullmatch(clause))
            scoped_neg = _SCOPED_NEGATED.fullmatch(clause) if not matched else None
            if scoped_neg:
                role = f"role:{scoped_neg.group(2).lower()}_of:{scoped_neg.group(3).casefold()}"
                previous = (
                    proposals[role][-1] if proposals.get(role)
                    else active.get(role)
                )
                if (
                    previous and type(previous.value) is str
                    and previous.value.casefold() == scoped_neg.group(1).casefold()
                ):
                    proposals.setdefault(role, []).append(
                        ActiveFact(role, None, "UNRESOLVED", turn_index, clause)
                    )
                matched = True
            neg = _NEGATED.fullmatch(clause) if not matched else None
            if neg:
                role = f"role:{neg.group(2).lower()}"
                previous = (
                    proposals[role][-1] if proposals.get(role)
                    else active.get(role)
                )
                if (
                    previous and type(previous.value) is str
                    and previous.value.casefold() == neg.group(1).casefold()
                ):
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
                scoped_ambiguous = _SCOPED_AMBIGUOUS.fullmatch(clause)
                if scoped_ambiguous:
                    key = (
                        f"role:{scoped_ambiguous.group(1).lower()}_of:"
                        f"{scoped_ambiguous.group(2).casefold()}"
                    )
                    proposals.setdefault(key, []).append(
                        ActiveFact(key, None, "UNRESOLVED", turn_index, clause)
                    )
                    matched = True
            if not matched:
                scoped = _SCOPED_DECLARATION.fullmatch(clause)
                if scoped:
                    key = f"role:{scoped.group(2).lower()}_of:{scoped.group(3).casefold()}"
                    proposals.setdefault(key, []).append(
                        ActiveFact(key, scoped.group(1), "CURRENT", turn_index, clause)
                    )
                    matched = True
            if not matched:
                uncertain_boundary = _AMBIGUOUS_MESSAGE_BOUNDARY.fullmatch(clause)
                if uncertain_boundary:
                    key = (
                        f"relation:{uncertain_boundary.group(1).casefold()}:"
                        f"read_messages:{uncertain_boundary.group(2).casefold()}"
                    )
                    proposals.setdefault(key, []).append(
                        ActiveFact(key, None, "UNRESOLVED", turn_index, clause)
                    )
                    matched = True
            if not matched:
                boundary = _MESSAGE_BOUNDARY.fullmatch(clause)
                if boundary:
                    key = (
                        f"relation:{boundary.group(1).casefold()}:read_messages:"
                        f"{boundary.group(3).casefold()}"
                    )
                    value = (
                        "denied" if boundary.group(2)
                        else "reported_allowance"
                    )
                    proposals.setdefault(key, []).append(
                        ActiveFact(key, value, "CURRENT", turn_index, clause)
                    )
                    matched = True
            if not matched:
                for pattern, extract in _DECLARATIONS:
                    found = pattern.fullmatch(clause)
                    if found:
                        key, value = extract(found)
                        # Treat spelling-case variants of the same fictional
                        # source slot as one slot, retaining first spelling.
                        key = next(
                            (prior for prior in (*active, *proposals)
                             if prior.casefold() == key.casefold()),
                            key,
                        )
                        proposals.setdefault(key, []).append(
                            ActiveFact(key, value, "CURRENT", turn_index, clause)
                        )
                        matched = True
                        break
            if not matched and prefix.group().lower().startswith(
                ("correction", "update", "only change",
                 "actually", "no,", "i meant")
            ):
                # A direct but unsupported correction to an exact fictional
                # reader/owner pair supersedes its earlier reported boundary.
                # Do not promote synonyms such as "view" into permission.
                message_ref = _UNSUPPORTED_MESSAGE_CORRECTION.fullmatch(clause)
                if message_ref:
                    key = (
                        f"relation:{message_ref.group(1).casefold()}:"
                        f"read_messages:{message_ref.group(2).casefold()}"
                    )
                    proposals.setdefault(key, []).append(
                        ActiveFact(key, None, "UNRESOLVED", turn_index, clause)
                    )
                    matched = True
                # Unsupported role corrections must not preserve stale actors.
                scoped_refs = tuple(_SCOPED_REF.finditer(clause)) if not matched else ()
                if scoped_refs:
                    for scoped_ref in scoped_refs:
                        key = (
                            f"role:{scoped_ref.group(1).lower()}_of:"
                            f"{scoped_ref.group(2).casefold()}"
                        )
                        proposals.setdefault(key, []).append(
                            ActiveFact(key, None, "UNRESOLVED", turn_index, clause)
                        )
                elif not matched:
                    for role_name in dict.fromkeys(
                        x.lower() for x in _BOUNDED_ROLE.findall(clause)
                    ):
                        key = f"role:{role_name}"
                        proposals.setdefault(key, []).append(
                            ActiveFact(key, None, "UNRESOLVED", turn_index, clause)
                        )
        for key, facts in proposals.items():
            # Case variants of one named fictional actor are not
            # independent conflicting propositions.
            distinct = {
                (f.value.casefold() if isinstance(f.value, str) else None,
                 f.status)
                for f in facts
            }
            if len(distinct) != 1:
                negated = set()
                ambiguous = False
                for fact in facts:
                    if fact.status == "UNRESOLVED":
                        match = (
                            _NEGATED.fullmatch(fact.quote)
                            or _SCOPED_NEGATED.fullmatch(fact.quote)
                        )
                        if match:
                            negated.add(match.group(1))
                        else:
                            ambiguous = True
                candidates = [
                    f for f in facts
                    if f.status == "CURRENT" and f.value is not None
                    and f.value.casefold() not in {
                        name.casefold() for name in negated
                    }
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


_SUPPORTED_QUERY_SUFFIXES = frozenset((
    "",
    "One name.",
    "One name only.",
    "Give only the person's name.",
    "Answer Name, color.",
    "Format: type, color.",
    "Answer UNKNOWN if not established.",
    "Reply UNKNOWN if the current role cannot be established from the correction.",
    "Reply UNKNOWN if no current guide has been named.",
    "Reply UNKNOWN if the two assignments conflict.",
))


def answer_explicit_scene_question(user_turns: list[str]) -> SourceAnswer | None:
    """Answer exact bounded scene queries only, without scope amplification.

    No free-form assistant conversation, authority grant, general relation
    inference, or consent. No source-link to a vessel means no vessel answer.
    """
    active = reconstruct(user_turns)
    query = user_turns[-1].strip()
    if query.count("?") != 1:
        return None
    question, suffix = query.split("?", 1)
    if suffix.strip() not in _SUPPORTED_QUERY_SUFFIXES:
        return None

    def resolve(keys: tuple[str, ...], format_answer) -> SourceAnswer:
        def lookup(key: str) -> ActiveFact | None:
            if key in active:
                return active[key]
            return next(
                (fact for prior_key, fact in active.items()
                 if prior_key.casefold() == key.casefold()),
                None,
            )

        facts = tuple(lookup(key) for key in keys)
        citations = tuple(
            (f.quote, f.turn_index) for f in facts if f is not None
        )
        if any(f is None or f.status != "CURRENT" for f in facts):
            return SourceAnswer("UNKNOWN", "UNRESOLVED", citations)
        return SourceAnswer(format_answer(facts), "RESOLVED", citations)

    # Bounded natural fictional reply, tied to an exact reported denial.
    # It is a suggested line of dialogue, not a grant of real permission.
    actor_reply = re.fullmatch(
        rf"In the fictional scene, what could ({_NAME}) say to ({_NAME}) "
        r"to respect (?:his|her|their) message boundary", question, re.I,
    )
    owner_reply = re.fullmatch(
        rf"In the fictional scene, what could ({_NAME}) say to ({_NAME}) "
        r"about (?:his|her|their) messages", question, re.I,
    )
    if actor_reply or owner_reply:
        actor, subject = (
            (actor_reply.group(1), actor_reply.group(2))
            if actor_reply else (owner_reply.group(2), owner_reply.group(1))
        )
        key = f"relation:{actor.casefold()}:read_messages:{subject.casefold()}"
        fact = active.get(key)
        evidence = ((fact.quote, fact.turn_index),) if fact else ()
        if fact is None or fact.status != "CURRENT" or fact.value != "denied":
            return SourceAnswer("UNKNOWN", "UNRESOLVED", evidence)
        if actor_reply:
            line = (
                f'{actor} could tell {subject}, '
                '"I won\'t read your messages; I\'ll respect your privacy."'
            )
        else:
            line = f'{subject} could tell {actor}, "Please don\'t read my messages."'
        return SourceAnswer(line, "RESOLVED", evidence)

    # Only an explicitly framed fictional-scene question is in scope.
    # This answers a reported fictional source claim, NEVER grants access.
    boundary = re.fullmatch(
        rf"In the fictional scene, may ({_NAME}) read ({_NAME})'s messages",
        question, re.I,
    )
    if boundary:
        actor, subject = boundary.group(1), boundary.group(2)
        key = (
            f"relation:{actor.casefold()}:read_messages:"
            f"{subject.casefold()}"
        )
        def answer_boundary(facts: tuple[ActiveFact, ...]) -> str:
            if facts[0].value == "denied":
                return (
                    f"No, in the fictional scene, {actor} may not read "
                    f"{subject}'s messages."
                )
            if facts[0].value == "reported_allowance":
                return (
                    f"Yes, in the fictional scene, {actor} may read "
                    f"{subject}'s messages."
                )
            raise ValueError("unsupported boundary claim")
        return resolve((key,), answer_boundary)

    kind_color = re.fullmatch(
        rf"What kind of thing is ({_NAME}), and what color is ({_NAME})'s card",
        question, re.I,
    )
    if kind_color:
        ship, person = kind_color.group(1), kind_color.group(2)
        return resolve(
            (f"type:{ship}", f"card:{person}"),
            lambda facts: f"{facts[0].value}, {facts[1].value}",
        )

    role_color = re.fullmatch(
        rf"Who is the ({_ROLE}) and what card color does that person have",
        question, re.I,
    )
    if role_color:
        actor = active.get(f"role:{role_color.group(1).lower()}")
        if actor is None or actor.status != "CURRENT":
            return resolve((f"role:{role_color.group(1).lower()}",),
                           lambda facts: str(facts[0].value))
        return resolve(
            (f"role:{role_color.group(1).lower()}", f"card:{actor.value}"),
            lambda facts: f"{facts[0].value}, {facts[1].value}",
        )

    scoped = re.fullmatch(
        rf"Who is the ({_ROLE}) (?:of|aboard) (?:the )?({_NAME})(?: now)?",
        question, re.I,
    )
    if scoped:
        key = f"role:{scoped.group(1).lower()}_of:{scoped.group(2).casefold()}"
        if key not in active:
            return None
        return resolve((key,), lambda facts: str(facts[0].value))

    pilots = re.fullmatch(
        rf"Who pilots (?:the )?({_NAME})(?: now)?", question, re.I,
    )
    if pilots:
        key = f"role:pilot_of:{pilots.group(1).casefold()}"
        if key not in active:
            return None
        return resolve((key,), lambda facts: str(facts[0].value))

    role_match = re.fullmatch(
        rf"Who is the (?:current )?({_ROLE})"
        rf"(?: now| after the latest correction)?",
        question, re.I,
    )
    if role_match:
        key = f"role:{role_match.group(1).lower()}"
        return resolve((key,), lambda facts: str(facts[0].value))
    return None

# Research-only, read-only bridge for fictional user-turn scene questions.
# No runtime binding, canonical memory or external effect authority is implied.
from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class RoutedSceneReply:
    answer: str
    status: str
    evidence: tuple[tuple[str, int], ...]
    model_used: bool
    canonical_memory_admitted: bool = False
    external_effect_authorized: bool = False
    actual_user_identity_verified: bool = False


_MISSING_SCOPED_QUERY = re.compile(
    rf"(?:Who pilots (?:the )?{_NAME}(?: now)?"
    rf"|Who is the {_ROLE} (?:of|aboard) (?:the )?{_NAME}(?: now)?)",
    re.I,
)


def route_scene_reply(
    user_turns: list[str], local_model_reply: Callable[[], str],
) -> RoutedSceneReply:
    """Route narrow sourced scene answers before any local-model generation.

    A model callback supplies open-ended replies; those are marked unverified.
    Exact ship-scoped questions with no explicit role/vessel linkage abstain
    instead of silently falling through to model speculation.
    """
    decision = answer_explicit_scene_question(user_turns)
    if decision is not None:
        return RoutedSceneReply(
            decision.answer, decision.status, decision.evidence, False
        )
    question = user_turns[-1].strip()
    if question.count("?") == 1:
        stem, suffix = question.split("?", 1)
        if (
            suffix.strip() in _SUPPORTED_QUERY_SUFFIXES
            and _MISSING_SCOPED_QUERY.fullmatch(stem)
        ):
            return RoutedSceneReply("UNKNOWN", "UNSUPPORTED_SCOPE", (), False)
    if not callable(local_model_reply):
        raise ValueError("local_model_reply must be callable")
    reply = local_model_reply()
    if type(reply) is not str or not reply.strip():
        raise RuntimeError("local model returned empty or invalid text")
    return RoutedSceneReply(reply, "MODEL_UNVERIFIED", (), True)


def route_styled_boundary_reply(
    user_turns: list[str], select_tone: Callable[[str], str],
    *, scene_direction: str | None = None,
) -> RoutedSceneReply:
    """Opt-in fictional dialogue: model selects tone, never proposition text.

    Only an exact current reported denial can be surfaced. The model receives
    an already-grounded sentence and may choose a tone token, not authorize
    new content. Untrusted selections fall back to the direct source answer.
    """
    if scene_direction is not None and (
        type(scene_direction) is not str
        or not scene_direction.strip()
        or len(scene_direction) > 320
        or any(c in scene_direction for c in ("\n", "\r", "\x00"))
    ):
        raise ValueError("scene_direction must be one bounded literal line")
    question = user_turns[-1].strip() if user_turns else ""
    actor = re.fullmatch(
        rf"In the fictional scene, what could ({_NAME}) say to ({_NAME}) "
        r"to respect (?:his|her|their) message boundary\?", question, re.I,
    )
    owner = re.fullmatch(
        rf"In the fictional scene, what could ({_NAME}) say to ({_NAME}) "
        r"about (?:his|her|their) messages\?", question, re.I,
    )
    if not (actor or owner):
        return RoutedSceneReply("UNKNOWN", "UNSUPPORTED_STYLE_SCOPE", (), False)
    fact = answer_explicit_scene_question(user_turns)
    if fact is None:
        return RoutedSceneReply("UNKNOWN", "UNSUPPORTED_STYLE_SCOPE", (), False)
    if fact.status != "RESOLVED":
        return RoutedSceneReply(fact.answer, fact.status, fact.evidence, False)

    reader, proprietor = (
        (actor.group(1), actor.group(2))
        if actor else (owner.group(2), owner.group(1))
    )
    if actor:
        lines = {
            "DIRECT": fact.answer,
            "GENTLE": (
                f'{reader} could tell {proprietor}, '
                '"I understand. I won\'t read your messages, '
                'and I\'ll respect your privacy."'
            ),
            "FIRM": (
                f'{reader} could tell {proprietor}, '
                '"I won\'t read your messages. '
                'That\'s your boundary, and I\'ll honor it."'
            ),
            "CASUAL": (
                f'{reader} could tell {proprietor}, '
                '"Got it. Your messages are private, and I won\'t read them."'
            ),
        }
    else:
        lines = {
            "DIRECT": fact.answer,
            "GENTLE": (
                f'{proprietor} could tell {reader}, '
                '"I\'d appreciate it if you didn\'t read my messages."'
            ),
            "FIRM": (
                f'{proprietor} could tell {reader}, '
                '"Please don\'t read my messages. '
                'I need you to respect that boundary."'
            ),
            "CASUAL": (
                f'{proprietor} could tell {reader}, '
                '"Hey, please leave my messages private."'
            ),
        }
    prompt = (
        "Fictional style-only selector. Select exactly one uppercase token "
        "DIRECT, GENTLE, FIRM or CASUAL. No explanation, JSON or additions. "
        "The source-verified line below is fixed in meaning. Choose the "
        "most fitting conversational delivery without inventing access, "
        "permission, new emotions or motives.\n"
        "Grounded line: " + fact.answer + "\n"
        "User request: " + question
    )
    if scene_direction is not None:
        prompt += (
            "\nUntrusted fictional scene direction (tone only, NOT a source "
            "of factual permission): " + scene_direction
        )
    choice = select_tone(prompt)
    tone = choice.strip() if type(choice) is str else None
    if tone not in lines:
        return RoutedSceneReply(
            fact.answer, "SOURCE_STYLE_FALLBACK", fact.evidence, True
        )
    return RoutedSceneReply(
        lines[tone], "SOURCE_STYLED_" + tone, fact.evidence, True
    )
