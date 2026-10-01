"""Provider-neutral admission invariants for external capabilities and substrates.

This module classifies what an external connector or host-composed substrate can
supply without allowing visibility, persistence, or execution capability to
become Vera identity, source authority, core runtime coupling, runtime
activation, canonical memory authority, or effect authority. Provider-specific
implementations remain host-composed adapters outside this contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


_PROVIDER_ID = re.compile(r"^[a-z0-9][a-z0-9_.:-]*$")


class ExternalCapabilityClass(StrEnum):
    OBSERVATION_SOURCE = "OBSERVATION_SOURCE"
    DATA_PROVIDER = "DATA_PROVIDER"
    ACTION_PROVIDER = "ACTION_PROVIDER"
    COMPUTE_PROVIDER = "COMPUTE_PROVIDER"
    COMMUNICATION_PROVIDER = "COMMUNICATION_PROVIDER"
    STORAGE_PROVIDER = "STORAGE_PROVIDER"
    RESEARCH_PROVIDER = "RESEARCH_PROVIDER"
    DESIGN_PROVIDER = "DESIGN_PROVIDER"
    DEPLOYMENT_PROVIDER = "DEPLOYMENT_PROVIDER"
    WORKSTATION_PROVIDER = "WORKSTATION_PROVIDER"
    REVIEW_PROVIDER = "REVIEW_PROVIDER"
    OPTIONAL_AUXILIARY = "OPTIONAL_AUXILIARY"
    NOT_RELEVANT = "NOT_RELEVANT"


class ExternalProviderKind(StrEnum):
    EXTERNAL_CONNECTOR = "EXTERNAL_CONNECTOR"
    INTERNAL_SUPPORT = "INTERNAL_SUPPORT"
    SUPPLIED_CANDIDATE = "SUPPLIED_CANDIDATE"
    HOST_EXECUTION_SUBSTRATE = "HOST_EXECUTION_SUBSTRATE"
    STATE_EVIDENCE_SUBSTRATE = "STATE_EVIDENCE_SUBSTRATE"


class ExternalSubstrateRole(StrEnum):
    NONE = "NONE"
    HOST_EXECUTION = "HOST_EXECUTION"
    STATE_EVIDENCE_COORDINATION = "STATE_EVIDENCE_COORDINATION"


@dataclass(frozen=True, slots=True)
class ExternalProviderAdmission:
    """A semantic admission record, never an authorization record."""

    provider_id: str
    capability_classes: tuple[ExternalCapabilityClass, ...]
    provider_kind: ExternalProviderKind = ExternalProviderKind.EXTERNAL_CONNECTOR
    substrate_role: ExternalSubstrateRole = ExternalSubstrateRole.NONE
    core_runtime_dependency: bool = False
    identity_authority: str = "NONE"
    source_authority: str = "NONE"
    availability_implies_authority: bool = False
    effect_authorization: str = "EXTERNAL_DECISION_REQUIRED"

    def __post_init__(self) -> None:
        if type(self.provider_id) is not str or not _PROVIDER_ID.fullmatch(
            self.provider_id
        ):
            raise ValueError(
                "provider_id must match [a-z0-9][a-z0-9_.:-]* exactly"
            )
        if type(self.capability_classes) is not tuple or not self.capability_classes:
            raise ValueError("capability_classes must be a non-empty exact tuple")
        if any(type(item) is not ExternalCapabilityClass for item in self.capability_classes):
            raise TypeError(
                "capability_classes must contain exact ExternalCapabilityClass values"
            )
        if len(set(self.capability_classes)) != len(self.capability_classes):
            raise ValueError("capability_classes must not contain duplicates")
        if type(self.provider_kind) is not ExternalProviderKind:
            raise TypeError("provider_kind must be exact ExternalProviderKind")
        if type(self.substrate_role) is not ExternalSubstrateRole:
            raise TypeError("substrate_role must be exact ExternalSubstrateRole")

        expected_role = {
            ExternalProviderKind.HOST_EXECUTION_SUBSTRATE: ExternalSubstrateRole.HOST_EXECUTION,
            ExternalProviderKind.STATE_EVIDENCE_SUBSTRATE: ExternalSubstrateRole.STATE_EVIDENCE_COORDINATION,
        }.get(self.provider_kind, ExternalSubstrateRole.NONE)
        if self.substrate_role is not expected_role:
            raise ValueError("substrate role must match provider kind exactly")

        if type(self.core_runtime_dependency) is not bool:
            raise TypeError("core_runtime_dependency must be bool")
        if self.core_runtime_dependency:
            raise ValueError(
                "external provider admission cannot create a Vera core runtime dependency"
            )
        if self.identity_authority != "NONE":
            raise ValueError("external provider admission cannot own Vera identity")
        if self.source_authority != "NONE":
            raise ValueError(
                "external provider admission cannot become Vera source authority"
            )
        if type(self.availability_implies_authority) is not bool:
            raise TypeError("availability_implies_authority must be bool")
        if self.availability_implies_authority:
            raise ValueError("capability availability cannot imply effect authority")
        if self.effect_authorization != "EXTERNAL_DECISION_REQUIRED":
            raise ValueError(
                "external provider admission cannot mint effect authorization"
            )

    @property
    def can_supply_actions(self) -> bool:
        """Descriptive action capability only; never permission to execute."""

        return any(
            item
            in {
                ExternalCapabilityClass.ACTION_PROVIDER,
                ExternalCapabilityClass.DEPLOYMENT_PROVIDER,
                ExternalCapabilityClass.WORKSTATION_PROVIDER,
            }
            for item in self.capability_classes
        )

    @property
    def is_external_substrate(self) -> bool:
        """True only for explicitly classified host/state substrate roles."""

        return self.substrate_role is not ExternalSubstrateRole.NONE


def validate_external_provider_catalog(
    admissions: tuple[ExternalProviderAdmission, ...],
) -> tuple[str, ...]:
    """Return deterministic catalog defects without mutating any provider state."""

    if type(admissions) is not tuple:
        raise TypeError("admissions must be an exact tuple")

    defects: list[str] = []
    seen: set[str] = set()
    for index, admission in enumerate(admissions):
        if type(admission) is not ExternalProviderAdmission:
            defects.append(f"index {index}: not exact ExternalProviderAdmission")
            continue
        if admission.provider_id in seen:
            defects.append(f"duplicate provider_id: {admission.provider_id}")
        seen.add(admission.provider_id)
    return tuple(defects)


__all__ = [
    "ExternalCapabilityClass",
    "ExternalProviderAdmission",
    "ExternalProviderKind",
    "ExternalSubstrateRole",
    "validate_external_provider_catalog",
]
