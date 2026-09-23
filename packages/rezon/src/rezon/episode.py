from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from threading import RLock

from .epistemics import Hyperrelation, Participant, Proposition, PropositionKind


class EpisodeInvariantError(ValueError):
    pass


def _require_exact_str_tuple(values, label: str) -> None:
    if type(values) is not tuple or any(
        type(value) is not str or not value
        for value in values
    ):
        raise EpisodeInvariantError(
            f"{label} must be a tuple of non-empty exact str values"
        )


def _validate_proposition(proposition: Proposition) -> None:
    if type(proposition) is not Proposition:
        raise EpisodeInvariantError("canonical proposition must be exact Proposition")
    if (
        type(proposition.proposition_id) is not str
        or not proposition.proposition_id
        or type(proposition.episode_id) is not str
        or not proposition.episode_id
        or type(proposition.content) is not str
        or not proposition.content
    ):
        raise EpisodeInvariantError(
            "canonical proposition identity/content fields must be non-empty exact str"
        )
    if type(proposition.kind) is not PropositionKind:
        raise EpisodeInvariantError("canonical proposition kind must be exact PropositionKind")
    if (
        proposition.producer_execution_id is not None
        and (
            type(proposition.producer_execution_id) is not str
            or not proposition.producer_execution_id
        )
    ):
        raise EpisodeInvariantError(
            "canonical proposition producer identity must be a non-empty exact str"
        )
    if proposition.confidence is not None and type(proposition.confidence) is not float:
        raise EpisodeInvariantError("canonical proposition confidence must be exact float")
    _require_exact_str_tuple(proposition.source_refs, "canonical proposition source refs")
    _require_exact_str_tuple(
        proposition.source_versions,
        "canonical proposition source versions",
    )


def _validate_relation(relation: Hyperrelation) -> None:
    if type(relation) is not Hyperrelation:
        raise EpisodeInvariantError("canonical relation must be exact Hyperrelation")
    if (
        type(relation.relation_id) is not str
        or not relation.relation_id
        or type(relation.episode_id) is not str
        or not relation.episode_id
        or type(relation.relation_type) is not str
        or not relation.relation_type
    ):
        raise EpisodeInvariantError(
            "canonical relation identity/type fields must be non-empty exact str"
        )
    if (
        relation.producer_execution_id is not None
        and (
            type(relation.producer_execution_id) is not str
            or not relation.producer_execution_id
        )
    ):
        raise EpisodeInvariantError(
            "canonical relation producer identity must be a non-empty exact str"
        )
    _require_exact_str_tuple(relation.source_refs, "canonical relation source refs")
    _require_exact_str_tuple(relation.source_versions, "canonical relation source versions")
    if type(relation.participants) is not tuple:
        raise EpisodeInvariantError("canonical relation participants must be an exact tuple")
    for participant in relation.participants:
        if type(participant) is not Participant:
            raise EpisodeInvariantError("canonical relation participant must be exact Participant")
        if (
            type(participant.ref_id) is not str
            or not participant.ref_id
            or type(participant.role) is not str
            or not participant.role
        ):
            raise EpisodeInvariantError(
                "canonical participant identity/role fields must be non-empty exact str"
            )


def _episode_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


@dataclass(frozen=True)
class EpisodeEvent:
    event_id: str
    episode_id: str
    event_type: str
    target_id: str
    reason: str | None = None


@dataclass(frozen=True)
class EpisodeSnapshot:
    episode_id: str
    version: int
    current_propositions: tuple[Proposition, ...]
    all_propositions: tuple[Proposition, ...]
    current_relations: tuple[Hyperrelation, ...]
    all_relations: tuple[Hyperrelation, ...]
    events: tuple[EpisodeEvent, ...]

    @property
    def version_ref(self) -> str:
        return f"{self.episode_id}@{self.version}"


class Episode:
    def __init__(self, episode_id: str):
        if type(episode_id) is not str or not episode_id:
            raise EpisodeInvariantError("episode_id must be a non-empty exact str")
        self._episode_id = episode_id
        self._propositions: dict[str, Proposition] = {}
        self._relations: dict[str, Hyperrelation] = {}
        self._active_propositions: set[str] = set()
        self._active_relations: set[str] = set()
        self._events: list[EpisodeEvent] = []
        self._lock = RLock()

    @property
    def episode_id(self) -> str:
        return self._episode_id

    @episode_id.setter
    def episode_id(self, value: str) -> None:
        raise EpisodeInvariantError("episode_id is immutable after construction")

    @contextmanager
    def atomic_mutation(self):
        with self._lock:
            checkpoint = (
                self._propositions.copy(),
                self._relations.copy(),
                self._active_propositions.copy(),
                self._active_relations.copy(),
                list(self._events),
            )
            try:
                yield
            except BaseException:
                (
                    self._propositions,
                    self._relations,
                    self._active_propositions,
                    self._active_relations,
                    self._events,
                ) = checkpoint
                raise

    def _event(self, event_type: str, target_id: str, reason: str | None = None) -> None:
        self._events.append(EpisodeEvent(
            event_id=f"{self.episode_id}:event:{len(self._events) + 1}",
            episode_id=self.episode_id,
            event_type=event_type,
            target_id=target_id,
            reason=reason,
        ))

    def _inactive_canonical_source_refs(self, source_refs: tuple[str, ...]) -> list[str]:
        known = set(self._propositions) | set(self._relations)
        active = self._active_propositions | self._active_relations
        return [source_ref for source_ref in source_refs if source_ref in known and source_ref not in active]

    @_episode_locked
    def add_proposition(self, proposition: Proposition) -> None:
        _validate_proposition(proposition)
        if proposition.episode_id != self.episode_id:
            raise EpisodeInvariantError("proposition belongs to a different episode")
        inactive_sources = self._inactive_canonical_source_refs(proposition.source_refs)
        if inactive_sources:
            raise EpisodeInvariantError(
                f"proposition references inactive canonical sources: {inactive_sources}"
            )
        previous = self._propositions.get(proposition.proposition_id)
        if previous is not None:
            if previous != proposition:
                raise EpisodeInvariantError("duplicate proposition ID has conflicting content")
            if proposition.proposition_id not in self._active_propositions:
                raise EpisodeInvariantError("retracted proposition ID cannot be silently reactivated")
            return
        self._propositions[proposition.proposition_id] = proposition
        self._active_propositions.add(proposition.proposition_id)
        self._event("proposition_added", proposition.proposition_id)

    @_episode_locked
    def retract_proposition(self, proposition_id: str, reason: str) -> None:
        if type(proposition_id) is not str or not proposition_id:
            raise EpisodeInvariantError("proposition_id must be a non-empty exact str")
        if type(reason) is not str or not reason:
            raise EpisodeInvariantError("retraction reason must be a non-empty exact str")
        if proposition_id not in self._propositions:
            raise EpisodeInvariantError("cannot retract unknown proposition")
        if proposition_id not in self._active_propositions:
            raise EpisodeInvariantError("proposition is already retracted")
        self._active_propositions.remove(proposition_id)
        self._event("proposition_retracted", proposition_id, reason)

        # Canonical object IDs appearing in source_refs are dependency edges for
        # currentness. External provenance strings remain provenance-only because
        # they do not resolve to canonical proposition/relation IDs.
        invalidated_refs = {proposition_id}
        while True:
            changed = False

            for dependent_id in tuple(self._active_propositions):
                dependent = self._propositions[dependent_id]
                if any(source_ref in invalidated_refs for source_ref in dependent.source_refs):
                    self._active_propositions.remove(dependent_id)
                    self._event(
                        "proposition_invalidated",
                        dependent_id,
                        f"dependency_retracted:{proposition_id}",
                    )
                    invalidated_refs.add(dependent_id)
                    changed = True

            for relation_id in tuple(self._active_relations):
                relation = self._relations[relation_id]
                participant_invalid = any(
                    participant.ref_id in invalidated_refs
                    for participant in relation.participants
                )
                provenance_dependency_invalid = any(
                    source_ref in invalidated_refs for source_ref in relation.source_refs
                )
                if participant_invalid or provenance_dependency_invalid:
                    self._active_relations.remove(relation_id)
                    self._event(
                        "relation_invalidated",
                        relation_id,
                        f"dependency_retracted:{proposition_id}",
                    )
                    invalidated_refs.add(relation_id)
                    changed = True

            if not changed:
                break

    @_episode_locked
    def add_relation(self, relation: Hyperrelation) -> None:
        _validate_relation(relation)
        if relation.episode_id != self.episode_id:
            raise EpisodeInvariantError("relation belongs to a different episode")
        active_refs = self._active_propositions | self._active_relations
        unavailable = [p.ref_id for p in relation.participants if p.ref_id not in active_refs]
        if unavailable:
            raise EpisodeInvariantError(
                f"relation references inactive or unknown objects: {unavailable}"
            )
        inactive_sources = self._inactive_canonical_source_refs(relation.source_refs)
        if inactive_sources:
            raise EpisodeInvariantError(
                f"relation references inactive canonical sources: {inactive_sources}"
            )
        previous = self._relations.get(relation.relation_id)
        if previous is not None:
            if previous != relation:
                raise EpisodeInvariantError("duplicate relation ID has conflicting content")
            if relation.relation_id not in self._active_relations:
                raise EpisodeInvariantError("invalidated relation ID cannot be silently reactivated")
            return
        self._relations[relation.relation_id] = relation
        self._active_relations.add(relation.relation_id)
        self._event("relation_added", relation.relation_id)

    @_episode_locked
    def snapshot(self) -> EpisodeSnapshot:
        return EpisodeSnapshot(
            episode_id=self.episode_id,
            version=len(self._events),
            current_propositions=tuple(p for k, p in self._propositions.items() if k in self._active_propositions),
            all_propositions=tuple(self._propositions.values()),
            current_relations=tuple(r for k, r in self._relations.items() if k in self._active_relations),
            all_relations=tuple(self._relations.values()),
            events=tuple(self._events),
        )
