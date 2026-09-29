from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import hashlib
import json
from typing import Iterable, Sequence


class TransferFidelity(StrEnum):
    EXACT = "EXACT"
    CONSTRUCTIVE = "CONSTRUCTIVE"
    LOSSY = "LOSSY"
    UNREPRESENTABLE = "UNREPRESENTABLE"

    @property
    def severity(self) -> int:
        return {
            TransferFidelity.EXACT: 0,
            TransferFidelity.CONSTRUCTIVE: 1,
            TransferFidelity.LOSSY: 2,
            TransferFidelity.UNREPRESENTABLE: 3,
        }[self]


@dataclass(frozen=True, slots=True)
class SemanticCapabilityProfile:
    profile_id: str
    capabilities: frozenset[str]
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.profile_id) is not str or not self.profile_id:
            raise ValueError("profile_id must be a non-empty exact string")
        if any(type(item) is not str or not item for item in self.capabilities):
            raise ValueError("capabilities must contain non-empty exact strings")

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class SemanticTransferRule:
    name: str
    source_capability: str
    target_capabilities: frozenset[str]
    fidelity: TransferFidelity
    description: str
    target_profiles: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name:
            raise ValueError("rule name must be a non-empty exact string")
        if type(self.source_capability) is not str or not self.source_capability:
            raise ValueError("source_capability must be a non-empty exact string")
        if not self.target_capabilities:
            raise ValueError("target_capabilities must not be empty")
        if any(type(item) is not str or not item for item in self.target_capabilities):
            raise ValueError("target_capabilities must contain non-empty exact strings")
        if type(self.description) is not str or not self.description.strip():
            raise ValueError("description must be non-empty")

    def applies_to(self, target: SemanticCapabilityProfile) -> bool:
        if self.target_profiles and target.profile_id not in self.target_profiles:
            return False
        return self.target_capabilities.issubset(target.capabilities)


@dataclass(frozen=True, slots=True)
class SemanticTransferCatalog:
    """Immutable admitted semantic-transfer profiles and rewrite rules."""

    catalog_id: str
    profiles: tuple[SemanticCapabilityProfile, ...]
    rules: tuple[SemanticTransferRule, ...] = ()

    def __post_init__(self) -> None:
        if type(self.catalog_id) is not str or not self.catalog_id:
            raise ValueError("catalog_id must be a non-empty exact string")
        object.__setattr__(self, "profiles", tuple(self.profiles))
        object.__setattr__(self, "rules", tuple(self.rules))
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("catalog profile_id values must be unique")

    def profile(self, profile_id: str) -> SemanticCapabilityProfile:
        for profile in self.profiles:
            if profile.profile_id == profile_id:
                return profile
        raise KeyError(f"UNKNOWN_SEMANTIC_PROFILE:{profile_id}")

    def manifest(self) -> dict[str, object]:
        profiles = [
            {
                "profile_id": profile.profile_id,
                "capabilities": sorted(profile.capabilities),
                "notes": list(profile.notes),
            }
            for profile in sorted(self.profiles, key=lambda item: item.profile_id)
        ]
        rules = [
            {
                "name": rule.name,
                "source_capability": rule.source_capability,
                "target_capabilities": sorted(rule.target_capabilities),
                "target_profiles": sorted(rule.target_profiles),
                "fidelity": rule.fidelity.value,
                "description": rule.description,
            }
            for rule in sorted(
                self.rules,
                key=lambda item: (
                    item.source_capability,
                    item.fidelity.severity,
                    item.name,
                ),
            )
        ]
        return {
            "schema": "VERA_SEMANTIC_TRANSFER_CATALOG_V1",
            "catalog_id": self.catalog_id,
            "profiles": profiles,
            "rules": rules,
        }

    @property
    def digest(self) -> str:
        canonical = json.dumps(
            self.manifest(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AppliedSemanticRewrite:
    source_capability: str
    rule_name: str
    fidelity: TransferFidelity
    description: str


@dataclass(frozen=True, slots=True)
class SemanticTransferPlan:
    source_profile: str
    target_profile: str
    required_capabilities: frozenset[str]
    native_capabilities: frozenset[str]
    missing_capabilities: frozenset[str]
    unresolved_capabilities: frozenset[str]
    rewrites: tuple[AppliedSemanticRewrite, ...]
    fidelity: TransferFidelity
    semantic_equivalence: str = "NOT_ESTABLISHED"
    authorization_effect: str = "NONE"
    catalog_id: str | None = None
    catalog_digest: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "source_profile": self.source_profile,
            "target_profile": self.target_profile,
            "required_capabilities": sorted(self.required_capabilities),
            "native_capabilities": sorted(self.native_capabilities),
            "missing_capabilities": sorted(self.missing_capabilities),
            "unresolved_capabilities": sorted(self.unresolved_capabilities),
            "rewrites": [
                {
                    "source_capability": rewrite.source_capability,
                    "rule_name": rewrite.rule_name,
                    "fidelity": rewrite.fidelity.value,
                    "description": rewrite.description,
                }
                for rewrite in self.rewrites
            ],
            "fidelity": self.fidelity.value,
            "semantic_equivalence": self.semantic_equivalence,
            "authorization_effect": self.authorization_effect,
            "catalog_id": self.catalog_id,
            "catalog_digest": self.catalog_digest,
        }


def _worst_fidelity(
    values: Iterable[TransferFidelity],
) -> TransferFidelity:
    values = tuple(values)
    if not values:
        return TransferFidelity.EXACT
    return max(values, key=lambda value: value.severity)


def plan_semantic_transfer(
    source: SemanticCapabilityProfile,
    target: SemanticCapabilityProfile,
    required_capabilities: Iterable[str],
    *,
    rules: Sequence[SemanticTransferRule] = (),
) -> SemanticTransferPlan:
    required = frozenset(required_capabilities)
    if any(type(item) is not str or not item for item in required):
        raise ValueError("required_capabilities must contain non-empty exact strings")

    unadmitted = sorted(
        capability
        for capability in required
        if not source.supports(capability)
    )
    if unadmitted:
        raise ValueError(
            "SOURCE_CAPABILITY_NOT_ADMITTED:" + ",".join(unadmitted)
        )

    native = frozenset(
        capability
        for capability in required
        if target.supports(capability)
    )
    missing = frozenset(required - native)
    unresolved: set[str] = set()
    rewrites: list[AppliedSemanticRewrite] = []

    for capability in sorted(missing):
        candidates = [
            rule
            for rule in rules
            if rule.source_capability == capability
            and rule.applies_to(target)
        ]
        if not candidates:
            unresolved.add(capability)
            continue

        selected = min(
            candidates,
            key=lambda rule: (rule.fidelity.severity, rule.name),
        )
        rewrites.append(
            AppliedSemanticRewrite(
                source_capability=capability,
                rule_name=selected.name,
                fidelity=selected.fidelity,
                description=selected.description,
            )
        )

    fidelity = (
        TransferFidelity.UNREPRESENTABLE
        if unresolved
        else _worst_fidelity(rewrite.fidelity for rewrite in rewrites)
    )

    return SemanticTransferPlan(
        source_profile=source.profile_id,
        target_profile=target.profile_id,
        required_capabilities=required,
        native_capabilities=native,
        missing_capabilities=missing,
        unresolved_capabilities=frozenset(unresolved),
        rewrites=tuple(rewrites),
        fidelity=fidelity,
    )


def plan_catalog_semantic_transfer(
    catalog: SemanticTransferCatalog,
    source_profile_id: str,
    target_profile_id: str,
    required_capabilities: Iterable[str],
) -> SemanticTransferPlan:
    """Plan a transfer and bind the result to the exact admitted catalog."""

    plan = plan_semantic_transfer(
        catalog.profile(source_profile_id),
        catalog.profile(target_profile_id),
        required_capabilities,
        rules=catalog.rules,
    )
    return replace(
        plan,
        catalog_id=catalog.catalog_id,
        catalog_digest=catalog.digest,
    )
