"""Deterministic simulation boundary with explicit external-effect rejection.

Adapted from Vera Habitat. Simulated mutations may advance only local
simulation state. External requests are rejected here and must cross Vera
Mono's separate qualified effect boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import copy
import hashlib
import json
from typing import Any, Mapping


class SimulationEffectClass(StrEnum):
    SIMULATION_ONLY = "SIMULATION_ONLY"
    EXTERNAL_REQUEST = "EXTERNAL_REQUEST"


@dataclass(frozen=True, slots=True)
class SimulationMutation:
    mutation_id: str
    effect_class: SimulationEffectClass
    subject_id: str
    patch: Mapping[str, Any]

    def __post_init__(self) -> None:
        for label, value in (
            ("mutation_id", self.mutation_id),
            ("subject_id", self.subject_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if type(self.effect_class) is not SimulationEffectClass:
            raise TypeError("effect_class must be exact SimulationEffectClass")
        if not isinstance(self.patch, Mapping):
            raise TypeError("patch must be a mapping")
        object.__setattr__(self, "patch", dict(self.patch))

    def request_digest(self) -> str:
        canonical = json.dumps(
            {
                "mutation_id": self.mutation_id,
                "effect_class": self.effect_class.value,
                "subject_id": self.subject_id,
                "patch": self.patch,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SimulationReceipt:
    mutation_id: str
    accepted: bool
    disposition: str
    revision_before: int
    revision_after: int
    request_digest: str
    external_effect: bool = False
    authorization_effect: str = "NONE"


class SimulationState:
    """Revisioned local simulation state with idempotent mutation receipts."""

    def __init__(self, subjects: Mapping[str, Mapping[str, Any]] | None = None):
        source = {} if subjects is None else subjects
        self._subjects = {
            str(subject_id): dict(values)
            for subject_id, values in source.items()
        }
        self._revision = 0
        self._receipts: dict[str, SimulationReceipt] = {}

    @property
    def revision(self) -> int:
        return self._revision

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(
            {
                subject_id: self._subjects[subject_id]
                for subject_id in sorted(self._subjects)
            }
        )

    def apply(self, mutation: SimulationMutation) -> SimulationReceipt:
        if type(mutation) is not SimulationMutation:
            raise TypeError("mutation must be exact SimulationMutation")
        digest = mutation.request_digest()
        prior = self._receipts.get(mutation.mutation_id)
        if prior is not None:
            if prior.request_digest != digest:
                raise ValueError("mutation_id replay carries different request")
            return prior

        before = self._revision
        if mutation.effect_class is SimulationEffectClass.EXTERNAL_REQUEST:
            receipt = SimulationReceipt(
                mutation_id=mutation.mutation_id,
                accepted=False,
                disposition="EXTERNAL_EFFECT_UNAVAILABLE",
                revision_before=before,
                revision_after=before,
                request_digest=digest,
            )
            self._receipts[mutation.mutation_id] = receipt
            return receipt

        current = self._subjects.get(mutation.subject_id)
        if current is None:
            receipt = SimulationReceipt(
                mutation_id=mutation.mutation_id,
                accepted=False,
                disposition="UNKNOWN_SIMULATION_SUBJECT",
                revision_before=before,
                revision_after=before,
                request_digest=digest,
            )
            self._receipts[mutation.mutation_id] = receipt
            return receipt

        updated = dict(current)
        updated.update(dict(mutation.patch))
        self._subjects[mutation.subject_id] = updated
        self._revision += 1
        receipt = SimulationReceipt(
            mutation_id=mutation.mutation_id,
            accepted=True,
            disposition="SIMULATION_MUTATION_APPLIED",
            revision_before=before,
            revision_after=self._revision,
            request_digest=digest,
        )
        self._receipts[mutation.mutation_id] = receipt
        return receipt
