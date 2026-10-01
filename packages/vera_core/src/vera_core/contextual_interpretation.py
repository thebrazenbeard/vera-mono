"""Context-bound interpretation and supersession.

Adapted from the deterministic mechanism in
thebrazenbeard/semiotics@37117a2097f7f2aa35968fc9db24eacf7240826e.

This module records source-bound competing readings for one subject. Matching
context establishes compatibility only; specificity is deterministic ordering,
not confidence, truth, currentness, or authority.
"""

from __future__ import annotations

from dataclasses import dataclass


class ContextualInterpretationError(ValueError):
    pass


RELATION_KINDS = frozenset(
    {"contrasts_with", "contradicts", "supports", "refines"}
)


def _exact_text(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContextualInterpretationError(
            f"{label} must be a non-empty exact string"
        )
    return value


def _exact_tags(value: frozenset[str], label: str) -> frozenset[str]:
    if type(value) is not frozenset:
        raise ContextualInterpretationError(f"{label} must be a frozenset")
    for tag in value:
        _exact_text(tag, f"{label} tag")
    return value


@dataclass(frozen=True, slots=True)
class ContextualInterpretation:
    interpretation_id: str
    subject_id: str
    meaning: str
    source_ref: str
    required_context: frozenset[str] = frozenset()
    excluded_context: frozenset[str] = frozenset()
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        _exact_text(self.interpretation_id, "interpretation_id")
        _exact_text(self.subject_id, "subject_id")
        _exact_text(self.meaning, "meaning")
        _exact_text(self.source_ref, "source_ref")
        _exact_tags(self.required_context, "required_context")
        _exact_tags(self.excluded_context, "excluded_context")
        if self.supersedes_id is not None:
            _exact_text(self.supersedes_id, "supersedes_id")
        overlap = self.required_context & self.excluded_context
        if overlap:
            raise ContextualInterpretationError(
                "an interpretation cannot require and exclude the same context: "
                + ", ".join(sorted(overlap))
            )

    @property
    def specificity(self) -> int:
        return len(self.required_context) + len(self.excluded_context)

    def matches(self, context: frozenset[str]) -> bool:
        _exact_tags(context, "context")
        return (
            self.required_context.issubset(context)
            and self.excluded_context.isdisjoint(context)
        )


@dataclass(frozen=True, slots=True)
class InterpretationRelation:
    relation_id: str
    left_id: str
    right_id: str
    kind: str
    source_ref: str

    def __post_init__(self) -> None:
        for label, value in (
            ("relation_id", self.relation_id),
            ("left_id", self.left_id),
            ("right_id", self.right_id),
            ("kind", self.kind),
            ("source_ref", self.source_ref),
        ):
            _exact_text(value, label)
        if self.left_id == self.right_id:
            raise ContextualInterpretationError(
                "a relation must connect distinct interpretations"
            )
        if self.kind not in RELATION_KINDS:
            raise ContextualInterpretationError(
                f"unsupported relation kind: {self.kind}"
            )


@dataclass(frozen=True, slots=True)
class ContextualInterpretationMatch:
    interpretation: ContextualInterpretation
    relations: tuple[InterpretationRelation, ...]


class ContextualInterpretationRegistry:
    def __init__(
        self,
        interpretations: tuple[ContextualInterpretation, ...],
        relations: tuple[InterpretationRelation, ...] = (),
    ) -> None:
        by_id: dict[str, ContextualInterpretation] = {}
        for item in interpretations:
            if item.interpretation_id in by_id:
                raise ContextualInterpretationError(
                    f"duplicate interpretation id: {item.interpretation_id}"
                )
            by_id[item.interpretation_id] = item

        relation_ids: set[str] = set()
        for relation in relations:
            if relation.relation_id in relation_ids:
                raise ContextualInterpretationError(
                    f"duplicate relation id: {relation.relation_id}"
                )
            relation_ids.add(relation.relation_id)
            for endpoint in (relation.left_id, relation.right_id):
                if endpoint not in by_id:
                    raise ContextualInterpretationError(
                        f"relation {relation.relation_id} references "
                        f"unknown interpretation {endpoint}"
                    )

        for item in interpretations:
            if item.supersedes_id is None:
                continue
            prior = by_id.get(item.supersedes_id)
            if prior is None:
                raise ContextualInterpretationError(
                    f"{item.interpretation_id} supersedes unknown "
                    f"interpretation {item.supersedes_id}"
                )
            if prior.subject_id != item.subject_id:
                raise ContextualInterpretationError(
                    "an interpretation may supersede only the same subject"
                )

        for item in interpretations:
            seen: set[str] = set()
            current = item
            while current.supersedes_id is not None:
                if current.interpretation_id in seen:
                    raise ContextualInterpretationError(
                        "interpretation supersession contains a cycle"
                    )
                seen.add(current.interpretation_id)
                current = by_id[current.supersedes_id]

        self._interpretations = interpretations
        self._relations = relations
        self._by_id = by_id

    def query(
        self,
        subject_id: str,
        context: frozenset[str] = frozenset(),
        *,
        include_superseded: bool = False,
    ) -> tuple[ContextualInterpretationMatch, ...]:
        _exact_text(subject_id, "subject_id")
        _exact_tags(context, "context")

        superseded_ids = {
            item.supersedes_id
            for item in self._interpretations
            if item.supersedes_id is not None
        }
        matched = [
            item
            for item in self._interpretations
            if item.subject_id == subject_id
            and item.matches(context)
            and (
                include_superseded
                or item.interpretation_id not in superseded_ids
            )
        ]
        matched.sort(
            key=lambda item: (-item.specificity, item.interpretation_id)
        )

        return tuple(
            ContextualInterpretationMatch(
                interpretation=item,
                relations=tuple(
                    sorted(
                        (
                            relation
                            for relation in self._relations
                            if item.interpretation_id
                            in {relation.left_id, relation.right_id}
                        ),
                        key=lambda relation: relation.relation_id,
                    )
                ),
            )
            for item in matched
        )
