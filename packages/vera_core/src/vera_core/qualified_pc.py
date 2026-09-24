from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from pc_connection.journal import (
    AttemptIdentity,
    AttemptProjection,
    JobJournal,
    JournalState,
)
from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from vera_assurance import EffectFenceError, EffectState

from .pc_execution_binding import (
    PCExecutionBinding,
    PCExecutionBindingStore,
    PCExecutionLease,
    PreparedPCDispatch,
)
from .qualified_runtime import QualifiedVeraRuntime


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PCJournalEventEvidence:
    """Host-supplied event identity/time evidence for the local PCCC journal."""

    local_event_id: str
    server_time_anchor: str
    local_monotonic_ns: int
    record_time: str


@dataclass(frozen=True, slots=True)
class QualifiedPCExecutionResult:
    projection: AttemptProjection
    outbound: Any


@dataclass(frozen=True, slots=True)
class PCExecutionRecoveryAssessment:
    projection: AttemptProjection
    effect_id: str
    effect_state: str | None
    replay_allowed: bool
    recovery_required: bool
    reason: str


class QualifiedPCExecutionAdapter:
    """Join PCCC's local attempt journal to QualifiedVeraRuntime.

    Phase-one PCCC operations are side-effect-class NONE. The adapter therefore
    records CLAIMED -> PREPARING before external execution, then records the
    result only after the lifecycle/trust/effect-fenced runtime returns. Any
    evidence that dispatch may have occurred without a locally recorded result
    is converted to RECOVERY_REQUIRED rather than replayed.

    The PCCC journal remains local evidence: RESULT_OBSERVED is not server
    terminal confirmation. Completion submission and exact server readback stay
    separate explicit methods.
    """

    def __init__(
        self,
        *,
        runtime: QualifiedVeraRuntime,
        journal: JobJournal,
        bindings: PCExecutionBindingStore | None = None,
    ):
        if type(runtime) is not QualifiedVeraRuntime:
            raise TypeError("runtime must be exact QualifiedVeraRuntime")
        if type(journal) is not JobJournal:
            raise TypeError("journal must be exact JobJournal")
        self.runtime = runtime
        self.journal = journal
        if bindings is not None and type(bindings) is not PCExecutionBindingStore:
            raise TypeError("bindings must be exact PCExecutionBindingStore")
        self.bindings = bindings

    @staticmethod
    def _event(
        source: Callable[[str], PCJournalEventEvidence],
        stage: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        evidence = source(stage)
        if type(evidence) is not PCJournalEventEvidence:
            raise TypeError(
                "event source must return exact PCJournalEventEvidence"
            )
        return {
            "local_event_id": evidence.local_event_id,
            "payload_digest": sha256_hex(canonical_json_bytes(payload)),
            "server_time_anchor": evidence.server_time_anchor,
            "local_monotonic_ns": evidence.local_monotonic_ns,
            "record_time": evidence.record_time,
        }

    @staticmethod
    def identity(
        prepared: PreparedPCDispatch,
        lease: PCExecutionLease,
    ) -> AttemptIdentity:
        if type(prepared) is not PreparedPCDispatch:
            raise TypeError("prepared must be exact PreparedPCDispatch")
        if type(lease) is not PCExecutionLease:
            raise TypeError("lease must be exact PCExecutionLease")
        job = prepared.job
        authorization = prepared.authorization
        identity = AttemptIdentity(
            job_id=lease.job_id,
            attempt_id=lease.attempt_id,
            host_id=job.host_id,
            claim_generation=lease.claim_generation,
            lease_id=lease.lease_id,
            lease_fence=lease.lease_fence,
            job_digest=prepared.job_digest,
            authorization_id=job.authorization_id,
            authorization_revision=job.authorization_revision,
            issuer_revocation_epoch=authorization.issuer_revocation_epoch,
            host_revocation_epoch=authorization.host_revocation_epoch,
            operation_id=job.operation_id,
            operation_version=job.operation_version,
            retry_class=job.retry_class,
            side_effect_class="NONE",
        )
        identity.validate()
        return identity

    @staticmethod
    def effect_id(prepared: PreparedPCDispatch) -> str:
        return f"pc:{prepared.job.envelope_id}"

    def assess(
        self,
        prepared: PreparedPCDispatch,
        lease: PCExecutionLease,
    ) -> PCExecutionRecoveryAssessment | None:
        identity = self.identity(prepared, lease)
        projection = self.journal.get(identity.job_id, identity.attempt_id)
        if projection is None:
            return None

        effect_id = self.effect_id(prepared)
        try:
            effect = self.runtime.fence.read(effect_id)
        except KeyError:
            effect = None

        effect_state = None if effect is None else effect.state.value
        if projection.local_state in {
            JournalState.TERMINAL_CONFIRMED,
            JournalState.ABANDONED,
        }:
            return PCExecutionRecoveryAssessment(
                projection=projection,
                effect_id=effect_id,
                effect_state=effect_state,
                replay_allowed=False,
                recovery_required=False,
                reason="local journal attempt is terminal",
            )

        if projection.local_state is JournalState.CLAIMED and effect is None:
            return PCExecutionRecoveryAssessment(
                projection=projection,
                effect_id=effect_id,
                effect_state=None,
                replay_allowed=True,
                recovery_required=False,
                reason="claim exists but preparation/external dispatch has not begun",
            )

        if projection.local_state is JournalState.PREPARING and effect is None:
            return PCExecutionRecoveryAssessment(
                projection=projection,
                effect_id=effect_id,
                effect_state=None,
                replay_allowed=True,
                recovery_required=False,
                reason="preparation is durable and no external effect record exists",
            )

        if (
            projection.local_state is JournalState.RESULT_OBSERVED
            and effect is not None
            and effect.state in {
                EffectState.COMMITTED,
                EffectState.RECONCILED_COMMITTED,
            }
        ):
            return PCExecutionRecoveryAssessment(
                projection=projection,
                effect_id=effect_id,
                effect_state=effect_state,
                replay_allowed=False,
                recovery_required=False,
                reason="local result and committed external effect evidence agree",
            )

        return PCExecutionRecoveryAssessment(
            projection=projection,
            effect_id=effect_id,
            effect_state=effect_state,
            replay_allowed=False,
            recovery_required=True,
            reason=(
                "journal/effect evidence indicates dispatch may have occurred; "
                "exact reconciliation is required before replay"
            ),
        )

    def execute(
        self,
        prepared: PreparedPCDispatch,
        *,
        authority_proof: Any,
        lease: PCExecutionLease,
        event_source: Callable[[str], PCJournalEventEvidence],
        execute: Callable[[], T],
    ) -> QualifiedPCExecutionResult:
        identity = self.identity(prepared, lease)
        if self.bindings is not None:
            self.bindings.bind(prepared, lease)
        assessment = self.assess(prepared, lease)

        if assessment is None:
            projection = self.journal.record_claim(
                identity,
                **self._event(
                    event_source,
                    "CLAIM_RECORDED",
                    {
                        "schema": "VERA_MONO_PC_EXECUTION_EVENT_V1",
                        "stage": "CLAIM_RECORDED",
                        "job_digest": prepared.job_digest,
                        "authorization_digest": prepared.authorization_digest,
                        "lifecycle_permit_digest": prepared.permit.permit_digest,
                        "authority_subject": prepared.authority_subject,
                        "claim_generation": lease.claim_generation,
                        "lease_fence": lease.lease_fence,
                    },
                ),
            )
        else:
            projection = assessment.projection
            if assessment.recovery_required:
                if projection.local_state is not JournalState.RECOVERY_REQUIRED:
                    projection = self.journal.require_recovery(
                        identity,
                        **self._event(
                            event_source,
                            "RECOVERY_REQUIRED",
                            {
                                "schema": "VERA_MONO_PC_EXECUTION_EVENT_V1",
                                "stage": "RECOVERY_REQUIRED",
                                "reason": assessment.reason,
                                "effect_state": assessment.effect_state,
                                "job_digest": prepared.job_digest,
                                "lifecycle_permit_digest": (
                                    prepared.permit.permit_digest
                                ),
                            },
                        ),
                    )
                raise EffectFenceError(
                    "PC attempt requires reconciliation before external replay"
                )
            if not assessment.replay_allowed:
                raise EffectFenceError(
                    "PC attempt cannot be externally replayed from its current state"
                )

        if projection.local_state is JournalState.CLAIMED:
            projection = self.journal.start_preparation(
                identity,
                **self._event(
                    event_source,
                    "PREPARATION_STARTED",
                    {
                        "schema": "VERA_MONO_PC_EXECUTION_EVENT_V1",
                        "stage": "PREPARATION_STARTED",
                        "job_digest": prepared.job_digest,
                        "authorization_digest": prepared.authorization_digest,
                        "lifecycle_permit_digest": prepared.permit.permit_digest,
                    },
                ),
            )

        try:
            outbound = self.runtime.dispatch_pc_job(
                prepared,
                authority_proof=authority_proof,
                execute=execute,
            )
        except BaseException:
            try:
                effect = self.runtime.fence.read(self.effect_id(prepared))
            except KeyError:
                effect = None
            if effect is not None and effect.state in {
                EffectState.EXECUTING,
                EffectState.ATTEMPTED_UNKNOWN,
                EffectState.COMMITTED,
                EffectState.RECONCILED_COMMITTED,
            }:
                current = self.journal.get(identity.job_id, identity.attempt_id)
                if (
                    current is not None
                    and current.local_state is not JournalState.RECOVERY_REQUIRED
                ):
                    self.journal.require_recovery(
                        identity,
                        **self._event(
                            event_source,
                            "RECOVERY_REQUIRED",
                            {
                                "schema": "VERA_MONO_PC_EXECUTION_EVENT_V1",
                                "stage": "RECOVERY_REQUIRED",
                                "effect_state": effect.state.value,
                                "effect_request_digest": effect.request_digest,
                                "job_digest": prepared.job_digest,
                                "lifecycle_permit_digest": (
                                    prepared.permit.permit_digest
                                ),
                            },
                        ),
                    )
            raise

        projection = self.journal.record_result(
            identity,
            result_digest=outbound.result_digest,
            **self._event(
                event_source,
                "RESULT_RECORDED",
                {
                    "schema": "VERA_MONO_PC_EXECUTION_EVENT_V1",
                    "stage": "RESULT_RECORDED",
                    "effect_request_digest": outbound.request_digest,
                    "effect_result_digest": outbound.result_digest,
                    "lifecycle_permit_digest": outbound.lifecycle_permit_digest,
                },
            ),
        )
        return QualifiedPCExecutionResult(
            projection=projection,
            outbound=outbound,
        )

    def submit_completion(
        self,
        prepared: PreparedPCDispatch,
        *,
        lease: PCExecutionLease,
        receipt_id: str,
        receipt_digest: str,
        server_request_id: str,
        event_source: Callable[[str], PCJournalEventEvidence],
    ) -> AttemptProjection:
        identity = self.identity(prepared, lease)
        if self.bindings is not None:
            self.bindings.bind(prepared, lease)
        current = self.journal.get(identity.job_id, identity.attempt_id)
        if current is None or current.local_state is not JournalState.RESULT_OBSERVED:
            raise EffectFenceError(
                "local PC result must be observed before completion submission"
            )
        return self.journal.submit_completion(
            identity,
            receipt_id=receipt_id,
            receipt_digest=receipt_digest,
            server_request_id=server_request_id,
            **self._event(
                event_source,
                "COMPLETION_SUBMITTED",
                {
                    "schema": "VERA_MONO_PC_EXECUTION_EVENT_V1",
                    "stage": "COMPLETION_SUBMITTED",
                    "result_digest": current.result_digest,
                    "receipt_digest": receipt_digest,
                    "server_request_id": server_request_id,
                },
            ),
        )

    def recover_bound_attempts(
        self,
    ) -> tuple[
        tuple[PCExecutionBinding, PCExecutionRecoveryAssessment | None],
        ...,
    ]:
        if self.bindings is None:
            raise ValueError(
                "recover_bound_attempts requires a durable PCExecutionBindingStore"
            )
        return tuple(
            (
                binding,
                self.assess(binding.prepared, binding.lease),
            )
            for binding in self.bindings.all()
        )

    def confirm_terminal_readback(
        self,
        prepared: PreparedPCDispatch,
        *,
        lease: PCExecutionLease,
        server_readback_receipt_id: str,
        server_readback_digest: str,
        event_source: Callable[[str], PCJournalEventEvidence],
    ) -> AttemptProjection:
        identity = self.identity(prepared, lease)
        if self.bindings is not None:
            self.bindings.bind(prepared, lease)
        current = self.journal.get(identity.job_id, identity.attempt_id)
        if current is None or current.local_state is not JournalState.COMPLETING:
            raise EffectFenceError(
                "PC completion must be submitted before terminal readback"
            )
        return self.journal.confirm_terminal_readback(
            identity,
            server_readback_receipt_id=server_readback_receipt_id,
            server_readback_digest=server_readback_digest,
            expected_result_digest=current.result_digest,
            expected_receipt_digest=current.terminal_receipt_digest,
            **self._event(
                event_source,
                "TERMINAL_READBACK_CONFIRMED",
                {
                    "schema": "VERA_MONO_PC_EXECUTION_EVENT_V1",
                    "stage": "TERMINAL_READBACK_CONFIRMED",
                    "expected_result_digest": current.result_digest,
                    "expected_receipt_digest": current.terminal_receipt_digest,
                    "server_readback_digest": server_readback_digest,
                },
            ),
        )
