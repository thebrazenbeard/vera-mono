from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

from .behavior_effect_verification import (
    BehaviorEffectRequirement,
    BehaviorEffectVerificationError,
    BehaviorEffectVerificationReceipt,
    BehaviorEffectVerificationStore,
    BehaviorEffectVerificationTransport,
    behavior_effect_requirements,
)
from .runtime_consumption import (
    RuntimeConsumptionVerificationError,
    runtime_consumption_requirements,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


@dataclass(frozen=True, slots=True)
class BehaviorEffectAssessment:
    task_id: str
    consumer_id: str
    probe_id: str
    evidence_kind: str
    expected_stimulus_digest: str
    expected_outcome_digest: str
    latest_status: str | None
    latest_receipt_digest: str | None
    latest_runtime_consumption_receipt_digest: str | None
    latest_process_instance_id: str | None
    latest_runtime_state_digest: str | None
    latest_external_effect_id: str | None
    latest_external_effect_receipt_digest: str | None
    latest_external_evidence_digest: str | None
    transport_available: bool
    runtime_consumption_required: bool
    runtime_consumption_current: bool
    current_runtime_consumption_receipt_digest: str | None
    current_process_instance_id: str | None
    current_runtime_state_digest: str | None
    current_observed_outcome_digest: str | None
    current_external_effect_id: str | None
    current_external_effect_receipt_digest: str | None
    current_external_evidence_digest: str | None
    current_matches_receipt: bool | None
    passed: bool
    reason: str


class QualifiedBehaviorEffectVerificationAdapter:
    """Task-bound live behavior/effect qualification from exact external evidence.

    Runtime consumption is a required prerequisite for the same consumer, but it
    is never treated as behavior/effect PASS. Qualification additionally requires
    a host/external probe observation tied to the exact currently consumed
    process/state and exact declared stimulus/outcome digests.
    """

    def __init__(
        self,
        *,
        runtime: "QualifiedVeraRuntime",
        transports: Mapping[str, BehaviorEffectVerificationTransport],
    ):
        self.runtime = runtime
        registry = dict(transports)
        for consumer_id, transport in registry.items():
            if type(consumer_id) is not str or not consumer_id:
                raise TypeError(
                    "behavior/effect transport keys must be non-empty strings"
                )
            if not isinstance(
                transport,
                BehaviorEffectVerificationTransport,
            ):
                raise TypeError(
                    f"behavior/effect transport for {consumer_id!r} "
                    "does not satisfy BehaviorEffectVerificationTransport"
                )
            if transport.consumer_id != consumer_id:
                raise ValueError(
                    "behavior/effect transport identity mismatch for "
                    f"{consumer_id!r}"
                )
        self.transports = registry

    def _requirements(
        self,
        task_id: str,
    ) -> tuple[BehaviorEffectRequirement, ...]:
        task = self.runtime.tasks.read(task_id)
        requirements = behavior_effect_requirements(
            task.packet.evidence_requirements
        )
        seen: dict[tuple[str, str], tuple[str, str, str]] = {}
        unique: list[BehaviorEffectRequirement] = []
        for requirement in requirements:
            key = (requirement.consumer_id, requirement.probe_id)
            value = (
                requirement.evidence_kind,
                requirement.expected_stimulus_digest,
                requirement.expected_outcome_digest,
            )
            prior = seen.get(key)
            if prior is not None:
                if prior != value:
                    raise BehaviorEffectVerificationError(
                        "task packet declares conflicting behavior/effect "
                        f"requirements for {key!r}"
                    )
                continue
            seen[key] = value
            unique.append(requirement)
        return tuple(unique)

    def _requirement(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ) -> BehaviorEffectRequirement:
        matches = tuple(
            item
            for item in self._requirements(task_id)
            if item.consumer_id == consumer_id
            and item.probe_id == probe_id
        )
        if len(matches) != 1:
            raise BehaviorEffectVerificationError(
                "task packet must declare exactly one matching "
                "BEHAVIOR_EFFECT_VERIFY requirement"
            )
        return matches[0]

    def _runtime_consumption_requirement(
        self,
        task_id: str,
        consumer_id: str,
    ):
        task = self.runtime.tasks.read(task_id)
        matches = tuple(
            item
            for item in runtime_consumption_requirements(
                task.packet.evidence_requirements
            )
            if item.consumer_id == consumer_id
        )
        if len(matches) != 1:
            raise BehaviorEffectVerificationError(
                "behavior/effect qualification requires exactly one matching "
                "RUNTIME_CONSUME_VERIFY requirement for the same consumer"
            )
        return matches[0]

    def _runtime_current(
        self,
        task_id: str,
        consumer_id: str,
    ):
        self._runtime_consumption_requirement(task_id, consumer_id)
        try:
            assessment = self.runtime.assess_runtime_consumption(
                task_id,
                consumer_id,
            )
        except RuntimeConsumptionVerificationError as exc:
            raise BehaviorEffectVerificationError(
                "runtime consumption prerequisite is invalid: " + str(exc)
            ) from exc
        return assessment

    def assess(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ) -> BehaviorEffectAssessment:
        task = self.runtime.tasks.read(task_id)
        requirement = self._requirement(
            task_id,
            consumer_id,
            probe_id,
        )
        transport = self.transports.get(consumer_id)
        runtime_assessment = self._runtime_current(
            task_id,
            consumer_id,
        )

        try:
            latest = self.runtime.behavior_effect_verifications.latest(
                task_id,
                consumer_id,
                probe_id,
            )
        except KeyError:
            return BehaviorEffectAssessment(
                task_id=task_id,
                consumer_id=consumer_id,
                probe_id=probe_id,
                evidence_kind=requirement.evidence_kind,
                expected_stimulus_digest=(
                    requirement.expected_stimulus_digest
                ),
                expected_outcome_digest=requirement.expected_outcome_digest,
                latest_status=None,
                latest_receipt_digest=None,
                latest_runtime_consumption_receipt_digest=None,
                latest_process_instance_id=None,
                latest_runtime_state_digest=None,
                latest_external_effect_id=None,
                latest_external_effect_receipt_digest=None,
                latest_external_evidence_digest=None,
                transport_available=transport is not None,
                runtime_consumption_required=True,
                runtime_consumption_current=runtime_assessment.passed,
                current_runtime_consumption_receipt_digest=(
                    runtime_assessment.latest_receipt_digest
                ),
                current_process_instance_id=(
                    runtime_assessment.current_process_instance_id
                ),
                current_runtime_state_digest=(
                    runtime_assessment.current_state_digest
                ),
                current_observed_outcome_digest=None,
                current_external_effect_id=None,
                current_external_effect_receipt_digest=None,
                current_external_evidence_digest=None,
                current_matches_receipt=None,
                passed=False,
                reason="required behavior/effect verification has not run",
            )

        base = dict(
            task_id=task_id,
            consumer_id=consumer_id,
            probe_id=probe_id,
            evidence_kind=requirement.evidence_kind,
            expected_stimulus_digest=requirement.expected_stimulus_digest,
            expected_outcome_digest=requirement.expected_outcome_digest,
            latest_status=latest.status,
            latest_receipt_digest=latest.receipt_digest,
            latest_runtime_consumption_receipt_digest=(
                latest.runtime_consumption_receipt_digest
            ),
            latest_process_instance_id=latest.observed_process_instance_id,
            latest_runtime_state_digest=latest.observed_runtime_state_digest,
            latest_external_effect_id=latest.external_effect_id,
            latest_external_effect_receipt_digest=(
                latest.external_effect_receipt_digest
            ),
            latest_external_evidence_digest=latest.external_evidence_digest,
            transport_available=transport is not None,
            runtime_consumption_required=True,
            runtime_consumption_current=runtime_assessment.passed,
            current_runtime_consumption_receipt_digest=(
                runtime_assessment.latest_receipt_digest
            ),
            current_process_instance_id=(
                runtime_assessment.current_process_instance_id
            ),
            current_runtime_state_digest=runtime_assessment.current_state_digest,
        )

        if latest.packet_digest != task.packet.packet_digest:
            return BehaviorEffectAssessment(
                **base,
                current_observed_outcome_digest=None,
                current_external_effect_id=None,
                current_external_effect_receipt_digest=None,
                current_external_evidence_digest=None,
                current_matches_receipt=False,
                passed=False,
                reason=(
                    "latest behavior/effect verification binds a different "
                    "task packet"
                ),
            )
        if (
            latest.evidence_kind != requirement.evidence_kind
            or latest.expected_stimulus_digest
            != requirement.expected_stimulus_digest
            or latest.expected_outcome_digest
            != requirement.expected_outcome_digest
        ):
            return BehaviorEffectAssessment(
                **base,
                current_observed_outcome_digest=None,
                current_external_effect_id=None,
                current_external_effect_receipt_digest=None,
                current_external_evidence_digest=None,
                current_matches_receipt=False,
                passed=False,
                reason=(
                    "latest behavior/effect verification binds a different "
                    "declared probe contract"
                ),
            )
        if latest.status != "PASS":
            return BehaviorEffectAssessment(
                **base,
                current_observed_outcome_digest=latest.observed_outcome_digest,
                current_external_effect_id=latest.external_effect_id,
                current_external_effect_receipt_digest=(
                    latest.external_effect_receipt_digest
                ),
                current_external_evidence_digest=(
                    latest.external_evidence_digest
                ),
                current_matches_receipt=None,
                passed=False,
                reason=f"behavior/effect verification is {latest.status}",
            )
        if not runtime_assessment.passed:
            return BehaviorEffectAssessment(
                **base,
                current_observed_outcome_digest=None,
                current_external_effect_id=None,
                current_external_effect_receipt_digest=None,
                current_external_evidence_digest=None,
                current_matches_receipt=False,
                passed=False,
                reason=(
                    "runtime consumption is not live-current; stored "
                    "behavior/effect PASS is historical evidence only"
                ),
            )
        if (
            runtime_assessment.latest_receipt_digest
            != latest.runtime_consumption_receipt_digest
            or runtime_assessment.current_process_instance_id
            != latest.consumed_process_instance_id
            or runtime_assessment.current_state_digest
            != latest.consumed_runtime_state_digest
        ):
            return BehaviorEffectAssessment(
                **base,
                current_observed_outcome_digest=None,
                current_external_effect_id=None,
                current_external_effect_receipt_digest=None,
                current_external_evidence_digest=None,
                current_matches_receipt=False,
                passed=False,
                reason=(
                    "live consumed runtime changed since behavior/effect "
                    "qualification"
                ),
            )
        if transport is None:
            return BehaviorEffectAssessment(
                **base,
                current_observed_outcome_digest=None,
                current_external_effect_id=None,
                current_external_effect_receipt_digest=None,
                current_external_evidence_digest=None,
                current_matches_receipt=None,
                passed=False,
                reason=(
                    "stored behavior/effect PASS cannot be refreshed because "
                    "no host/external evidence transport is available"
                ),
            )

        current = transport.observe(
            requirement.probe_id,
            requirement.evidence_kind,
            requirement.expected_stimulus_digest,
            requirement.expected_outcome_digest,
        )
        current_status = BehaviorEffectVerificationStore._status(
            requirement,
            current,
            consumed_process_instance_id=(
                runtime_assessment.current_process_instance_id
            ),
            consumed_runtime_state_digest=(
                runtime_assessment.current_state_digest
            ),
        )
        current_matches = (
            current_status == "PASS"
            and current.process_instance_id
            == latest.observed_process_instance_id
            and current.runtime_state_digest
            == latest.observed_runtime_state_digest
            and current.stimulus_digest
            == latest.observed_stimulus_digest
            and current.observed_outcome_digest
            == latest.observed_outcome_digest
            and current.external_effect_id == latest.external_effect_id
            and current.external_effect_receipt_digest
            == latest.external_effect_receipt_digest
            and current.external_evidence_digest
            == latest.external_evidence_digest
            and current.evidence_ref == latest.evidence_ref
        )
        return BehaviorEffectAssessment(
            **base,
            current_observed_outcome_digest=current.observed_outcome_digest,
            current_external_effect_id=current.external_effect_id,
            current_external_effect_receipt_digest=(
                current.external_effect_receipt_digest
            ),
            current_external_evidence_digest=current.external_evidence_digest,
            current_matches_receipt=current_matches,
            passed=current_matches,
            reason=(
                "behavior/effect PASS remains live-current for the exact "
                "consumed runtime and host/external evidence"
                if current_matches
                else (
                    "live host/external behavior evidence no longer matches "
                    "the exact stored PASS observation"
                )
            ),
        )

    def verify(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ) -> BehaviorEffectVerificationReceipt:
        task = self.runtime.tasks.read(task_id)
        if task.closed:
            raise BehaviorEffectVerificationError(
                "closed task cannot append behavior/effect verification"
            )
        if "behavior/effect" not in task.packet.relevant_surfaces:
            raise BehaviorEffectVerificationError(
                "task packet does not declare behavior/effect surface"
            )
        requirement = self._requirement(
            task_id,
            consumer_id,
            probe_id,
        )
        transport = self.transports.get(consumer_id)
        if transport is None:
            raise BehaviorEffectVerificationError(
                "no host-injected behavior/effect transport for consumer"
            )

        self.runtime.accepted_permit()
        runtime_assessment = self._runtime_current(
            task_id,
            consumer_id,
        )
        if not runtime_assessment.passed:
            raise BehaviorEffectVerificationError(
                "behavior/effect cannot qualify before the same live runtime "
                "consumer is verified-current"
            )
        if (
            runtime_assessment.latest_receipt_digest is None
            or runtime_assessment.current_process_instance_id is None
            or runtime_assessment.current_state_digest is None
        ):
            raise BehaviorEffectVerificationError(
                "runtime consumption PASS lacks exact current process/state evidence"
            )

        observation = transport.observe(
            requirement.probe_id,
            requirement.evidence_kind,
            requirement.expected_stimulus_digest,
            requirement.expected_outcome_digest,
        )
        return self.runtime.behavior_effect_verifications.append(
            task_id=task_id,
            packet_digest=task.packet.packet_digest,
            requirement=requirement,
            runtime_consumption_receipt_digest=(
                runtime_assessment.latest_receipt_digest
            ),
            consumed_process_instance_id=(
                runtime_assessment.current_process_instance_id
            ),
            consumed_runtime_state_digest=(
                runtime_assessment.current_state_digest
            ),
            observation=observation,
        )

    def assess_task(
        self,
        task_id: str,
    ) -> tuple[BehaviorEffectAssessment, ...]:
        return tuple(
            self.assess(
                task_id,
                requirement.consumer_id,
                requirement.probe_id,
            )
            for requirement in self._requirements(task_id)
        )

    def recover(
        self,
    ) -> tuple[BehaviorEffectAssessment, ...]:
        return tuple(
            assessment
            for task in self.runtime.tasks.tasks()
            if not task.closed
            for assessment in self.assess_task(task.task_id)
        )
