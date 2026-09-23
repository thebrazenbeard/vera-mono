from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from threading import RLock
from typing import Any, Callable, Iterable


_REQUIREMENT_CLASSES = {"MANDATORY", "OPTIONAL"}
_FORBIDDEN_PROJECTION_INPUT_KEYS = frozenset({
    "target_behavior", "desired_response", "target_phrase", "expected_answer",
    "expected_output", "requested_emotional_display",
})
_STRUCTURALLY_FORBIDDEN_PROJECTION_DOMAINS = frozenset({
    "truth", "factual_confidence_authority", "consent", "authorization",
    "protected_effect_authority", "identity_admission",
    "autobiographical_memory_admission", "permanent_preference",
    "relationship_status", "provider_currentness", "installation_current_route",
    "behavioral_qualification", "phenomenology",
})
_CURRENTNESS_MODES = {"ATOMIC_START_SNAPSHOT", "LEASE_THROUGH_SUBMISSION"}
_LEDGER_STATES = {
    "RESERVED", "SUBMISSION_INTENT", "SUBMITTED", "ACKNOWLEDGED",
    "RESPONSE_BOUND", "FAILED", "CANCELLED", "OUTCOME_UNKNOWN",
}
_TERMINAL_STATES = {"RESPONSE_BOUND", "FAILED", "CANCELLED"}


def _canonical_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be canonical JSON-safe") from exc
    return encoded.encode("utf-8")


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{label} must be a 64-character SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be hexadecimal") from exc
    return value.lower()


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be non-empty")
    return value


def _normalize_domain_id(value: str) -> str:
    _require_text(value, "domain_id")
    mapped = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in mapped.split("_") if part)


@dataclass(frozen=True)
class StateComponentRef:
    component_id: str
    domain_id: str
    source_locator: str
    source_revision: str
    component_generation: str
    content_digest: str
    observed_at: str
    currentness_basis: str
    supersession_state: str
    conflict_state: str
    privacy_classification: str
    allowed_egress_scopes: frozenset[str]
    disclosure_source: str
    disclosure_generation: str
    requirement_class: str
    payload: Any | None = None
    payload_ref: str | None = None

    def __post_init__(self) -> None:
        for label in (
            "component_id", "domain_id", "source_locator", "source_revision",
            "component_generation", "observed_at", "currentness_basis",
            "supersession_state", "conflict_state", "privacy_classification",
            "disclosure_source", "disclosure_generation",
        ):
            _require_text(getattr(self, label), label)
        if self.requirement_class not in _REQUIREMENT_CLASSES:
            raise ValueError("requirement_class must be MANDATORY or OPTIONAL")
        if not isinstance(self.allowed_egress_scopes, frozenset) or not self.allowed_egress_scopes:
            raise ValueError("allowed_egress_scopes must be a non-empty frozenset")
        if not all(isinstance(item, str) and item for item in self.allowed_egress_scopes):
            raise ValueError("allowed_egress_scopes entries must be non-empty strings")
        _require_digest(self.content_digest, "content_digest")
        has_payload = self.payload is not None
        has_pointer = self.payload_ref is not None
        if has_payload == has_pointer:
            raise ValueError("component requires exactly one of payload or payload_ref")
        if has_pointer:
            _require_text(self.payload_ref, "payload_ref")
        if has_payload and canonical_digest(self.payload) != self.content_digest.lower():
            raise ValueError("inline payload digest does not match content_digest")

    def digest_material(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "component_id": self.component_id,
            "domain_id": self.domain_id,
            "source_locator": self.source_locator,
            "source_revision": self.source_revision,
            "component_generation": self.component_generation,
            "content_digest": self.content_digest.lower(),
            "observed_at": self.observed_at,
            "currentness_basis": self.currentness_basis,
            "supersession_state": self.supersession_state,
            "conflict_state": self.conflict_state,
            "privacy_classification": self.privacy_classification,
            "allowed_egress_scopes": sorted(self.allowed_egress_scopes),
            "disclosure_source": self.disclosure_source,
            "disclosure_generation": self.disclosure_generation,
            "requirement_class": self.requirement_class,
        }
        if self.payload is not None:
            result["payload"] = self.payload
        else:
            result["payload_ref"] = self.payload_ref
        return result


@dataclass(frozen=True)
class OmissionRecord:
    component_id: str
    domain_id: str
    reason: str
    observed_at: str
    evidence_ref: str
    requirement_class: str = "OPTIONAL"

    def __post_init__(self) -> None:
        if self.requirement_class != "OPTIONAL":
            raise ValueError("only OPTIONAL components may be represented by an omission record")
        for label in ("component_id", "domain_id", "reason", "observed_at", "evidence_ref"):
            _require_text(getattr(self, label), label)

    def digest_material(self) -> dict[str, str]:
        return {
            "component_id": self.component_id, "domain_id": self.domain_id,
            "reason": self.reason, "observed_at": self.observed_at,
            "evidence_ref": self.evidence_ref, "requirement_class": self.requirement_class,
        }


@dataclass(frozen=True)
class VeraStateComposition:
    composition_id: str
    subject: str
    components: tuple[StateComponentRef, ...]
    component_generation_vector: tuple[tuple[str, str], ...]
    composition_digest: str
    composed_at: str
    composition_policy_revision: str
    omissions: tuple[OmissionRecord, ...]


def _admitted_state_material(
    *, subject: str, composition_digest: str, composition_policy_revision: str,
    admission_receipt_digest: str, admitted_components: tuple[StateComponentRef, ...],
    omissions: tuple[OmissionRecord, ...], forbidden_domains: frozenset[str],
    admitted_disclosure_scope: str, admission_currentness_basis: str,
    admission_epoch_or_lease: str, admitted_at: str,
) -> dict[str, Any]:
    return {
        "schema": "VERA_ADMITTED_STATE_V1",
        "subject": subject,
        "composition_digest": composition_digest,
        "composition_policy_revision": composition_policy_revision,
        "admission_receipt_digest": admission_receipt_digest,
        "admitted_components": [item.digest_material() for item in admitted_components],
        "omissions": [item.digest_material() for item in omissions],
        "forbidden_domains": sorted(forbidden_domains),
        "admitted_disclosure_scope": admitted_disclosure_scope,
        "admission_currentness_basis": admission_currentness_basis,
        "admission_epoch_or_lease": admission_epoch_or_lease,
        "admitted_at": admitted_at,
    }


@dataclass(frozen=True)
class AdmittedVeraState:
    subject: str
    composition_digest: str
    composition_policy_revision: str
    admitted_state_digest: str
    admission_receipt_digest: str
    admitted_components: tuple[StateComponentRef, ...]
    omissions: tuple[OmissionRecord, ...]
    forbidden_domains: frozenset[str]
    admitted_disclosure_scope: str
    admission_currentness_basis: str
    admission_epoch_or_lease: str
    admitted_at: str

    def __post_init__(self) -> None:
        _require_text(self.subject, "subject")
        _require_digest(self.composition_digest, "composition_digest")
        _require_text(self.composition_policy_revision, "composition_policy_revision")
        _require_digest(self.admission_receipt_digest, "admission_receipt_digest")
        _require_digest(self.admitted_state_digest, "admitted_state_digest")
        expected = canonical_digest(_admitted_state_material(
            subject=self.subject,
            composition_digest=self.composition_digest,
            composition_policy_revision=self.composition_policy_revision,
            admission_receipt_digest=self.admission_receipt_digest,
            admitted_components=self.admitted_components,
            omissions=self.omissions,
            forbidden_domains=self.forbidden_domains,
            admitted_disclosure_scope=self.admitted_disclosure_scope,
            admission_currentness_basis=self.admission_currentness_basis,
            admission_epoch_or_lease=self.admission_epoch_or_lease,
            admitted_at=self.admitted_at,
        ))
        if expected != self.admitted_state_digest.lower():
            raise ValueError("admitted_state_digest does not match admitted state material")


def compose_state(
    *, subject: str, components: Iterable[StateComponentRef],
    omissions: Iterable[OmissionRecord], policy_revision: str,
    composed_at: str = "UNSPECIFIED",
) -> VeraStateComposition:
    _require_text(subject, "subject")
    _require_text(policy_revision, "policy_revision")
    component_tuple = tuple(sorted(tuple(components), key=lambda item: item.component_id))
    omission_tuple = tuple(sorted(tuple(omissions), key=lambda item: item.component_id))
    component_ids = [item.component_id for item in component_tuple]
    omission_ids = [item.component_id for item in omission_tuple]
    if len(component_ids) != len(set(component_ids)):
        raise ValueError("duplicate component_id in composition")
    if len(omission_ids) != len(set(omission_ids)):
        raise ValueError("duplicate omission component_id in composition")
    if set(component_ids) & set(omission_ids):
        raise ValueError("component cannot be both included and omitted")
    for item in component_tuple:
        if item.supersession_state != "CURRENT_OBSERVATION":
            raise ValueError(f"component {item.component_id} is not current")
        if item.conflict_state != "NONE":
            raise ValueError(f"component {item.component_id} has unresolved conflict")
    vector = tuple((item.component_id, item.component_generation) for item in component_tuple)
    digest_material = {
        "subject": subject,
        "components": [item.digest_material() for item in component_tuple],
        "component_generation_vector": [list(item) for item in vector],
        "omissions": [item.digest_material() for item in omission_tuple],
        "composition_policy_revision": policy_revision,
    }
    digest = canonical_digest(digest_material)
    return VeraStateComposition(
        composition_id=f"sha256:{digest}", subject=subject, components=component_tuple,
        component_generation_vector=vector, composition_digest=digest,
        composed_at=composed_at, composition_policy_revision=policy_revision,
        omissions=omission_tuple,
    )


def bind_admitted_state(
    composition: VeraStateComposition, *, admission_receipt_digest: str,
    admitted_component_ids: set[str] | frozenset[str],
    mandatory_component_ids: set[str] | frozenset[str], target_egress_scope: str,
    forbidden_domains: set[str] | frozenset[str], admission_currentness_basis: str,
    admission_epoch_or_lease: str, admitted_at: str,
) -> AdmittedVeraState:
    _require_digest(admission_receipt_digest, "admission_receipt_digest")
    _require_text(target_egress_scope, "target_egress_scope")
    _require_text(admission_currentness_basis, "admission_currentness_basis")
    _require_text(admission_epoch_or_lease, "admission_epoch_or_lease")
    included = {item.component_id: item for item in composition.components}
    omitted = {item.component_id: item for item in composition.omissions}
    admitted_ids = set(admitted_component_ids)
    mandatory_ids = set(mandatory_component_ids)
    declared_mandatory_ids = {
        item.component_id for item in composition.components
        if item.requirement_class == "MANDATORY"
    }
    downgraded_mandatory = declared_mandatory_ids - mandatory_ids
    if downgraded_mandatory:
        raise ValueError(
            "mandatory component requirement_class is missing from admission policy: "
            f"{sorted(downgraded_mandatory)!r}"
        )
    upgraded_optional = {
        component_id for component_id in mandatory_ids & set(included)
        if included[component_id].requirement_class != "MANDATORY"
    }
    if upgraded_optional:
        raise ValueError(
            "optional component requirement_class cannot be upgraded by admission policy: "
            f"{sorted(upgraded_optional)!r}"
        )
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
    effective_forbidden_domains = (
        frozenset(forbidden_domains) | _STRUCTURALLY_FORBIDDEN_PROJECTION_DOMAINS
    )
    admitted_state_digest = canonical_digest(_admitted_state_material(
        subject=composition.subject,
        composition_digest=composition.composition_digest,
        composition_policy_revision=composition.composition_policy_revision,
        admission_receipt_digest=admission_receipt_digest.lower(),
        admitted_components=selected,
        omissions=composition.omissions,
        forbidden_domains=effective_forbidden_domains,
        admitted_disclosure_scope=target_egress_scope,
        admission_currentness_basis=admission_currentness_basis,
        admission_epoch_or_lease=admission_epoch_or_lease,
        admitted_at=admitted_at,
    ))
    return AdmittedVeraState(
        subject=composition.subject, composition_digest=composition.composition_digest,
        composition_policy_revision=composition.composition_policy_revision,
        admitted_state_digest=admitted_state_digest,
        admission_receipt_digest=admission_receipt_digest.lower(), admitted_components=selected,
        omissions=composition.omissions,
        forbidden_domains=effective_forbidden_domains,
        admitted_disclosure_scope=target_egress_scope,
        admission_currentness_basis=admission_currentness_basis,
        admission_epoch_or_lease=admission_epoch_or_lease, admitted_at=admitted_at,
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
        "host_identity": host_identity, "host_revision": host_revision,
        "host_generation": host_generation, "target_provider_or_host": target_provider_or_host,
        "target_egress_scope": target_egress_scope, "model_identity": model_identity,
        "model_revision": model_revision, "adapter_identity": adapter_identity,
        "adapter_revision": adapter_revision, "requested_backend": requested_backend,
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
        "host_identity": host_identity, "host_revision": host_revision,
        "host_generation": host_generation, "target_provider_or_host": target_provider_or_host,
        "target_egress_scope": target_egress_scope, "model_identity": model_identity,
        "model_revision": model_revision, "adapter_identity": adapter_identity,
        "adapter_revision": adapter_revision, "selected_backend": requested_backend,
        "supported_projection_backends": sorted(supported),
        "backend_constraints": backend_constraints,
        "admitted_state_digest": admitted.admitted_state_digest,
    }
    return CapabilityBinding(
        host_identity=host_identity, host_revision=host_revision, host_generation=host_generation,
        target_provider_or_host=target_provider_or_host, target_egress_scope=target_egress_scope,
        model_identity=model_identity, model_revision=model_revision,
        adapter_identity=adapter_identity, adapter_revision=adapter_revision,
        selected_backend=requested_backend, supported_projection_backends=supported,
        backend_constraints=dict(backend_constraints),
        admitted_state_digest=admitted.admitted_state_digest,
        capability_digest=canonical_digest(material), bound_at=bound_at,
    )


def _find_forbidden_projection_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key in _FORBIDDEN_PROJECTION_INPUT_KEYS:
                return key
            found = _find_forbidden_projection_key(child)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for child in value:
            found = _find_forbidden_projection_key(child)
            if found is not None:
                return found
    return None


def project_text_context(
    admitted: AdmittedVeraState, capability: CapabilityBinding, *,
    projected_at: str = "UNSPECIFIED",
) -> ProjectionEnvelope:
    if capability.selected_backend != "TEXT_CONTEXT_V1":
        raise ValueError("TEXT_CONTEXT_V1 projection requires an exact TEXT_CONTEXT_V1 capability binding")
    if capability.target_egress_scope != admitted.admitted_disclosure_scope:
        raise ValueError("projection egress does not match admitted disclosure scope")
    if capability.admitted_state_digest != admitted.admitted_state_digest:
        raise ValueError("capability/admitted-state digest mismatch")
    components: list[dict[str, Any]] = []
    for component in admitted.admitted_components:
        normalized_domain = _normalize_domain_id(component.domain_id)
        if (
            component.domain_id in admitted.forbidden_domains
            or normalized_domain in _STRUCTURALLY_FORBIDDEN_PROJECTION_DOMAINS
        ):
            raise ValueError(f"forbidden projection domain: {component.domain_id}")
        if capability.target_egress_scope not in component.allowed_egress_scopes:
            raise ValueError(f"projection egress is not allowed for {component.component_id}")
        if component.payload is not None:
            forbidden_key = _find_forbidden_projection_key(component.payload)
            if forbidden_key is not None:
                raise ValueError(f"forbidden projection input key: {forbidden_key}")
            state_material: dict[str, Any] = {"payload": component.payload}
        else:
            state_material = {"payload_ref": component.payload_ref, "content_digest": component.content_digest.lower()}
        components.append({
            "component_id": component.component_id, "domain_id": component.domain_id,
            "source_revision": component.source_revision,
            "component_generation": component.component_generation, **state_material,
        })
    projection_material: dict[str, Any] = {
        "schema": "VERA_TEXT_CONTEXT_V1", "subject": admitted.subject,
        "composition_digest": admitted.composition_digest,
        "admitted_state_digest": admitted.admitted_state_digest,
        "admission_receipt_digest": admitted.admission_receipt_digest,
        "host_identity": capability.host_identity, "host_revision": capability.host_revision,
        "host_generation": capability.host_generation, "model_identity": capability.model_identity,
        "model_revision": capability.model_revision, "adapter_identity": capability.adapter_identity,
        "adapter_revision": capability.adapter_revision,
        "target_egress_scope": capability.target_egress_scope,
        "components": components,
        "omissions": [item.digest_material() for item in admitted.omissions],
        "claim_ceiling": "PROMPT_REQUEST_CONDITIONING_ONLY",
    }
    maximum = capability.backend_constraints.get("max_chars")
    if maximum is not None:
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0:
            raise ValueError("TEXT_CONTEXT_V1 max_chars must be a positive integer")
        if len(_canonical_bytes(projection_material).decode("utf-8")) > maximum:
            raise ValueError("TEXT_CONTEXT_V1 projection exceeds max_chars capability")
    return ProjectionEnvelope(
        admitted_state_digest=admitted.admitted_state_digest,
        capability_binding_digest=capability.capability_digest,
        projection_backend="TEXT_CONTEXT_V1",
        projection_digest=canonical_digest(projection_material),
        projection_material=projection_material,
        target_egress_scope=capability.target_egress_scope,
        binding_class="PROMPT_BOUND", causal_role="INSTRUCTION_CONDITIONED",
        projected_at=projected_at,
    )


@dataclass(frozen=True)
class InvocationRecord:
    generation_id: str
    host_generation: str
    subject: str
    composition_digest: str
    admitted_state_digest: str
    admission_receipt_digest: str
    omission_receipt_digests: tuple[str, ...]
    capability_binding_digest: str
    projection_digest: str
    request_material_digest: str
    target_provider_or_host: str
    target_egress_scope: str
    model_identity: str
    model_revision: str
    adapter_identity: str
    adapter_revision: str
    projection_backend: str
    binding_class: str
    causal_role: str
    invocation_currentness_mode: str
    reserved_at: str
    ledger_state: str
    retry_of_generation_id: str | None = None
    provider_idempotency_key: str | None = None
    provider_request_id: str | None = None
    provider_ack_evidence: str | None = None
    response_or_run_id: str | None = None
    response_binding_evidence: str | None = None
    failure_evidence: str | None = None
    transport_retry_count: int = 0
    last_observed_at: str | None = None

    def __post_init__(self) -> None:
        if self.ledger_state not in _LEDGER_STATES:
            raise ValueError(f"unsupported invocation ledger state: {self.ledger_state}")


@dataclass(frozen=True)
class CausalGenerationReceipt:
    receipt_id: str
    generation_id: str
    subject: str
    composition_digest: str
    admitted_state_digest: str
    admission_receipt_digest: str
    omission_receipt_digests: tuple[str, ...]
    capability_binding_digest: str
    projection_digest: str
    request_material_digest: str
    target_provider_or_host: str
    target_egress_scope: str
    model_identity: str
    model_revision: str
    adapter_identity: str
    adapter_revision: str
    projection_backend: str
    binding_class: str
    causal_role: str
    evidence_level: str
    event_observed_at: str
    provider_request_id: str | None
    provider_ack_evidence: str | None
    response_or_run_id: str | None
    response_binding_evidence: str | None
    ledger_state: str
    claim_ceiling: tuple[str, ...]


class InvocationFrontier:
    """Provider-neutral host-generation ledger semantics.

    A concrete inference host owns the shared frontier instance and persistence.
    External submission is forbidden unless durable transition persistence is
    configured. This class itself performs no provider I/O and claims no effect.
    """

    def __init__(
        self, *, host_generation: str, durable: bool,
        persist_transition: Callable[[InvocationRecord], None] | None = None,
    ) -> None:
        _require_text(host_generation, "host_generation")
        if durable and persist_transition is None:
            raise ValueError("durable invocation frontier requires a transition persistence callback")
        self.host_generation = host_generation
        self.durable = bool(durable)
        self._persist_transition = persist_transition
        self._records: dict[str, InvocationRecord] = {}
        self._lock = RLock()

    def _persist_then_store(self, record: InvocationRecord) -> InvocationRecord:
        if self._persist_transition is not None:
            self._persist_transition(record)
        self._records[record.generation_id] = record
        return record

    def _require_record(self, generation_id: str) -> InvocationRecord:
        record = self._records.get(generation_id)
        if record is None:
            raise ValueError(f"unknown generation_id: {generation_id}")
        return record

    def get(self, generation_id: str) -> InvocationRecord | None:
        with self._lock:
            return self._records.get(generation_id)

    def reserve(
        self, *, generation_id: str, admitted: AdmittedVeraState,
        capability: CapabilityBinding, projection: ProjectionEnvelope,
        request_material_digest: str, currentness_mode: str,
        revalidate: Callable[[], bool], reserved_at: str,
        retry_of_generation_id: str | None = None,
    ) -> InvocationRecord:
        _require_text(generation_id, "generation_id")
        if currentness_mode not in _CURRENTNESS_MODES:
            raise ValueError("unsupported invocation currentness mode")
        request_digest = _require_digest(request_material_digest, "request_material_digest")
        if capability.host_generation != self.host_generation:
            raise ValueError("capability binding host generation does not match invocation frontier")
        if capability.admitted_state_digest != admitted.admitted_state_digest:
            raise ValueError("capability/admitted-state digest mismatch")
        if projection.admitted_state_digest != admitted.admitted_state_digest:
            raise ValueError("projection/admitted-state digest mismatch")
        if projection.capability_binding_digest != capability.capability_digest:
            raise ValueError("projection/capability binding mismatch")
        with self._lock:
            if generation_id in self._records:
                raise ValueError("generation_id is single-use and already reserved")
            if retry_of_generation_id is not None:
                if generation_id == retry_of_generation_id:
                    raise ValueError("semantic retry requires a new generation_id")
                prior = self._require_record(retry_of_generation_id)
                if prior.ledger_state == "OUTCOME_UNKNOWN":
                    raise ValueError("semantic retry is blocked while prior outcome is unknown")
                if prior.ledger_state != "FAILED":
                    raise ValueError("semantic retry requires proved terminal failure")
            try:
                current = bool(revalidate())
            except Exception as exc:
                raise ValueError("pre-call revalidation raised and reservation was not created") from exc
            if not current:
                raise ValueError("pre-call revalidation failed; reservation was not created")
            record = InvocationRecord(
                generation_id=generation_id, host_generation=self.host_generation,
                subject=admitted.subject, composition_digest=admitted.composition_digest,
                admitted_state_digest=admitted.admitted_state_digest,
                admission_receipt_digest=admitted.admission_receipt_digest,
                omission_receipt_digests=tuple(canonical_digest(item.digest_material()) for item in admitted.omissions),
                capability_binding_digest=capability.capability_digest,
                projection_digest=projection.projection_digest,
                request_material_digest=request_digest,
                target_provider_or_host=capability.target_provider_or_host,
                target_egress_scope=capability.target_egress_scope,
                model_identity=capability.model_identity, model_revision=capability.model_revision,
                adapter_identity=capability.adapter_identity, adapter_revision=capability.adapter_revision,
                projection_backend=projection.projection_backend, binding_class=projection.binding_class,
                causal_role=projection.causal_role, invocation_currentness_mode=currentness_mode,
                reserved_at=reserved_at, ledger_state="RESERVED",
                retry_of_generation_id=retry_of_generation_id, last_observed_at=reserved_at,
            )
            return self._persist_then_store(record)

    def submission_intent(
        self, generation_id: str, *, request_material_digest: str,
        provider_idempotency_key: str | None, intended_at: str, external: bool,
    ) -> InvocationRecord:
        digest = _require_digest(request_material_digest, "request_material_digest")
        with self._lock:
            record = self._require_record(generation_id)
            if record.ledger_state != "RESERVED":
                raise ValueError("submission intent requires RESERVED invocation state")
            if digest != record.request_material_digest:
                raise ValueError("submission-intent request digest mismatch")
            if external and not self.durable:
                raise ValueError("external submission requires durable write-ahead invocation frontier")
            if provider_idempotency_key is not None:
                _require_text(provider_idempotency_key, "provider_idempotency_key")
            return self._persist_then_store(replace(
                record, ledger_state="SUBMISSION_INTENT",
                provider_idempotency_key=provider_idempotency_key,
                last_observed_at=intended_at,
            ))

    def mark_submitted(
        self, generation_id: str, *, submitted_at: str,
        provider_request_id: str | None = None,
    ) -> InvocationRecord:
        with self._lock:
            record = self._require_record(generation_id)
            if record.ledger_state != "SUBMISSION_INTENT":
                raise ValueError("submission acknowledgement requires SUBMISSION_INTENT state")
            return self._persist_then_store(replace(
                record, ledger_state="SUBMITTED", provider_request_id=provider_request_id,
                last_observed_at=submitted_at,
            ))

    def acknowledge(
        self, generation_id: str, *, acknowledged_at: str,
        provider_ack_evidence: str,
    ) -> InvocationRecord:
        _require_text(provider_ack_evidence, "provider_ack_evidence")
        with self._lock:
            record = self._require_record(generation_id)
            if record.ledger_state != "SUBMITTED":
                raise ValueError("provider acknowledgement requires SUBMITTED state")
            return self._persist_then_store(replace(
                record, ledger_state="ACKNOWLEDGED",
                provider_ack_evidence=provider_ack_evidence,
                last_observed_at=acknowledged_at,
            ))

    def bind_response(
        self, generation_id: str, *, response_or_run_id: str,
        response_binding_evidence: str, bound_at: str,
    ) -> InvocationRecord:
        _require_text(response_or_run_id, "response_or_run_id")
        _require_text(response_binding_evidence, "response_binding_evidence")
        with self._lock:
            record = self._require_record(generation_id)
            if record.ledger_state != "ACKNOWLEDGED":
                raise ValueError("response binding requires PROVIDER_ACKNOWLEDGED state")
            return self._persist_then_store(replace(
                record, ledger_state="RESPONSE_BOUND",
                response_or_run_id=response_or_run_id,
                response_binding_evidence=response_binding_evidence,
                last_observed_at=bound_at,
            ))

    def recover_ambiguous(self, generation_id: str, *, observed_at: str) -> InvocationRecord:
        with self._lock:
            record = self._require_record(generation_id)
            if record.ledger_state != "SUBMISSION_INTENT":
                raise ValueError("ambiguous recovery requires unresolved SUBMISSION_INTENT")
            return self._persist_then_store(replace(
                record, ledger_state="OUTCOME_UNKNOWN", last_observed_at=observed_at,
            ))

    def mark_failed(
        self, generation_id: str, *, failed_at: str, failure_evidence: str,
    ) -> InvocationRecord:
        _require_text(failure_evidence, "failure_evidence")
        with self._lock:
            record = self._require_record(generation_id)
            if record.ledger_state in _TERMINAL_STATES:
                raise ValueError("terminal invocation state cannot be overwritten")
            if record.ledger_state == "OUTCOME_UNKNOWN":
                raise ValueError("OUTCOME_UNKNOWN must be reconciled before terminal failure is asserted")
            return self._persist_then_store(replace(
                record, ledger_state="FAILED", failure_evidence=failure_evidence,
                last_observed_at=failed_at,
            ))

    def authorize_transport_retry(
        self, generation_id: str, *, request_material_digest: str,
        provider_idempotency_key: str, provider_contract_idempotent: bool,
        observed_at: str,
    ) -> InvocationRecord:
        digest = _require_digest(request_material_digest, "request_material_digest")
        with self._lock:
            record = self._require_record(generation_id)
            if record.ledger_state != "OUTCOME_UNKNOWN":
                raise ValueError("same-generation transport retry requires OUTCOME_UNKNOWN reconciliation state")
            if provider_contract_idempotent is not True:
                raise ValueError("same-generation transport retry requires exact provider idempotency guarantee")
            if digest != record.request_material_digest:
                raise ValueError("same-generation transport retry request digest mismatch")
            if not provider_idempotency_key or provider_idempotency_key != record.provider_idempotency_key:
                raise ValueError("same-generation transport retry idempotency key mismatch")
            return self._persist_then_store(replace(
                record, ledger_state="SUBMISSION_INTENT",
                transport_retry_count=record.transport_retry_count + 1,
                last_observed_at=observed_at,
            ))


def build_causal_receipt(record: InvocationRecord, *, observed_at: str) -> CausalGenerationReceipt:
    evidence_level = {
        "RESERVED": "REQUEST_CONSTRUCTED", "SUBMISSION_INTENT": "REQUEST_CONSTRUCTED",
        "OUTCOME_UNKNOWN": "REQUEST_CONSTRUCTED", "FAILED": "REQUEST_CONSTRUCTED",
        "CANCELLED": "REQUEST_CONSTRUCTED", "SUBMITTED": "INVOCATION_SUBMITTED",
        "ACKNOWLEDGED": "PROVIDER_ACKNOWLEDGED", "RESPONSE_BOUND": "RESPONSE_BOUND",
    }[record.ledger_state]
    provider_request_id = record.provider_request_id if evidence_level != "REQUEST_CONSTRUCTED" else None
    provider_ack_evidence = record.provider_ack_evidence if evidence_level in {"PROVIDER_ACKNOWLEDGED", "RESPONSE_BOUND"} else None
    response_or_run_id = record.response_or_run_id if evidence_level == "RESPONSE_BOUND" else None
    response_binding_evidence = record.response_binding_evidence if evidence_level == "RESPONSE_BOUND" else None
    if evidence_level == "PROVIDER_ACKNOWLEDGED" and not provider_ack_evidence:
        raise ValueError("PROVIDER_ACKNOWLEDGED receipt requires acknowledgement evidence")
    if evidence_level == "RESPONSE_BOUND" and (not response_or_run_id or not response_binding_evidence):
        raise ValueError("RESPONSE_BOUND receipt requires exact response binding evidence")
    receipt_material = {
        "generation_id": record.generation_id, "ledger_state": record.ledger_state,
        "evidence_level": evidence_level, "composition_digest": record.composition_digest,
        "admitted_state_digest": record.admitted_state_digest,
        "capability_binding_digest": record.capability_binding_digest,
        "projection_digest": record.projection_digest,
        "request_material_digest": record.request_material_digest,
        "observed_at": observed_at, "provider_request_id": provider_request_id,
        "provider_ack_evidence": provider_ack_evidence,
        "response_or_run_id": response_or_run_id,
        "response_binding_evidence": response_binding_evidence,
    }
    return CausalGenerationReceipt(
        receipt_id=f"sha256:{canonical_digest(receipt_material)}",
        generation_id=record.generation_id, subject=record.subject,
        composition_digest=record.composition_digest,
        admitted_state_digest=record.admitted_state_digest,
        admission_receipt_digest=record.admission_receipt_digest,
        omission_receipt_digests=record.omission_receipt_digests,
        capability_binding_digest=record.capability_binding_digest,
        projection_digest=record.projection_digest,
        request_material_digest=record.request_material_digest,
        target_provider_or_host=record.target_provider_or_host,
        target_egress_scope=record.target_egress_scope,
        model_identity=record.model_identity, model_revision=record.model_revision,
        adapter_identity=record.adapter_identity, adapter_revision=record.adapter_revision,
        projection_backend=record.projection_backend, binding_class=record.binding_class,
        causal_role=record.causal_role, evidence_level=evidence_level,
        event_observed_at=observed_at, provider_request_id=provider_request_id,
        provider_ack_evidence=provider_ack_evidence, response_or_run_id=response_or_run_id,
        response_binding_evidence=response_binding_evidence,
        ledger_state=record.ledger_state,
        claim_ceiling=(
            "INSTALL_CURRENT_ROUTE_NOT_ESTABLISHED",
            "PROVIDER_CURRENTNESS_NOT_ESTABLISHED",
            "BEHAVIORAL_QUALIFICATION_NOT_ESTABLISHED",
            "PHENOMENOLOGY_UNRESOLVED",
        ),
    )
