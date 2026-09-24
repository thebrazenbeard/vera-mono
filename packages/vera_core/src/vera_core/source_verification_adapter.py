from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

from vera_assurance import EffectState

from .source_verification import (
    SourceVerificationError,
    SourceVerificationReceipt,
    SourceVerificationTransport,
    source_verification_requirements,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


@dataclass(frozen=True, slots=True)
class SourceVerificationAssessment:
    mutation_id: str
    repository: str
    ref: str
    commit_sha: str | None
    required_checks: tuple[str, ...]
    verification_required: bool
    latest_status: str | None
    latest_receipt_digest: str | None
    transport_available: bool
    passed: bool
    reason: str
    current_ref_head: str | None = None
    current_ref_matches_commit: bool | None = None


class QualifiedSourceVerificationAdapter:
    """Read-only exact-commit verification for committed source mutations."""

    def __init__(
        self,
        *,
        runtime: "QualifiedVeraRuntime",
        transports: Mapping[
            tuple[str, str], SourceVerificationTransport
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
                    "source verification transport keys must be (repository, ref)"
                )
            if not isinstance(transport, SourceVerificationTransport):
                raise TypeError(
                    f"source verification transport for {scope!r} "
                    "does not satisfy SourceVerificationTransport"
                )
            if (transport.repository, transport.ref) != scope:
                raise ValueError(
                    f"source verification transport identity mismatch for {scope!r}"
                )
        self.transports = registry

    def _validated_outcome(self, mutation_id: str):
        binding = self.runtime.source_mutation_bindings.read(
            mutation_id
        )
        outcome = self.runtime.source_mutation_outcomes.read(
            mutation_id
        )
        provider_binding = self.runtime.provider_execution_bindings.read(
            mutation_id
        )
        if outcome.source_binding_digest != binding.binding_digest:
            raise SourceVerificationError(
                "source verification outcome does not bind exact source mutation"
            )
        if outcome.provider_binding_digest != provider_binding.binding_digest:
            raise SourceVerificationError(
                "source verification outcome does not bind exact provider execution"
            )
        expected_effect_id = (
            f"provider:{binding.provider_id}:{binding.provider_effect_id}"
        )
        if outcome.mechanical_effect_id != expected_effect_id:
            raise SourceVerificationError(
                "source verification outcome mechanical effect identity mismatch"
            )
        if (
            outcome.repository != binding.repository
            or outcome.ref != binding.ref
            or outcome.operation != binding.operation
            or outcome.path != binding.path
            or outcome.destination_path != binding.destination_path
            or outcome.previous_ref_head != binding.expected_ref_head
        ):
            raise SourceVerificationError(
                "source verification outcome diverges from durable mutation binding"
            )
        receipt = self.runtime.fence.read(expected_effect_id)
        if receipt.state not in {
            EffectState.COMMITTED,
            EffectState.RECONCILED_COMMITTED,
        }:
            raise SourceVerificationError(
                "source verification requires successful terminal source effect"
            )
        if receipt.request_digest != outcome.effect_request_digest:
            raise SourceVerificationError(
                "source verification outcome request digest mismatch"
            )
        if receipt.result_digest != outcome.effect_result_digest:
            raise SourceVerificationError(
                "source verification outcome result digest mismatch"
            )
        return binding, outcome

    def _requirements(
        self,
        mutation_id: str,
    ) -> tuple[str, ...]:
        binding = self.runtime.source_mutation_bindings.read(
            mutation_id
        )
        task = self.runtime.tasks.read(binding.task_id)
        requirements = source_verification_requirements(
            task.packet.evidence_requirements,
            repository=binding.repository,
            ref=binding.ref,
        )
        return tuple(
            dict.fromkeys(
                requirement.check_name
                for requirement in requirements
            )
        )

    def assess(
        self,
        mutation_id: str,
    ) -> SourceVerificationAssessment:
        binding = self.runtime.source_mutation_bindings.read(
            mutation_id
        )
        requirements = self._requirements(mutation_id)
        try:
            _, outcome = self._validated_outcome(mutation_id)
        except KeyError:
            return SourceVerificationAssessment(
                mutation_id=mutation_id,
                repository=binding.repository,
                ref=binding.ref,
                commit_sha=None,
                required_checks=requirements,
                verification_required=bool(requirements),
                latest_status=None,
                latest_receipt_digest=None,
                transport_available=(
                    (binding.repository, binding.ref)
                    in self.transports
                ),
                passed=False,
                reason="source mutation has no exact durable outcome",
            )

        latest = self.runtime.source_verifications.latest(
            mutation_id
        )
        transport_available = (
            (binding.repository, binding.ref) in self.transports
        )
        if not requirements:
            return SourceVerificationAssessment(
                mutation_id=mutation_id,
                repository=binding.repository,
                ref=binding.ref,
                commit_sha=outcome.new_ref_head,
                required_checks=(),
                verification_required=False,
                latest_status=(
                    None if latest is None else latest.status
                ),
                latest_receipt_digest=(
                    None
                    if latest is None
                    else latest.receipt_digest
                ),
                transport_available=transport_available,
                passed=True,
                reason="task packet does not require source verification",
            )

        if latest is None:
            return SourceVerificationAssessment(
                mutation_id=mutation_id,
                repository=binding.repository,
                ref=binding.ref,
                commit_sha=outcome.new_ref_head,
                required_checks=requirements,
                verification_required=True,
                latest_status=None,
                latest_receipt_digest=None,
                transport_available=transport_available,
                passed=False,
                reason="required exact-commit source verification has not run",
            )

        exact = (
            latest.repository == binding.repository
            and latest.ref == binding.ref
            and latest.commit_sha == outcome.new_ref_head
            and latest.required_checks == requirements
        )
        if not exact:
            return SourceVerificationAssessment(
                mutation_id=mutation_id,
                repository=binding.repository,
                ref=binding.ref,
                commit_sha=outcome.new_ref_head,
                required_checks=requirements,
                verification_required=True,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                transport_available=transport_available,
                passed=False,
                reason=(
                    "latest source verification does not bind the exact "
                    "current mutation outcome/requirements"
                ),
            )

        if latest.status == "PASS":
            transport = self.transports.get(
                (binding.repository, binding.ref)
            )
            if transport is None:
                return SourceVerificationAssessment(
                    mutation_id=mutation_id,
                    repository=binding.repository,
                    ref=binding.ref,
                    commit_sha=outcome.new_ref_head,
                    required_checks=requirements,
                    verification_required=True,
                    latest_status=latest.status,
                    latest_receipt_digest=latest.receipt_digest,
                    transport_available=False,
                    passed=False,
                    reason=(
                        "stored exact-commit verification passed, but the "
                        "current ref head cannot be refreshed because no "
                        "verification transport is available"
                    ),
                )
            current_ref_head = transport.observe_ref_head()
            if current_ref_head != outcome.new_ref_head:
                return SourceVerificationAssessment(
                    mutation_id=mutation_id,
                    repository=binding.repository,
                    ref=binding.ref,
                    commit_sha=outcome.new_ref_head,
                    required_checks=requirements,
                    verification_required=True,
                    latest_status=latest.status,
                    latest_receipt_digest=latest.receipt_digest,
                    transport_available=True,
                    passed=False,
                    reason=(
                        "source ref moved after the stored PASS observation; "
                        "the exact committed source is no longer current"
                    ),
                    current_ref_head=current_ref_head,
                    current_ref_matches_commit=False,
                )
            return SourceVerificationAssessment(
                mutation_id=mutation_id,
                repository=binding.repository,
                ref=binding.ref,
                commit_sha=outcome.new_ref_head,
                required_checks=requirements,
                verification_required=True,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                transport_available=True,
                passed=True,
                reason=(
                    "exact source verification passed and the live ref still "
                    "names the verified commit"
                ),
                current_ref_head=current_ref_head,
                current_ref_matches_commit=True,
            )

        return SourceVerificationAssessment(
            mutation_id=mutation_id,
            repository=binding.repository,
            ref=binding.ref,
            commit_sha=outcome.new_ref_head,
            required_checks=requirements,
            verification_required=True,
            latest_status=latest.status,
            latest_receipt_digest=latest.receipt_digest,
            transport_available=transport_available,
            passed=False,
            reason=f"exact source verification is {latest.status}",
        )

    def verify_mutation(
        self,
        mutation_id: str,
    ) -> SourceVerificationReceipt:
        binding, outcome = self._validated_outcome(
            mutation_id
        )
        task = self.runtime.tasks.read(binding.task_id)
        if task.closed:
            raise SourceVerificationError(
                "closed task cannot append new source verification evidence"
            )
        requirements = self._requirements(mutation_id)
        if not requirements:
            raise SourceVerificationError(
                "task packet does not require source verification "
                "for this repository/ref"
            )
        transport = self.transports.get(
            (binding.repository, binding.ref)
        )
        if transport is None:
            raise SourceVerificationError(
                "no host-injected source verification transport "
                "for repository/ref"
            )

        # Require accepted current runtime state before an external verification
        # read is treated as qualified task evidence.
        self.runtime.accepted_permit()
        result = transport.verify(
            outcome.new_ref_head,
            requirements,
        )
        if (
            result.repository != binding.repository
            or result.ref != binding.ref
            or result.commit_sha != outcome.new_ref_head
        ):
            raise SourceVerificationError(
                "source verification transport result identity mismatch"
            )
        return self.runtime.source_verifications.append(
            mutation_id=mutation_id,
            result=result,
            required_checks=requirements,
        )

    def recover(
        self,
    ) -> tuple[SourceVerificationAssessment, ...]:
        return tuple(
            self.assess(binding.mutation_id)
            for binding in self.runtime.source_mutation_bindings.all()
        )
