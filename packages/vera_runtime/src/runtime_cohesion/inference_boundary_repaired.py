from __future__ import annotations

"""Repaired canonical provider-neutral inference boundary.

This module supersedes the first R3 implementation surface for canonical package
exports.  It closes two exact review defects without changing the source/effect
claim ceiling:

1. source-declared MANDATORY components cannot be downgraded by a caller that
   omits them from ``mandatory_component_ids``; caller policy may strengthen but
   never weaken the component-bound requirement class;
2. capability/projection/reservation bind an exact digest of the *admission
   result*, not merely the pre-admission composition digest.

The original ``runtime_cohesion.inference_boundary`` module remains historical
source provenance for R3.  Canonical package exports and the runtime hook point to
this repaired module.
"""

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from . import inference_boundary as _r3


# Unchanged source objects/helpers remain single-source and retain their existing
# validation semantics.
StateComponentRef = _r3.StateComponentRef
OmissionRecord = _r3.OmissionRecord
VeraStateComposition = _r3.VeraStateComposition
InvocationRecord = _r3.InvocationRecord
CausalGenerationReceipt = _r3.CausalGenerationReceipt
canonical_digest = _r3.canonical_digest
compose_state = _r3.compose_state
build_causal_receipt = _r3.build_causal_receipt


def _require_digest(value: str, label: str) -> str:
    return _r3._require_digest(value, label)


def _require_text(value: Any, label: str) -> str:
    return _r3._require_text(value, label)


def _admitted_state_material(
    *,
    subject: str,
    composition_digest: str,
    admission_receipt_digest: str,
    admitted_components: tuple[StateComponentRef, ...],
    omissions: tuple[OmissionRecord, ...],
    forbidden_domains: frozenset[str],
    admitted_disclosure_scope: str,
    admission_currentness_basis: str,
    admission_epoch_or_lease: str,
) -> dict[str, Any]:
    return {
        "subject": subject,
        "composition_digest": composition_digest,
        "admission_receipt_digest": admission_receipt_digest,
        "admitted_components": [
            item.digest_material()
            for item in sorted(admitted_components, key=lambda item: item.component_id)
        ],
        "omissions": [
            item.digest_material()
            for item in sorted(omissions, key=lambda item: item.component_id)
        ],
        "forbidden_domains": sorted(forbidden_domains),
        "admitted_disclosure_scope": admitted_disclosure_scope,
        "admission_currentness_basis": admission_currentness_basis,
        "admission_epoch_or_lease": admission_epoch_or_lease,
    }


@dataclass(frozen=True)
class AdmittedVeraState:
    subject: str
    composition_digest: str
    admission_receipt_digest: str
    admitted_components: tuple[StateComponentRef, ...]
    omissions: tuple[OmissionRecord, ...]
    forbidden_domains: frozenset[str]
    admitted_disclosure_scope: str
    admission_currentness_basis: str
    admission_epoch_or_lease: str
    admitted_at: str
    admitted_state_digest: str = ""

    def __post_init__(self) -> None:
        _require_text(self.subject, "subject")
        _require_digest(self.composition_digest, "composition_digest")
        _require_digest(self.admission_receipt_digest, "admission_receipt_digest")
        _require_text(self.admitted_disclosure_scope, "admitted_disclosure_scope")
        _require_text(self.admission_currentness_basis, "admission_currentness_basis")
        _require_text(self.admission_epoch_or_lease, "admission_epoch_or_lease")
        expected = canonical_digest(_admitted_state_material(
            subject=self.subject,
            composition_digest=self.composition_digest,
            admission_receipt_digest=self.admission_receipt_digest,
            admitted_components=self.admitted_components,
            omissions=self.omissions,
            forbidden_domains=self.forbidden_domains,
            admitted_disclosure_scope=self.admitted_disclosure_scope,
            admission_currentness_basis=self.admission_currentness_basis,
            admission_epoch_or_lease=self.admission_epoch_or_lease,
        ))
        if self.admitted_state_digest:
            supplied = _require_digest(self.admitted_state_digest, "admitted_state_digest")
            if supplied != expected:
                raise ValueError("admitted_state_digest does not bind the exact admission result")
        object.__setattr__(self, "admitted_state_digest", expected)


def bind_admitted_state(
    composition: VeraStateComposition, *, admission_receipt_digest: str,
    admitted_component_ids: set[str] | frozenset[str],
    mandatory_component_ids: set[str] | frozenset[str], target_egress_scope: str,
    forbidden_domains: set[str] | frozenset[str], admission_currentness_basis: str,
    admission_epoch_or_lease: str, admitted_at: str,
) -> AdmittedVeraState:
    receipt_digest = _require_digest(admission_receipt_digest, "admission_receipt_digest")
    _require_text(target_egress_scope, "target_egress_scope")
    _require_text(admission_currentness_basis, "admission_currentness_basis")
    _require_text(admission_epoch_or_lease, "admission_epoch_or_lease")

    included = {item.component_id: item for item in composition.components}
    omitted = {item.component_id: item for item in composition.omissions}
    admitted_ids = set(admitted_component_ids)
    caller_mandatory = set(mandatory_component_ids)
    source_mandatory = {
        item.component_id
        for item in composition.components
        if item.requirement_class == "MANDATORY"
    }
    # Caller policy may strengthen the source declaration but cannot weaken it.
    mandatory_ids = source_mandatory | caller_mandatory

    unknown = admitted_ids - set(included)
    if unknown:
        raise ValueError(f"admitted component ids are not in composition: {sorted(unknown)!r}")

    missing_mandatory = mandatory_ids - admitted_ids
    if missing_mandatory:
        if missing_mandatory & set(omitted):
            raise ValueError("mandatory component cannot be satisfied by optional omission")
        raise ValueError(f"mandatory component missing from admission: {sorted(missing_mandatory)!r}")

    selected = tuple(item for item in composition.components if item.component_id in admitted_ids)
    for item in selected:
        if target_egress_scope not in item.allowed_egress_scopes:
            raise ValueError(
                f"target egress scope {target_egress_scope!r} is not explicitly allowed for {item.component_id}"
            )

    return AdmittedVeraState(
        subject=composition.subject,
        composition_digest=composition.composition_digest,
        admission_receipt_digest=receipt_digest,
        admitted_components=selected,
        omissions=composition.omissions,
        forbidden_domains=frozenset(forbidden_domains),
        admitted_disclosure_scope=target_egress_scope,
        admission_currentness_basis=admission_currentness_basis,
        admission_epoch_or_lease=admission_epoch_or_lease,
        admitted_at=admitted_at,
    )


@dataclass(frozen=True)
class CapabilityBinding:
    host_identity: str
    host_revision: str
    host_generation: str
    target_provider_or_host: str
    target_egress_scope: str
    model_identity: str
    model_revision: str
    adapter_identity: str
    adapter_revision: str
    selected_backend: str
    supported_projection_backends: frozenset[str]
    backend_constraints: dict[str, Any]
    admitted_state_digest: str
    capability_digest: str
    bound_at: str


@dataclass(frozen=True)
class ProjectionEnvelope:
    admitted_state_digest: str
    capability_binding_digest: str
    projection_backend: str
    projection_digest: str
    projection_material: dict[str, Any]
    target_egress_scope: str
    binding_class: str
    causal_role: str
    projected_at: str


def bind_capability(
    admitted: AdmittedVeraState, *, host_identity: str, host_revision: str,
    host_generation: str, target_provider_or_host: str, target_egress_scope: str,
    model_identity: str, model_revision: str, adapter_identity: str,
    adapter_revision: str, requested_backend: str,
    supported_projection_backends: set[str] | frozenset[str],
    backend_constraints: dict[str, Any], bound_at: str,
) -> CapabilityBinding:
    for label, value in {
        "host_identity": host_identity,
        "host_revision": host_revision,
        "host_generation": host_generation,
        "target_provider_or_host": target_provider_or_host,
        "target_egress_scope": target_egress_scope,
        "model_identity": model_identity,
        "model_revision": model_revision,
        "adapter_identity": adapter_identity,
        "adapter_revision": adapter_revision,
        "requested_backend": requested_backend,
        "bound_at": bound_at,
    }.items():
        _require_text(value, label)

    supported = frozenset(supported_projection_backends)
    if requested_backend not in supported:
        raise ValueError(f"requested backend {requested_backend!r} is not supported by exact capability binding")
    if target_egress_scope != admitted.admitted_disclosure_scope:
        raise ValueError("capability target egress would broaden or change admitted egress scope")
    if not isinstance(backend_constraints, dict):
        raise ValueError("backend_constraints must be a JSON-safe mapping")

    material = {
        "host_identity": host_identity,
        "host_revision": host_revision,
        "host_generation": host_generation,
        "target_provider_or_host": target_provider_or_host,
        "target_egress_scope": target_egress_scope,
        "model_identity": model_identity,
        "model_revision": model_revision,
        "adapter_identity": adapter_identity,
        "adapter_revision": adapter_revision,
        "selected_backend": requested_backend,
        "supported_projection_backends": sorted(supported),
        "backend_constraints": backend_constraints,
        "admitted_state_digest": admitted.admitted_state_digest,
    }
    return CapabilityBinding(
        host_identity=host_identity,
        host_revision=host_revision,
        host_generation=host_generation,
        target_provider_or_host=target_provider_or_host,
        target_egress_scope=target_egress_scope,
        model_identity=model_identity,
        model_revision=model_revision,
        adapter_identity=adapter_identity,
        adapter_revision=adapter_revision,
        selected_backend=requested_backend,
        supported_projection_backends=supported,
        backend_constraints=dict(backend_constraints),
        admitted_state_digest=admitted.admitted_state_digest,
        capability_digest=canonical_digest(material),
        bound_at=bound_at,
    )


def project_text_context(
    admitted: AdmittedVeraState, capability: CapabilityBinding, *,
    projected_at: str = "UNSPECIFIED",
) -> ProjectionEnvelope:
    if capability.admitted_state_digest != admitted.admitted_state_digest:
        raise ValueError("capability/admitted-state digest mismatch")

    # Reuse the established R3 projection firewall/materialization logic only
    # after the repaired admission binding has been checked.
    legacy_capability = _r3.CapabilityBinding(
        host_identity=capability.host_identity,
        host_revision=capability.host_revision,
        host_generation=capability.host_generation,
        target_provider_or_host=capability.target_provider_or_host,
        target_egress_scope=capability.target_egress_scope,
        model_identity=capability.model_identity,
        model_revision=capability.model_revision,
        adapter_identity=capability.adapter_identity,
        adapter_revision=capability.adapter_revision,
        selected_backend=capability.selected_backend,
        supported_projection_backends=capability.supported_projection_backends,
        backend_constraints=capability.backend_constraints,
        capability_digest=capability.capability_digest,
        bound_at=capability.bound_at,
    )
    legacy_admitted = _r3.AdmittedVeraState(
        subject=admitted.subject,
        composition_digest=admitted.composition_digest,
        admission_receipt_digest=admitted.admission_receipt_digest,
        admitted_components=admitted.admitted_components,
        omissions=admitted.omissions,
        forbidden_domains=admitted.forbidden_domains,
        admitted_disclosure_scope=admitted.admitted_disclosure_scope,
        admission_currentness_basis=admitted.admission_currentness_basis,
        admission_epoch_or_lease=admitted.admission_epoch_or_lease,
        admitted_at=admitted.admitted_at,
    )
    legacy_projection = _r3.project_text_context(
        legacy_admitted, legacy_capability, projected_at=projected_at
    )
    material = dict(legacy_projection.projection_material)
    material["admitted_state_digest"] = admitted.admitted_state_digest
    return ProjectionEnvelope(
        admitted_state_digest=admitted.admitted_state_digest,
        capability_binding_digest=capability.capability_digest,
        projection_backend=legacy_projection.projection_backend,
        projection_digest=canonical_digest(material),
        projection_material=material,
        target_egress_scope=legacy_projection.target_egress_scope,
        binding_class=legacy_projection.binding_class,
        causal_role=legacy_projection.causal_role,
        projected_at=legacy_projection.projected_at,
    )


class InvocationFrontier(_r3.InvocationFrontier):
    """R3 invocation frontier with exact admission-result binding repaired."""

    def reserve(
        self, *, generation_id: str, admitted: AdmittedVeraState,
        capability: CapabilityBinding, projection: ProjectionEnvelope,
        request_material_digest: str, currentness_mode: str,
        revalidate: Callable[[], bool], reserved_at: str,
        retry_of_generation_id: str | None = None,
    ) -> InvocationRecord:
        if capability.admitted_state_digest != admitted.admitted_state_digest:
            raise ValueError("capability/admitted-state digest mismatch")
        if projection.admitted_state_digest != admitted.admitted_state_digest:
            raise ValueError("projection/admitted-state digest mismatch")
        if projection.capability_binding_digest != capability.capability_digest:
            raise ValueError("projection/capability binding mismatch")

        legacy_admitted = _r3.AdmittedVeraState(
            subject=admitted.subject,
            composition_digest=admitted.composition_digest,
            admission_receipt_digest=admitted.admission_receipt_digest,
            admitted_components=admitted.admitted_components,
            omissions=admitted.omissions,
            forbidden_domains=admitted.forbidden_domains,
            admitted_disclosure_scope=admitted.admitted_disclosure_scope,
            admission_currentness_basis=admitted.admission_currentness_basis,
            admission_epoch_or_lease=admitted.admission_epoch_or_lease,
            admitted_at=admitted.admitted_at,
        )
        legacy_capability = _r3.CapabilityBinding(
            host_identity=capability.host_identity,
            host_revision=capability.host_revision,
            host_generation=capability.host_generation,
            target_provider_or_host=capability.target_provider_or_host,
            target_egress_scope=capability.target_egress_scope,
            model_identity=capability.model_identity,
            model_revision=capability.model_revision,
            adapter_identity=capability.adapter_identity,
            adapter_revision=capability.adapter_revision,
            selected_backend=capability.selected_backend,
            supported_projection_backends=capability.supported_projection_backends,
            backend_constraints=capability.backend_constraints,
            capability_digest=capability.capability_digest,
            bound_at=capability.bound_at,
        )
        # The legacy reserve path checks pre-admission composition identity.  We
        # have already performed the stronger exact admission-result equality
        # above; this adapter value exists only so the inherited ledger/state
        # transition machinery can be reused without weakening the new gate.
        legacy_projection = _r3.ProjectionEnvelope(
            admitted_state_digest=admitted.composition_digest,
            capability_binding_digest=projection.capability_binding_digest,
            projection_backend=projection.projection_backend,
            projection_digest=projection.projection_digest,
            projection_material=projection.projection_material,
            target_egress_scope=projection.target_egress_scope,
            binding_class=projection.binding_class,
            causal_role=projection.causal_role,
            projected_at=projection.projected_at,
        )
        return super().reserve(
            generation_id=generation_id,
            admitted=legacy_admitted,
            capability=legacy_capability,
            projection=legacy_projection,
            request_material_digest=request_material_digest,
            currentness_mode=currentness_mode,
            revalidate=revalidate,
            reserved_at=reserved_at,
            retry_of_generation_id=retry_of_generation_id,
        )


__all__ = [
    "StateComponentRef",
    "OmissionRecord",
    "VeraStateComposition",
    "AdmittedVeraState",
    "CapabilityBinding",
    "ProjectionEnvelope",
    "InvocationRecord",
    "InvocationFrontier",
    "CausalGenerationReceipt",
    "canonical_digest",
    "compose_state",
    "bind_admitted_state",
    "bind_capability",
    "project_text_context",
    "build_causal_receipt",
]
