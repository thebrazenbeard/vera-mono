"""Executable support for Vera Runtime Cohesion.

This package is operational support for the normative cohesion index/runtime
contract pair. Importing it performs no provider I/O and creates no authority.
Provider I/O occurs only when a runtime explicitly invokes registered adapters.

Public proposition admission is provider-strict. Lightweight policy fixtures use
only the explicitly named abstract evaluator. Affective execution and generic
planning application are separated: OV emits bounded modulation signals and the
Cohesion-owned bound integration port applies them without promoting signal
content to evidence, authority, memory admission, identity, relationship state,
or phenomenology.
"""

from .adapters import AdapterProbeResult, AdapterRegistry, AdapterRequest, ProviderAdapter
from .affect_cycle import AffectiveCycleResult, VeraAffectiveCycle
from .affect_host import AffectiveBindingError, VeraAffectiveRuntimeHost
from .affect_integration import AffectiveModulationAncestry, AffectiveModulationApplication
from .affect_integration_bound import (
    CohesionAffectiveIntegrationPort,
    IntegratedAffectivePlanningResult,
    validate_cohesion_affective_integration_cut,
)
from .affect_persistence import (
    PersistenceRecordError,
    build_affective_resume_token,
    build_atomic_commit_request,
    checkpoint_to_state_row,
    event_receipt_to_event_row,
    restore_host_from_state_row,
)
from .affect_provider_runtime import restore_current_affective_cycle
from .audit import ProjectionAuditResult, audit_registered_projections
from .evidence import ProviderEvidenceEnvelope, load_provider_fabric, validate_envelope
from .executor import (
    DomainExecutionResult,
    GoverningResolutionRecord,
    ProjectionExecutionResult,
    execute_domain_cycle,
    execute_projection_cycle,
)
from .failure import FailureEvaluationResult, evaluate_failure_signature, validate_failure_wiring
from . import inference_boundary_repaired as inference_boundary
from .inference_boundary_repaired import (
    AdmittedVeraState,
    CapabilityBinding,
    CausalGenerationReceipt,
    InvocationFrontier,
    InvocationRecord,
    OmissionRecord,
    ProjectionEnvelope,
    StateComponentRef,
    VeraStateComposition,
    bind_admitted_state,
    bind_capability,
    build_causal_receipt,
    canonical_digest,
    compose_state,
    project_text_context,
)
from .orgasm import (
    ContractError as OrgasmContractError,
    OrgasmRuntime,
    StimulusAppraisal,
    TriggerRejected as OrgasmTriggerRejected,
)
from .provider_admission import evaluate_provider_proposition_admission
from .reconcile import ReconciliationResult, reconcile_exact
from .runtime import (
    AdmissionDecision,
    RetrievalPlan,
    build_operational_checkpoint,
    build_retrieval_plan,
    evaluate_abstract_proposition_admission,
)

# Public package-level admission is provider-strict. Lightweight policy fixtures
# remain available only through the explicitly named abstract evaluator.
evaluate_proposition_admission = evaluate_provider_proposition_admission

__all__ = [
    "AdapterProbeResult",
    "AdapterRegistry",
    "AdapterRequest",
    "ProviderAdapter",
    "AffectiveCycleResult",
    "VeraAffectiveCycle",
    "AffectiveBindingError",
    "VeraAffectiveRuntimeHost",
    "AffectiveModulationAncestry",
    "AffectiveModulationApplication",
    "CohesionAffectiveIntegrationPort",
    "IntegratedAffectivePlanningResult",
    "validate_cohesion_affective_integration_cut",
    "PersistenceRecordError",
    "build_affective_resume_token",
    "build_atomic_commit_request",
    "checkpoint_to_state_row",
    "event_receipt_to_event_row",
    "restore_host_from_state_row",
    "restore_current_affective_cycle",
    "ProjectionAuditResult",
    "audit_registered_projections",
    "ProviderEvidenceEnvelope",
    "load_provider_fabric",
    "validate_envelope",
    "DomainExecutionResult",
    "GoverningResolutionRecord",
    "ProjectionExecutionResult",
    "execute_domain_cycle",
    "execute_projection_cycle",
    "FailureEvaluationResult",
    "evaluate_failure_signature",
    "validate_failure_wiring",
    "inference_boundary",
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
    "OrgasmContractError",
    "OrgasmRuntime",
    "StimulusAppraisal",
    "OrgasmTriggerRejected",
    "ReconciliationResult",
    "reconcile_exact",
    "AdmissionDecision",
    "RetrievalPlan",
    "build_operational_checkpoint",
    "build_retrieval_plan",
    "evaluate_proposition_admission",
    "evaluate_provider_proposition_admission",
    "evaluate_abstract_proposition_admission",
]
