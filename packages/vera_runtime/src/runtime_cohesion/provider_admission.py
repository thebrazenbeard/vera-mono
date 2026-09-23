from __future__ import annotations

from .runtime import AdmissionDecision, evaluate_proposition_admission


# One strict function object is shared by the direct runtime API, the provider
# admission surface, and the governing executor's existing runtime import. This
# keeps identity/wiring explicit without import-time monkeypatching. The strict
# function requires ProviderEvidenceEnvelope instances before delegating to the
# separately named abstract policy evaluator.
evaluate_provider_proposition_admission = evaluate_proposition_admission


__all__ = [
    "AdmissionDecision",
    "evaluate_provider_proposition_admission",
]
