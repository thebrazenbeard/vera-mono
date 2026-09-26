"""Internal Vera assurance primitives.

These checks are intentionally not independent review. External DriftGuard or
another separate evaluator remains the stronger falsification boundary.
"""

from .drift import DriftFinding, DriftPolicy, DriftReport, Snapshot, compare_snapshots
from .mechanism_admission import (
    MechanismAdmissionError,
    MechanismEvidencePacket,
    assert_mechanism_admissible,
    mechanism_admission_defects,
)
from .resource_envelope import (
    FixedResourceEnvelope,
    ResourceEnvelopeReport,
    ResourceUsage,
    adjudicate_resource_envelope,
)
from .policy_constraints import (
    PolicyConstraintFinding,
    PolicyConstraintReport,
    audit_policy_constraints,
)
from .evaluation_commitment import (
    CommittedComparison,
    ComparisonConditions,
    PredictionCommitment,
    commit_prediction,
    compare_committed_predictions,
)
from .effect_fence import (
    AtomicCurrentnessStore,
    CurrentnessSnapshot,
    EffectFence,
    EffectFenceError,
    EffectReceipt,
    EffectState,
)

__all__ = [
    "AtomicCurrentnessStore",
    "CommittedComparison",
    "ComparisonConditions",
    "PredictionCommitment",
    "commit_prediction",
    "compare_committed_predictions",
    "CurrentnessSnapshot",
    "DriftFinding",
    "DriftPolicy",
    "DriftReport",
    "EffectFence",
    "EffectFenceError",
    "EffectReceipt",
    "EffectState",
    "MechanismAdmissionError",
    "MechanismEvidencePacket",
    "assert_mechanism_admissible",
    "mechanism_admission_defects",
    "FixedResourceEnvelope",
    "ResourceEnvelopeReport",
    "ResourceUsage",
    "adjudicate_resource_envelope",
    "PolicyConstraintFinding",
    "PolicyConstraintReport",
    "Snapshot",
    "audit_policy_constraints",
    "compare_snapshots",
]
