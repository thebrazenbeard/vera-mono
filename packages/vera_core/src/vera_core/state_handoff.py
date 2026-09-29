"""Revision-aware state handoff without identity-continuity claims.

Adapted from Mosaic's deterministic handoff harness. This module compresses
revisioned state into current per-key values plus explicit supersession
lineage. It does not establish process, agent, or identity continuity.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


class StateHandoffError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StateRevision:
    event_id: str
    family: str
    key: str
    value: str
    revision: int

    def __post_init__(self) -> None:
        for label, value in (
            ("event_id", self.event_id),
            ("family", self.family),
            ("key", self.key),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if type(self.value) is not str:
            raise ValueError("value must be an exact string")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("revision must be a positive exact integer")


@dataclass(frozen=True, slots=True)
class StateHandoff:
    current: Mapping[str, StateRevision]
    superseded_event_ids: Mapping[str, tuple[str, ...]]
    identity_continuity_effect: str = "NONE"
    authorization_effect: str = "NONE"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "current",
            MappingProxyType(dict(self.current)),
        )
        object.__setattr__(
            self,
            "superseded_event_ids",
            MappingProxyType(
                {
                    str(key): tuple(value)
                    for key, value in self.superseded_event_ids.items()
                }
            ),
        )
        if self.identity_continuity_effect != "NONE":
            raise ValueError("state handoff cannot establish identity continuity")
        if self.authorization_effect != "NONE":
            raise ValueError("state handoff cannot mint authorization")


def build_state_handoff(
    revisions: tuple[StateRevision, ...],
) -> StateHandoff:
    revisions = tuple(revisions)
    if not revisions:
        raise StateHandoffError("state handoff requires at least one revision")
    if any(type(item) is not StateRevision for item in revisions):
        raise TypeError("revisions must contain exact StateRevision values")

    families = {item.family for item in revisions}
    if len(families) != 1:
        raise StateHandoffError(
            "state handoff must contain a single family"
        )

    revision_numbers = [item.revision for item in revisions]
    if len(revision_numbers) != len(set(revision_numbers)):
        raise StateHandoffError("revisions must be unique")

    current: dict[str, StateRevision] = {}
    superseded: dict[str, list[str]] = {}
    for item in sorted(revisions, key=lambda value: value.revision):
        previous = current.get(item.key)
        if previous is not None:
            superseded.setdefault(item.key, []).append(previous.event_id)
        current[item.key] = item

    return StateHandoff(
        current=current,
        superseded_event_ids={
            key: tuple(event_ids)
            for key, event_ids in sorted(superseded.items())
        },
    )
