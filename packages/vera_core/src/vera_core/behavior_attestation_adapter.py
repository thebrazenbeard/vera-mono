from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

from .behavior_attestation import (
    BehaviorAttestationError,
    BehaviorAttestationReceipt,
    BehaviorAttestationRequirement,
    BehaviorAttestationStore,
    BehaviorAttestationTransport,
    behavior_attestation_requirements,
)
from .behavior_effect_verification import (
    BehaviorEffectRequirement,
    BehaviorEffectVerificationError,
    behavior_effect_requirements,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


@dataclass(frozen=True, slots=True)
class BehaviorAttestationAssessment:
    task_id: str
    consumer_id: str
    probe_id: str
    evidence_kind: str
    expected_declaration_digest: str
    expected_provider_id: str
    expected_provider_key_id: str
    expected_provider_key_digest: str
    expected_effect_subject_digest: str | None
    latest_status: str | None
    latest_receipt_digest: str | None
    latest_behavior_effect_receipt_digest: str | None
    latest_attestation_subject_digest: str | None
    latest_external_evidence_digest: str | None
    transport_available: bool
    behavior_effect_current: bool
    current_behavior_effect_receipt_digest: str | None
    current_attestation_subject_digest: str | None
    current_external_evidence_digest: str | None
    current_signature_valid: bool | None
    current_matches_receipt: bool | None
    passed: bool
    reason: str


class QualifiedBehaviorAttestationAdapter:
    """Verifier-bound external provenance above live behavior/effect PASS."""

    def __init__(
        self,
        *,
        runtime: "QualifiedVeraRuntime",
        transports: Mapping[
            tuple[str, str],
            BehaviorAttestationTransport,
        ],
    ):
        self.runtime = runtime
        registry = dict(transports)
        for scope, transport in registry.items():
            if (
                not isinstance(scope, tuple)
                or len(scope) != 2
                or not all(type(item) is str and item for item in scope)
            ):
                raise TypeError(
                    "behavior attestation transport keys must be "
                    "(consumer_id, provider_id)"
                )
            if not isinstance(transport, BehaviorAttestationTransport):
                raise TypeError(
                    f"behavior attestation transport for {scope!r} "
                    "does not satisfy BehaviorAttestationTransport"
                )
            if (transport.consumer_id, transport.provider_id) != scope:
                raise ValueError(
                    "behavior attestation transport identity mismatch for "
                    f"{scope!r}"
                )
        self.transports = registry

    def _requirements(
        self,
        task_id: str,
    ) -> tuple[BehaviorAttestationRequirement, ...]:
        task = self.runtime.tasks.read(task_id)
        requirements = behavior_attestation_requirements(
            task.packet.evidence_requirements
        )
        seen: dict[
            tuple[str, str],
            tuple[str, str, str, str, str | None],
        ] = {}
        unique: list[BehaviorAttestationRequirement] = []
        for requirement in requirements:
            key = (requirement.consumer_id, requirement.probe_id)
            value = (
                requirement.declaration_digest,
                requirement.provider_id,
                requirement.provider_key_id,
                requirement.provider_key_digest,
                requirement.effect_subject_digest,
            )
            prior = seen.get(key)
            if prior is not None:
                if prior != value:
                    raise BehaviorAttestationError(
                        "task packet declares conflicting behavior attestation "
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
    ) -> BehaviorAttestationRequirement:
        matches = tuple(
            item
            for item in self._requirements(task_id)
            if item.consumer_id == consumer_id
            and item.probe_id == probe_id
        )
        if len(matches) != 1:
            raise BehaviorAttestationError(
                "task packet must declare exactly one matching "
                "BEHAVIOR_ATTEST_VERIFY requirement"
            )
        return matches[0]

    def _behavior_requirement(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ) -> BehaviorEffectRequirement:
        task = self.runtime.tasks.read(task_id)
        matches = tuple(
            item
            for item in behavior_effect_requirements(
                task.packet.evidence_requirements
            )
            if item.consumer_id == consumer_id
            and item.probe_id == probe_id
        )
        if len(matches) != 1:
            raise BehaviorAttestationError(
                "behavior attestation requires exactly one matching "
                "BEHAVIOR_EFFECT_VERIFY requirement"
            )
        return matches[0]

    def _transport(
        self,
        requirement: BehaviorAttestationRequirement,
    ) -> BehaviorAttestationTransport | None:
        return self.transports.get(
            (requirement.consumer_id, requirement.provider_id)
        )

    def _behavior_assessment(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ):
        try:
            return self.runtime.assess_behavior_effect(
                task_id,
                consumer_id,
                probe_id,
            )
        except BehaviorEffectVerificationError as exc:
            raise BehaviorAttestationError(
                "behavior/effect prerequisite is invalid: " + str(exc)
            ) from exc

    def assess(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ) -> BehaviorAttestationAssessment:
        task = self.runtime.tasks.read(task_id)
        requirement = self._requirement(task_id, consumer_id, probe_id)
        behavior_requirement = self._behavior_requirement(
            task_id, consumer_id, probe_id
        )
        behavior_assessment = self._behavior_assessment(
            task_id, consumer_id, probe_id
        )
        transport = self._transport(requirement)

        try:
            latest = self.runtime.behavior_attestations.latest(
                task_id, consumer_id, probe_id
            )
        except KeyError:
            return BehaviorAttestationAssessment(
                task_id=task_id,
                consumer_id=consumer_id,
                probe_id=probe_id,
                evidence_kind=behavior_requirement.evidence_kind,
                expected_declaration_digest=requirement.declaration_digest,
                expected_provider_id=requirement.provider_id,
                expected_provider_key_id=requirement.provider_key_id,
                expected_provider_key_digest=requirement.provider_key_digest,
                expected_effect_subject_digest=requirement.effect_subject_digest,
                latest_status=None,
                latest_receipt_digest=None,
                latest_behavior_effect_receipt_digest=None,
                latest_attestation_subject_digest=None,
                latest_external_evidence_digest=None,
                transport_available=transport is not None,
                behavior_effect_current=behavior_assessment.passed,
                current_behavior_effect_receipt_digest=(
                    behavior_assessment.latest_receipt_digest
                ),
                current_attestation_subject_digest=None,
                current_external_evidence_digest=None,
                current_signature_valid=None,
                current_matches_receipt=None,
                passed=False,
                reason="required external behavior attestation has not run",
            )

        base = dict(
            task_id=task_id,
            consumer_id=consumer_id,
            probe_id=probe_id,
            evidence_kind=behavior_requirement.evidence_kind,
            expected_declaration_digest=requirement.declaration_digest,
            expected_provider_id=requirement.provider_id,
            expected_provider_key_id=requirement.provider_key_id,
            expected_provider_key_digest=requirement.provider_key_digest,
            expected_effect_subject_digest=requirement.effect_subject_digest,
            latest_status=latest.status,
            latest_receipt_digest=latest.receipt_digest,
            latest_behavior_effect_receipt_digest=(
                latest.behavior_effect_receipt_digest
            ),
            latest_attestation_subject_digest=(
                latest.observed_attestation_subject_digest
            ),
            latest_external_evidence_digest=(
                latest.observed_external_evidence_digest
            ),
            transport_available=transport is not None,
            behavior_effect_current=behavior_assessment.passed,
            current_behavior_effect_receipt_digest=(
                behavior_assessment.latest_receipt_digest
            ),
        )

        if latest.packet_digest != task.packet.packet_digest:
            return BehaviorAttestationAssessment(
                **base,
                current_attestation_subject_digest=None,
                current_external_evidence_digest=None,
                current_signature_valid=None,
                current_matches_receipt=False,
                passed=False,
                reason="latest behavior attestation binds a different task packet",
            )
        if (
            latest.expected_declaration_digest != requirement.declaration_digest
            or latest.expected_provider_id != requirement.provider_id
            or latest.expected_provider_key_id != requirement.provider_key_id
            or latest.expected_provider_key_digest
            != requirement.provider_key_digest
            or latest.expected_effect_subject_digest
            != requirement.effect_subject_digest
            or latest.evidence_kind != behavior_requirement.evidence_kind
        ):
            return BehaviorAttestationAssessment(
                **base,
                current_attestation_subject_digest=None,
                current_external_evidence_digest=None,
                current_signature_valid=None,
                current_matches_receipt=False,
                passed=False,
                reason=(
                    "latest behavior attestation binds a different declaration "
                    "or evidence-provider contract"
                ),
            )
        if latest.status != "PASS":
            return BehaviorAttestationAssessment(
                **base,
                current_attestation_subject_digest=(
                    latest.observed_attestation_subject_digest
                ),
                current_external_evidence_digest=(
                    latest.observed_external_evidence_digest
                ),
                current_signature_valid=latest.observed_signature_valid,
                current_matches_receipt=None,
                passed=False,
                reason=f"behavior attestation is {latest.status}",
            )
        if not behavior_assessment.passed:
            return BehaviorAttestationAssessment(
                **base,
                current_attestation_subject_digest=None,
                current_external_evidence_digest=None,
                current_signature_valid=None,
                current_matches_receipt=False,
                passed=False,
                reason=(
                    "behavior/effect prerequisite is not live-current; stored "
                    "attestation is historical evidence only"
                ),
            )
        if (
            behavior_assessment.latest_receipt_digest
            != latest.behavior_effect_receipt_digest
        ):
            return BehaviorAttestationAssessment(
                **base,
                current_attestation_subject_digest=None,
                current_external_evidence_digest=None,
                current_signature_valid=None,
                current_matches_receipt=False,
                passed=False,
                reason="live behavior/effect receipt changed since attestation",
            )
        if transport is None:
            return BehaviorAttestationAssessment(
                **base,
                current_attestation_subject_digest=None,
                current_external_evidence_digest=None,
                current_signature_valid=None,
                current_matches_receipt=None,
                passed=False,
                reason=(
                    "stored behavior attestation cannot be refreshed because "
                    "no external verifier transport is available"
                ),
            )

        behavior_receipt = self.runtime.behavior_effect_verifications.latest(
            task_id, consumer_id, probe_id
        )
        current = transport.observe(
            requirement,
            behavior_requirement,
            behavior_receipt,
        )
        current_status = BehaviorAttestationStore._status(
            requirement,
            behavior_requirement,
            behavior_receipt,
            current,
        )
        current_matches = (
            current_status == "PASS"
            and current.behavior_effect_receipt_digest
            == latest.observed_behavior_effect_receipt_digest
            and current.declaration_digest == latest.observed_declaration_digest
            and current.process_instance_id == latest.observed_process_instance_id
            and current.runtime_state_digest
            == latest.observed_runtime_state_digest
            and current.stimulus_digest == latest.observed_stimulus_digest
            and current.outcome_digest == latest.observed_outcome_digest
            and current.raw_response_digest == latest.observed_raw_response_digest
            and current.provider_id == latest.observed_provider_id
            and current.provider_key_id == latest.observed_provider_key_id
            and current.provider_key_digest
            == latest.observed_provider_key_digest
            and current.attestation_nonce == latest.observed_attestation_nonce
            and current.attestation_subject_digest
            == latest.observed_attestation_subject_digest
            and current.attestation_signature
            == latest.observed_attestation_signature
            and current.signature_valid == latest.observed_signature_valid
            and current.external_effect_id == latest.observed_external_effect_id
            and current.external_effect_receipt_digest
            == latest.observed_external_effect_receipt_digest
            and current.external_effect_subject_digest
            == latest.observed_external_effect_subject_digest
            and current.external_evidence_digest
            == latest.observed_external_evidence_digest
            and current.evidence_ref == latest.evidence_ref
        )
        return BehaviorAttestationAssessment(
            **base,
            current_attestation_subject_digest=current.attestation_subject_digest,
            current_external_evidence_digest=current.external_evidence_digest,
            current_signature_valid=current.signature_valid,
            current_matches_receipt=current_matches,
            passed=current_matches,
            reason=(
                "external behavior attestation remains live-current for the "
                "exact declaration, provider, behavior receipt, and evidence"
                if current_matches
                else (
                    "live external behavior attestation no longer matches "
                    "the exact stored PASS"
                )
            ),
        )

    def verify(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ) -> BehaviorAttestationReceipt:
        task = self.runtime.tasks.read(task_id)
        if task.closed:
            raise BehaviorAttestationError(
                "closed task cannot append behavior attestation"
            )
        if "behavior/effect" not in task.packet.relevant_surfaces:
            raise BehaviorAttestationError(
                "task packet does not declare behavior/effect surface"
            )
        requirement = self._requirement(task_id, consumer_id, probe_id)
        behavior_requirement = self._behavior_requirement(
            task_id, consumer_id, probe_id
        )
        transport = self._transport(requirement)
        if transport is None:
            raise BehaviorAttestationError(
                "no host-injected behavior attestation transport for "
                "consumer/provider"
            )

        self.runtime.accepted_permit()
        behavior_assessment = self._behavior_assessment(
            task_id, consumer_id, probe_id
        )
        if not behavior_assessment.passed:
            raise BehaviorAttestationError(
                "behavior attestation cannot qualify before the matching "
                "behavior/effect probe is live-current PASS"
            )
        behavior_receipt = self.runtime.behavior_effect_verifications.latest(
            task_id, consumer_id, probe_id
        )
        if (
            behavior_assessment.latest_receipt_digest
            != behavior_receipt.receipt_digest
        ):
            raise BehaviorAttestationError(
                "behavior/effect assessment and durable receipt diverge"
            )

        observation = transport.observe(
            requirement,
            behavior_requirement,
            behavior_receipt,
        )
        return self.runtime.behavior_attestations.append(
            task_id=task_id,
            packet_digest=task.packet.packet_digest,
            requirement=requirement,
            behavior_requirement=behavior_requirement,
            behavior_receipt=behavior_receipt,
            observation=observation,
        )

    def assess_task(
        self,
        task_id: str,
    ) -> tuple[BehaviorAttestationAssessment, ...]:
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
    ) -> tuple[BehaviorAttestationAssessment, ...]:
        return tuple(
            assessment
            for task in self.runtime.tasks.tasks()
            if not task.closed
            for assessment in self.assess_task(task.task_id)
        )
