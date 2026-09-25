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
from .policy_constraints import (
    PolicyConstraintFinding,
    PolicyConstraintReport,
    audit_policy_constraints,
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
    "PolicyConstraintFinding",
    "PolicyConstraintReport",
    "Snapshot",
    "audit_policy_constraints",
    "compare_snapshots",
]
