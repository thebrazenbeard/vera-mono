"""Deterministic simulation boundary with explicit external-effect rejection.

Adapted from Vera Habitat. Simulated mutations may advance only local
simulation state. External requests are rejected here and must cross Vera
Mono's separate qualified effect boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import copy
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Mapping


_MAX_PATCH_DEPTH = 64
_MAX_PATCH_NODES = 100_000
_MAX_PATCH_BYTES = 1_048_576


def _json_patch_copy(value: object, *, depth: int = 0,
                     ancestors: set[int] | None = None,
                     remaining: list[int] | None = None) -> Any:
    """Detach exact JSON-like data; never invoke custom repr/copy hooks."""
    if ancestors is None:
        ancestors = set()
    if remaining is None:
        remaining = [_MAX_PATCH_NODES]
    remaining[0] -= 1
    if remaining[0] < 0 or depth > _MAX_PATCH_DEPTH:
        raise ValueError("patch exceeds bounded JSON-compatible shape")

    if value is None or type(value) in (str, bool):
        return value
    if type(value) is int:
        if value.bit_length() > 4096:
            raise ValueError("patch contains oversized non-JSON-compatible integer")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("patch contains nonfinite non-JSON-compatible number")
        return value
    if type(value) not in (dict, MappingProxyType, list):
        raise TypeError("patch must contain only JSON-compatible values")
    identity = id(value)
    if identity in ancestors:
        raise ValueError("patch contains cyclic non-JSON-compatible values")
    ancestors.add(identity)
    try:
        if type(value) is list:
            return [_json_patch_copy(item, depth=depth + 1,
                                     ancestors=ancestors, remaining=remaining)
                    for item in value]
        if any(type(key) is not str for key in value):
            raise TypeError("patch object keys must be JSON-compatible strings")
        return {key: _json_patch_copy(item, depth=depth + 1,
                                      ancestors=ancestors, remaining=remaining)
                for key, item in value.items()}
    finally:
        ancestors.remove(identity)


class SimulationEffectClass(StrEnum):
    SIMULATION_ONLY = "SIMULATION_ONLY"
    EXTERNAL_REQUEST = "EXTERNAL_REQUEST"


@dataclass(frozen=True, slots=True)
class SimulationMutation:
    mutation_id: str
    effect_class: SimulationEffectClass
    subject_id: str
    patch: Mapping[str, Any]
    _initial_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for label, value in (
            ("mutation_id", self.mutation_id),
            ("subject_id", self.subject_id),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if type(self.effect_class) is not SimulationEffectClass:
            raise TypeError("effect_class must be exact SimulationEffectClass")
        if type(self.patch) not in (dict, MappingProxyType):
            raise TypeError("patch must be a JSON-compatible mapping")
        # Recursively rebuild the patch to detach caller-owned containers.
        # Only exact JSON-like primitives are accepted: no custom __str__,
        # __deepcopy__, object identity, or unserializable state can enter.
        object.__setattr__(self, "patch", MappingProxyType(_json_patch_copy(self.patch)))
        object.__setattr__(self, "_initial_digest", self._digest_for(self.patch))

    def _digest_for(self, patch: Mapping[str, Any]) -> str:
        try:
            canonical = json.dumps(
                {
                    "mutation_id": self.mutation_id,
                    "effect_class": self.effect_class.value,
                    "subject_id": self.subject_id,
                    "patch": dict(patch),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("patch must be UTF-8 JSON-compatible") from exc
        if len(canonical) > _MAX_PATCH_BYTES:
            raise ValueError("patch exceeds JSON-compatible byte budget")
        return hashlib.sha256(canonical).hexdigest()

    def request_digest(self) -> str:
        """The creation-time request fingerprint, not a mutable live view."""
        return self._initial_digest

    def _admitted_patch_copy(self) -> dict[str, Any]:
        """Freeze one candidate copy and reject post-construction tampering."""
        candidate = _json_patch_copy(self.patch)
        if self._digest_for(candidate) != self._initial_digest:
            raise ValueError("mutation patch changed after construction")
        return candidate


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
        patch = mutation._admitted_patch_copy()
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
        updated.update(patch)
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
