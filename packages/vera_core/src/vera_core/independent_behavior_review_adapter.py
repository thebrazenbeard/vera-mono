from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, TYPE_CHECKING

from .behavior_effect_verification import BehaviorEffectRequirement, BehaviorEffectVerificationError, behavior_effect_requirements
from .independent_behavior_review import (
    IndependentBehaviorReviewError, IndependentBehaviorReviewReceipt, IndependentBehaviorReviewRequirement,
    IndependentBehaviorReviewStore, IndependentBehaviorReviewTransport, independent_behavior_review_requirements,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


@dataclass(frozen=True, slots=True)
class IndependentBehaviorReviewAssessment:
    task_id: str
    consumer_id: str
    probe_id: str
    review_id: str
    latest_status: str | None
    latest_receipt_digest: str | None
    transport_available: bool
    behavior_effect_current: bool
    current_behavior_effect_receipt_digest: str | None
    current_authority_subject_digest: str | None
    current_review_subject_digest: str | None
    current_authority_evidence_digest: str | None
    current_review_evidence_digest: str | None
    current_verdict: str | None
    current_authority_current: bool | None
    current_operationally_separate: bool | None
    current_signatures_valid: bool | None
    current_matches_receipt: bool | None
    passed: bool
    reason: str


class QualifiedIndependentBehaviorReviewAdapter:
    def __init__(self, *, runtime: "QualifiedVeraRuntime", transports: Mapping[tuple[str, str], IndependentBehaviorReviewTransport]):
        self.runtime = runtime
        self.transports = dict(transports)
        for scope, transport in self.transports.items():
            if not isinstance(scope, tuple) or len(scope) != 2 or not all(type(x) is str and x for x in scope):
                raise TypeError("independent review transport keys must be (consumer_id, review_id)")
            if not isinstance(transport, IndependentBehaviorReviewTransport):
                raise TypeError("independent review transport does not satisfy IndependentBehaviorReviewTransport")
            if (transport.consumer_id, transport.review_id) != scope:
                raise ValueError("independent review transport identity mismatch")

    def _requirements(self, task_id):
        task = self.runtime.tasks.read(task_id)
        raw = independent_behavior_review_requirements(task.packet.evidence_requirements)
        seen, out = {}, []
        for item in raw:
            key = (item.consumer_id, item.probe_id, item.review_id)
            value = tuple(IndependentBehaviorReviewStore._requirement_dict(item).values())
            if key in seen and seen[key] != value:
                raise IndependentBehaviorReviewError(f"conflicting independent review requirements for {key!r}")
            if key not in seen:
                seen[key] = value
                out.append(item)
        return tuple(out)

    def _requirement(self, task_id, consumer_id, probe_id, review_id):
        matches = tuple(x for x in self._requirements(task_id) if (x.consumer_id, x.probe_id, x.review_id) == (consumer_id, probe_id, review_id))
        if len(matches) != 1:
            raise IndependentBehaviorReviewError("task packet must declare exactly one matching INDEPENDENT_BEHAVIOR_REVIEW_VERIFY requirement")
        return matches[0]

    def _behavior_requirement(self, task_id, consumer_id, probe_id) -> BehaviorEffectRequirement:
        task = self.runtime.tasks.read(task_id)
        matches = tuple(x for x in behavior_effect_requirements(task.packet.evidence_requirements) if (x.consumer_id, x.probe_id) == (consumer_id, probe_id))
        if len(matches) != 1:
            raise IndependentBehaviorReviewError("independent review requires exactly one matching BEHAVIOR_EFFECT_VERIFY requirement")
        return matches[0]

    def _behavior_assessment(self, task_id, consumer_id, probe_id):
        try:
            return self.runtime.assess_behavior_effect(task_id, consumer_id, probe_id)
        except BehaviorEffectVerificationError as exc:
            raise IndependentBehaviorReviewError("behavior/effect prerequisite is invalid: " + str(exc)) from exc

    def assess(self, task_id, consumer_id, probe_id, review_id):
        task = self.runtime.tasks.read(task_id)
        requirement = self._requirement(task_id, consumer_id, probe_id, review_id)
        behavior_requirement = self._behavior_requirement(task_id, consumer_id, probe_id)
        behavior_assessment = self._behavior_assessment(task_id, consumer_id, probe_id)
        transport = self.transports.get((consumer_id, review_id))
        base = dict(task_id=task_id, consumer_id=consumer_id, probe_id=probe_id, review_id=review_id,
                    transport_available=transport is not None, behavior_effect_current=behavior_assessment.passed,
                    current_behavior_effect_receipt_digest=behavior_assessment.latest_receipt_digest)
        try:
            latest = self.runtime.independent_behavior_reviews.latest(task_id, consumer_id, probe_id, review_id)
        except KeyError:
            return IndependentBehaviorReviewAssessment(**base, latest_status=None, latest_receipt_digest=None,
                current_authority_subject_digest=None, current_review_subject_digest=None,
                current_authority_evidence_digest=None, current_review_evidence_digest=None,
                current_verdict=None, current_authority_current=None, current_operationally_separate=None,
                current_signatures_valid=None, current_matches_receipt=None, passed=False,
                reason="required independent behavior review has not run")

        def answer(reason, **values):
            defaults = dict(current_authority_subject_digest=None, current_review_subject_digest=None,
                current_authority_evidence_digest=None, current_review_evidence_digest=None, current_verdict=None,
                current_authority_current=None, current_operationally_separate=None, current_signatures_valid=None,
                current_matches_receipt=False, passed=False)
            defaults.update(values)
            return IndependentBehaviorReviewAssessment(**base, latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest, reason=reason, **defaults)

        if latest.payload.get("packet_digest") != task.packet.packet_digest:
            return answer("latest independent review binds a different task packet")
        if latest.payload.get("requirement") != IndependentBehaviorReviewStore._requirement_dict(requirement):
            return answer("latest independent review binds a different review contract")
        if latest.status != "PASS":
            return answer(f"independent behavior review is {latest.status}", current_matches_receipt=None)
        if not behavior_assessment.passed:
            return answer("behavior/effect prerequisite is not live-current; stored independent review is historical evidence only")
        if latest.payload.get("behavior_effect_receipt_digest") != behavior_assessment.latest_receipt_digest:
            return answer("live behavior/effect receipt changed since independent review")
        if transport is None:
            return answer("stored independent review cannot be refreshed because no external review transport is available")
        behavior_receipt = self.runtime.behavior_effect_verifications.latest(task_id, consumer_id, probe_id)
        current = transport.observe(requirement, behavior_requirement, behavior_receipt)
        status = IndependentBehaviorReviewStore._status(requirement, behavior_requirement, behavior_receipt, current)
        matches = status == "PASS" and asdict(current) == latest.payload.get("observation")
        return answer(
            "independent behavior review remains live-current for the exact held-out set, evaluator authority, runtime receipt, result, and provenance"
            if matches else "live independent behavior review no longer matches the exact stored PASS",
            current_authority_subject_digest=current.authority_subject_digest,
            current_review_subject_digest=current.review_subject_digest,
            current_authority_evidence_digest=current.authority_evidence_digest,
            current_review_evidence_digest=current.review_evidence_digest,
            current_verdict=current.verdict, current_authority_current=current.authority_current,
            current_operationally_separate=current.operationally_separate,
            current_signatures_valid=current.authority_signature_valid is True and current.evaluator_signature_valid is True,
            current_matches_receipt=matches, passed=matches,
        )

    def verify(self, task_id, consumer_id, probe_id, review_id) -> IndependentBehaviorReviewReceipt:
        task = self.runtime.tasks.read(task_id)
        if task.closed:
            raise IndependentBehaviorReviewError("closed task cannot append independent review")
        if "behavior/effect" not in task.packet.relevant_surfaces:
            raise IndependentBehaviorReviewError("task packet does not declare behavior/effect surface")
        requirement = self._requirement(task_id, consumer_id, probe_id, review_id)
        behavior_requirement = self._behavior_requirement(task_id, consumer_id, probe_id)
        transport = self.transports.get((consumer_id, review_id))
        if transport is None:
            raise IndependentBehaviorReviewError("no host-injected independent review transport for consumer/review")
        self.runtime.accepted_permit()
        behavior_assessment = self._behavior_assessment(task_id, consumer_id, probe_id)
        if not behavior_assessment.passed:
            raise IndependentBehaviorReviewError("independent review cannot qualify before matching behavior/effect probe is live-current PASS")
        behavior_receipt = self.runtime.behavior_effect_verifications.latest(task_id, consumer_id, probe_id)
        observation = transport.observe(requirement, behavior_requirement, behavior_receipt)
        return self.runtime.independent_behavior_reviews.append(
            task_id=task_id, packet_digest=task.packet.packet_digest, requirement=requirement,
            behavior_requirement=behavior_requirement, behavior_receipt=behavior_receipt, observation=observation,
        )

    def assess_task(self, task_id):
        return tuple(self.assess(task_id, x.consumer_id, x.probe_id, x.review_id) for x in self._requirements(task_id))

    def recover(self):
        return tuple(a for task in self.runtime.tasks.tasks() if not task.closed for a in self.assess_task(task.task_id))
