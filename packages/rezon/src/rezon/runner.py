from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from uuid import uuid4

from .admission import AdmissionError, admit_execution_result
from .envelopes import (
    AuthorityVerificationEvidence,
    AuthorityVerificationPolicy,
    TaskEnvelope,
    task_envelope_contract_is_exact,
)
from .episode import Episode
from .epistemics import PropositionKind, source_ref_version_bindings
from .nodes import (
    NodeDescriptor,
    VerificationStatus,
    execution_result_contract_is_exact,
    node_descriptor_contract_is_exact,
)
from .provenance import (
    canonical_episode_snapshot_digest,
    canonical_output_digest,
)
from .receipts import (
    EffectState,
    FailureState,
    IndependenceMetadata,
    IndependenceVerificationEvidence,
    IndependenceVerificationPolicy,
    ResultReceipt,
)
from .scheduler import Budget, DeterministicScheduler, ScheduleAction
from .trace import ExecutionTrace, TraceRecord
from .visibility import (
    VisibilityPolicy,
    build_execution_view,
    visibility_policy_contract_is_exact,
)


@dataclass(frozen=True)
class RunnerNode:
    descriptor: NodeDescriptor
    executor: object | None
    visibility: VisibilityPolicy
    independence: IndependenceMetadata = IndependenceMetadata()
    independence_policy: IndependenceVerificationPolicy | None = None
    authority_policy: AuthorityVerificationPolicy | None = None


@dataclass(frozen=True)
class RunOutcome:
    receipt: ResultReceipt
    trace: ExecutionTrace


class _ExecutorEpisodeMutationError(RuntimeError):
    pass


class _InvalidExecutionResultError(RuntimeError):
    pass


def _freeze_independence_policy(policy):
    if type(policy) is not IndependenceVerificationPolicy:
        return policy
    evidence_values = policy.verified_evidence
    if type(evidence_values) is not tuple:
        return replace(policy)
    frozen_evidence = tuple(
        replace(evidence)
        if type(evidence) is IndependenceVerificationEvidence
        else evidence
        for evidence in evidence_values
    )
    return IndependenceVerificationPolicy(frozen_evidence)


def _freeze_authority_policy(policy):
    if type(policy) is not AuthorityVerificationPolicy:
        return policy
    evidence_values = policy.verified_evidence
    if type(evidence_values) is not tuple:
        return replace(policy)
    frozen_evidence = tuple(
        replace(evidence)
        if type(evidence) is AuthorityVerificationEvidence
        else evidence
        for evidence in evidence_values
    )
    return AuthorityVerificationPolicy(frozen_evidence)


def _freeze_runner_node(node: RunnerNode) -> RunnerNode:
    return RunnerNode(
        descriptor=replace(node.descriptor),
        executor=node.executor,
        visibility=replace(node.visibility),
        independence=replace(node.independence),
        independence_policy=_freeze_independence_policy(node.independence_policy),
        authority_policy=_freeze_authority_policy(node.authority_policy),
    )


def _dedupe(items: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _view_source_refs(view) -> tuple[str, ...]:
    refs: list[str] = []
    for proposition in view.propositions:
        refs.extend(proposition.source_refs)
    for relation in view.relations:
        refs.extend(relation.source_refs)
    return _dedupe(refs)


def _view_governed_refs(view) -> tuple[str, ...]:
    refs: list[str] = [
        *(p.proposition_id for p in view.propositions),
        *(r.relation_id for r in view.relations),
    ]
    refs.extend(_view_source_refs(view))
    return _dedupe(refs)


def _view_source_versions(view) -> tuple[str, ...]:
    versions: list[str] = []
    for proposition in view.propositions:
        versions.extend(proposition.source_versions)
    for relation in view.relations:
        versions.extend(relation.source_versions)
    return _dedupe(versions)


def _view_source_bindings(view) -> tuple[tuple[str, str], ...]:
    bindings: list[tuple[str, str]] = []
    for source in (*view.propositions, *view.relations):
        source_bindings = source_ref_version_bindings(
            source.source_refs,
            source.source_versions,
        )
        if source_bindings is None:
            continue
        for binding in source_bindings:
            if binding not in bindings:
                bindings.append(binding)
    return tuple(bindings)


def _view_potentially_consumed_evidence_refs(view) -> tuple[str, ...]:
    refs: list[str] = []
    for proposition in view.propositions:
        if proposition.kind is not PropositionKind.EVIDENCE:
            continue
        refs.append(proposition.proposition_id)
        refs.extend(proposition.source_refs)
    return _dedupe(refs)


def _view_potentially_consumed_evidence_versions(view) -> tuple[str, ...]:
    versions: list[str] = []
    for proposition in view.propositions:
        if proposition.kind is not PropositionKind.EVIDENCE:
            continue
        versions.extend(proposition.source_versions)
    return _dedupe(versions)


def _independence_view_is_blind(view, descriptor: NodeDescriptor) -> bool:
    protected_kinds = set(descriptor.independence_blind_kinds)
    protected_ids = set(descriptor.independence_blind_ids)

    # Kernel V0 has no typed safe-shared worker-proposition class. Any visible
    # prior worker output is therefore answer-bearing by default, regardless of
    # its proposition kind.
    if any(
        proposition.producer_execution_id is not None
        for proposition in view.propositions
    ):
        return False

    if any(
        proposition.kind in protected_kinds
        or proposition.proposition_id in protected_ids
        for proposition in view.propositions
    ):
        return False

    # Kernel V0 has no typed safe-shared worker-relation class. Fail closed
    # rather than exposing peer-produced relation identity/type/roles as an
    # answer-bearing side channel to an independence-required worker.
    if any(
        relation.producer_execution_id is not None
        for relation in view.relations
    ):
        return False
    return True


class EpisodeRunner:
    def __init__(self, nodes: tuple[RunnerNode, ...], budget_limit: int = 8):
        self.nodes = nodes
        self.budget_limit = budget_limit
        self.scheduler = DeterministicScheduler()

    def run(
        self,
        episode: Episode,
        task_id: str,
        *,
        task_envelope: TaskEnvelope | None = None,
    ) -> RunOutcome:
        if type(task_id) is not str or not task_id:
            receipt = ResultReceipt(
                task_id="runner:invalid_task_id",
                episode_version="runner:unbound_episode",
                unresolved=("runner:invalid_task_id",),
                failures=(FailureState.CONTRACT_VIOLATION,),
                effect_state=EffectState.PLAN,
            )
            return RunOutcome(receipt, ExecutionTrace())

        if type(episode) is not Episode:
            receipt = ResultReceipt(
                task_id=task_id,
                episode_version="runner:invalid_episode",
                unresolved=("runner:invalid_episode_contract",),
                failures=(FailureState.CONTRACT_VIOLATION,),
                effect_state=EffectState.PLAN,
            )
            return RunOutcome(receipt, ExecutionTrace())

        if (
            task_envelope is not None
            and not task_envelope_contract_is_exact(task_envelope)
        ):
            receipt = ResultReceipt(
                task_id=task_id,
                episode_version=Episode.snapshot(episode).version_ref,
                unresolved=("task_envelope:invalid_contract",),
                failures=(FailureState.CONTRACT_VIOLATION,),
                effect_state=EffectState.PLAN,
            )
            return RunOutcome(receipt, ExecutionTrace())

        governed_task_envelope = (
            replace(task_envelope)
            if task_envelope is not None
            else None
        )
        task_digest = (
            governed_task_envelope.digest
            if governed_task_envelope is not None
            else None
        )
        if (
            governed_task_envelope is not None
            and governed_task_envelope.task_id != task_id
        ):
            receipt = ResultReceipt(
                task_id=task_id,
                episode_version=Episode.snapshot(episode).version_ref,
                unresolved=("task_envelope:mismatched_task_id",),
                failures=(FailureState.CONTRACT_VIOLATION,),
                effect_state=EffectState.PLAN,
                task_envelope_digest=task_digest,
            )
            return RunOutcome(receipt, ExecutionTrace())

        candidate_nodes = self.nodes
        if (
            type(candidate_nodes) is not tuple
            or any(
                type(node) is not RunnerNode
                or not node_descriptor_contract_is_exact(node.descriptor)
                or not visibility_policy_contract_is_exact(node.visibility)
                or type(node.independence) is not IndependenceMetadata
                for node in candidate_nodes
            )
        ):
            receipt = ResultReceipt(
                task_id=task_id,
                episode_version=Episode.snapshot(episode).version_ref,
                unresolved=("runner:invalid_node_contract",),
                failures=(FailureState.CONTRACT_VIOLATION,),
                effect_state=EffectState.PLAN,
                task_envelope_digest=task_digest,
            )
            return RunOutcome(receipt, ExecutionTrace())

        governed_nodes = tuple(
            _freeze_runner_node(node)
            for node in candidate_nodes
        )

        if type(self.budget_limit) is not int or self.budget_limit < 0:
            receipt = ResultReceipt(
                task_id=task_id,
                episode_version=Episode.snapshot(episode).version_ref,
                unresolved=("runner:invalid_budget_contract",),
                failures=(FailureState.CONTRACT_VIOLATION,),
                effect_state=EffectState.PLAN,
                task_envelope_digest=task_digest,
            )
            return RunOutcome(receipt, ExecutionTrace())

        effective_budget = self.budget_limit
        if (
            governed_task_envelope is not None
            and governed_task_envelope.resource_budget is not None
        ):
            effective_budget = min(
                effective_budget,
                governed_task_envelope.resource_budget,
            )

        # Scheduling is an internal governed control. Do not dispatch through
        # the mutable public scheduler attribute, which callers can replace or
        # shadow between construction and execution.
        governed_scheduler = DeterministicScheduler()

        completed: list[str] = []
        failures: list[FailureState] = []
        unresolved: list[str] = []
        records: list[TraceRecord] = []
        prior_independent: list[IndependenceMetadata] = []
        prior_independent_source_versions: list[tuple[str, ...]] = []
        receipt_source_versions: list[str] = []
        used = 0

        def add_failure(failure: FailureState) -> None:
            if failure not in failures:
                failures.append(failure)

        def add_source_versions(source_versions: tuple[str, ...]) -> None:
            for source_version in source_versions:
                if source_version not in receipt_source_versions:
                    receipt_source_versions.append(source_version)

        def add_preflight_trace(
            execution_id: str,
            runner_node: RunnerNode,
            audit_view,
            canonical_episode_snapshot_digest: str,
            failure: FailureState,
        ) -> None:
            task_specification_digest = (
                audit_view.task_specification.digest
                if audit_view.task_specification is not None
                else None
            )
            executor_episode_version = (
                "independent@0"
                if runner_node.descriptor.independence_required
                else audit_view.episode_version
            )
            records.append(TraceRecord(
                execution_id=execution_id,
                node_id=runner_node.descriptor.node_id,
                episode_version=audit_view.episode_version,
                visible_proposition_ids=tuple(p.proposition_id for p in audit_view.propositions),
                blinded_proposition_ids=audit_view.blinded_proposition_ids,
                visible_relation_ids=tuple(r.relation_id for r in audit_view.relations),
                blinded_relation_ids=audit_view.blinded_relation_ids,
                emitted_proposition_ids=(),
                independence_demonstrated=False,
                task_envelope_digest=task_digest,
                executor_task_specification_digest=task_specification_digest,
                executor_episode_version=executor_episode_version,
                canonical_producer_execution_id=None,
                canonical_episode_snapshot_digest=canonical_episode_snapshot_digest,
                canonical_output_digest=None,
                duration_seconds=0.0,
                failures=(failure,),
            ))

        while True:
            decision = governed_scheduler.next(
                Episode.snapshot(episode),
                tuple(node.descriptor for node in governed_nodes),
                tuple(completed),
                Budget(effective_budget, used),
            )
            if decision.action is ScheduleAction.TERMINATE:
                if decision.failure is not None:
                    add_failure(decision.failure)
                    if decision.reason == "duplicate_node_id":
                        unresolved.append("scheduler:duplicate_node_id")
                break

            if (
                decision.node_index is None
                or decision.node_index < 0
                or decision.node_index >= len(governed_nodes)
            ):
                add_failure(FailureState.CONTRACT_VIOLATION)
                unresolved.append("scheduler:invalid_node_identity")
                break
            runner_node = governed_nodes[decision.node_index]
            if runner_node.descriptor.node_id != decision.node_id:
                add_failure(FailureState.CONTRACT_VIOLATION)
                unresolved.append("scheduler:descriptor_identity_mismatch")
                break
            required_authority = tuple(runner_node.descriptor.required_authority)
            if required_authority:
                # Kernel V0 has no independently governed authority verifier.
                # Caller-supplied envelope strings or in-process policy objects
                # are declarations/evidence candidates only and cannot authorize
                # protected execution. Fail closed until that boundary is
                # separately qualified.
                add_failure(FailureState.CONTRACT_VIOLATION)
                unresolved.append(f"authority:{runner_node.descriptor.node_id}")
                break

            if runner_node.executor is None:
                add_failure(FailureState.UNAVAILABLE)
                unresolved.append(
                    f"mandatory:{runner_node.descriptor.node_id}"
                    if runner_node.descriptor.mandatory_verification
                    else f"node:{runner_node.descriptor.node_id}"
                )
                completed.append(runner_node.descriptor.node_id)
                if runner_node.descriptor.mandatory_verification:
                    break
                continue

            if runner_node.descriptor.independence_required:
                execution_id = (
                    f"independent:exec:{runner_node.descriptor.node_id}:"
                    f"{uuid4().hex}"
                )
            else:
                execution_id = (
                    f"{task_id}:exec:{len(records) + 1}:"
                    f"{runner_node.descriptor.node_id}"
                )
            execution_snapshot = Episode.snapshot(episode)
            canonical_snapshot_digest = canonical_episode_snapshot_digest(
                execution_snapshot
            )
            audit_view = build_execution_view(
                execution_id,
                execution_snapshot,
                runner_node.visibility,
                runner_node.independence,
                governed_task_envelope,
            )
            executor_task_specification = audit_view.task_specification
            executor_task_specification_digest = (
                executor_task_specification.digest
                if executor_task_specification is not None
                else None
            )
            executor_episode_version = (
                "independent@0"
                if runner_node.descriptor.independence_required
                else audit_view.episode_version
            )
            attempted_output_digest = None
            canonical_producer_execution_id = None
            executor_view = replace(
                audit_view,
                episode_version=executor_episode_version,
                blinded_proposition_ids=(),
                blinded_relation_ids=(),
                task_envelope=(
                    None
                    if runner_node.descriptor.independence_required
                    else (
                        replace(governed_task_envelope)
                        if governed_task_envelope is not None
                        else None
                    )
                ),
                independence=(
                    IndependenceMetadata()
                    if runner_node.descriptor.independence_required
                    else audit_view.independence
                ),
            )

            visible_refs = {
                *(p.proposition_id for p in audit_view.propositions),
                *(r.relation_id for r in audit_view.relations),
            }
            if decision.target_id is not None and decision.target_id not in visible_refs:
                add_failure(FailureState.CONTRACT_VIOLATION)
                unresolved.append(f"scheduled_target:{decision.target_id}")
                add_preflight_trace(
                    execution_id,
                    runner_node,
                    audit_view,
                    canonical_snapshot_digest,
                    FailureState.CONTRACT_VIOLATION,
                )
                completed.append(runner_node.descriptor.node_id)
                used += 1
                break

            accepted_input_kinds = set(runner_node.descriptor.accepted_input_kinds)
            if accepted_input_kinds and any(
                proposition.kind not in accepted_input_kinds
                for proposition in audit_view.propositions
            ):
                add_failure(FailureState.CONTRACT_VIOLATION)
                unresolved.append(f"input_contract:{runner_node.descriptor.node_id}")
                add_preflight_trace(
                    execution_id,
                    runner_node,
                    audit_view,
                    canonical_snapshot_digest,
                    FailureState.CONTRACT_VIOLATION,
                )
                completed.append(runner_node.descriptor.node_id)
                used += 1
                break

            independence_ok = False
            if runner_node.descriptor.independence_required:
                # Kernel V0 strong independence permits the shared task
                # specification but not auxiliary dynamic context. TaskEnvelope
                # context_refs are an explicit shared-context channel and are
                # therefore incompatible with an independence_required run.
                if (
                    governed_task_envelope is not None
                    and governed_task_envelope.context_refs
                ):
                    add_failure(FailureState.CONTRACT_VIOLATION)
                    unresolved.append(
                        f"independence_context:{runner_node.descriptor.node_id}"
                    )
                    add_preflight_trace(
                        execution_id,
                        runner_node,
                        audit_view,
                        canonical_snapshot_digest,
                        FailureState.CONTRACT_VIOLATION,
                    )
                    break

                independence = runner_node.independence
                policy = runner_node.independence_policy
                exact_independence_metadata = (
                    type(independence) is IndependenceMetadata
                )
                exact_independence_policy = (
                    type(policy) is IndependenceVerificationPolicy
                )
                claim_complete = bool(
                    exact_independence_metadata
                    and independence.is_demonstrably_independent
                )
                if not claim_complete:
                    add_failure(FailureState.CONTRACT_VIOLATION)
                    unresolved.append(f"independence:{runner_node.descriptor.node_id}")
                    break

                policy_verified = bool(
                    exact_independence_policy
                    and policy.verify(independence)
                )
                potentially_consumed_evidence = _view_potentially_consumed_evidence_refs(
                    audit_view
                )
                evidence_attestation_matches_view = (
                    len(independence.consumed_evidence_refs)
                    == len(set(independence.consumed_evidence_refs))
                    and set(independence.consumed_evidence_refs)
                    == set(potentially_consumed_evidence)
                )
                pairwise_metadata_ok = all(
                    independence.demonstrably_independent_from(previous)
                    for previous in prior_independent
                )
                potentially_consumed_evidence_versions = (
                    _view_potentially_consumed_evidence_versions(audit_view)
                )
                pairwise_source_versions_ok = all(
                    not (
                        set(potentially_consumed_evidence_versions)
                        & set(previous_versions)
                    )
                    for previous_versions in prior_independent_source_versions
                )
                pairwise_ok = (
                    pairwise_metadata_ok
                    and pairwise_source_versions_ok
                )
                candidate_blind = _independence_view_is_blind(
                    audit_view,
                    runner_node.descriptor,
                )
                independence_ok = bool(
                    policy_verified
                    and evidence_attestation_matches_view
                    and pairwise_ok
                    and candidate_blind
                )
                if not independence_ok:
                    add_failure(FailureState.CONTRACT_VIOLATION)
                    unresolved.append(f"independence:{runner_node.descriptor.node_id}")
                    add_preflight_trace(
                        execution_id,
                        runner_node,
                        audit_view,
                        canonical_snapshot_digest,
                        FailureState.CONTRACT_VIOLATION,
                    )
                    break

            executor = runner_node.executor

            input_source_refs = _view_source_refs(audit_view)
            input_source_versions = _view_source_versions(audit_view)
            input_source_bindings = _view_source_bindings(audit_view)
            governed_refs = _view_governed_refs(audit_view)
            add_source_versions(input_source_versions)

            started = perf_counter()
            try:
                with Episode.atomic_mutation(episode):
                    active_executor = executor
                    if (
                        decision.target_id is not None
                        and hasattr(active_executor, "target_hypothesis_id")
                    ):
                        active_executor = type(active_executor)(decision.target_id)
                    result = active_executor.execute(
                        executor_view,
                        episode.episode_id,
                    )
                    if not execution_result_contract_is_exact(result):
                        raise _InvalidExecutionResultError(
                            "executor returned an invalid ExecutionResult contract"
                        )
                    if (
                        canonical_episode_snapshot_digest(Episode.snapshot(episode))
                        != canonical_snapshot_digest
                    ):
                        raise _ExecutorEpisodeMutationError(
                            "executor mutated canonical episode during execution"
                        )
            except _InvalidExecutionResultError:
                duration = perf_counter() - started
                add_failure(FailureState.CONTRACT_VIOLATION)
                unresolved.append(f"execution_result:invalid_contract:{execution_id}")
                records.append(TraceRecord(
                    execution_id=execution_id,
                    node_id=runner_node.descriptor.node_id,
                    episode_version=audit_view.episode_version,
                    visible_proposition_ids=tuple(p.proposition_id for p in audit_view.propositions),
                    blinded_proposition_ids=audit_view.blinded_proposition_ids,
                    visible_relation_ids=tuple(r.relation_id for r in audit_view.relations),
                    blinded_relation_ids=audit_view.blinded_relation_ids,
                    emitted_proposition_ids=(),
                    independence_demonstrated=independence_ok,
                    task_envelope_digest=task_digest,
                    executor_task_specification_digest=executor_task_specification_digest,
                    executor_episode_version=executor_episode_version,
                    canonical_producer_execution_id=None,
                    canonical_episode_snapshot_digest=canonical_snapshot_digest,
                    canonical_output_digest=None,
                    source_refs=input_source_refs,
                    source_versions=input_source_versions,
                    duration_seconds=duration,
                    failures=(FailureState.CONTRACT_VIOLATION,),
                ))
                completed.append(runner_node.descriptor.node_id)
                used += 1
                if runner_node.descriptor.mandatory_verification:
                    break
                continue
            except _ExecutorEpisodeMutationError:
                duration = perf_counter() - started
                add_failure(FailureState.CONTRACT_VIOLATION)
                unresolved.append(f"executor_episode_mutation:{execution_id}")
                records.append(TraceRecord(
                    execution_id=execution_id,
                    node_id=runner_node.descriptor.node_id,
                    episode_version=audit_view.episode_version,
                    visible_proposition_ids=tuple(p.proposition_id for p in audit_view.propositions),
                    blinded_proposition_ids=audit_view.blinded_proposition_ids,
                    visible_relation_ids=tuple(r.relation_id for r in audit_view.relations),
                    blinded_relation_ids=audit_view.blinded_relation_ids,
                    emitted_proposition_ids=(),
                    independence_demonstrated=independence_ok,
                    task_envelope_digest=task_digest,
                    executor_task_specification_digest=executor_task_specification_digest,
                    executor_episode_version=executor_episode_version,
                    canonical_producer_execution_id=None,
                    canonical_episode_snapshot_digest=canonical_snapshot_digest,
                    canonical_output_digest=None,
                    source_refs=input_source_refs,
                    source_versions=input_source_versions,
                    duration_seconds=duration,
                    failures=(FailureState.CONTRACT_VIOLATION,),
                ))
                completed.append(runner_node.descriptor.node_id)
                used += 1
                if runner_node.descriptor.mandatory_verification:
                    break
                continue
            except Exception:
                duration = perf_counter() - started
                add_failure(FailureState.ATTEMPTED_UNKNOWN)
                unresolved.append(f"execution:{execution_id}")
                records.append(TraceRecord(
                    execution_id=execution_id,
                    node_id=runner_node.descriptor.node_id,
                    episode_version=audit_view.episode_version,
                    visible_proposition_ids=tuple(p.proposition_id for p in audit_view.propositions),
                    blinded_proposition_ids=audit_view.blinded_proposition_ids,
                    visible_relation_ids=tuple(r.relation_id for r in audit_view.relations),
                    blinded_relation_ids=audit_view.blinded_relation_ids,
                    emitted_proposition_ids=(),
                    independence_demonstrated=independence_ok,
                    task_envelope_digest=task_digest,
                    executor_task_specification_digest=executor_task_specification_digest,
                    executor_episode_version=executor_episode_version,
                    canonical_producer_execution_id=None,
                    canonical_episode_snapshot_digest=canonical_snapshot_digest,
                    canonical_output_digest=None,
                    source_refs=input_source_refs,
                    source_versions=input_source_versions,
                    duration_seconds=duration,
                    failures=(FailureState.ATTEMPTED_UNKNOWN,),
                ))
                completed.append(runner_node.descriptor.node_id)
                used += 1
                if runner_node.descriptor.mandatory_verification:
                    break
                continue
            duration = perf_counter() - started

            attempted_output_digest = canonical_output_digest(result)

            reported_source_refs = _dedupe(list(result.source_refs))
            reported_source_versions = _dedupe(list(result.source_versions))

            execution_failures = list(result.failures)
            admitted_ids: tuple[str, ...] = ()
            admission_ok = False
            verification_precondition_ok = True

            if result.failures:
                for failure in result.failures:
                    add_failure(failure)
                unresolved.append(f"execution_result:{execution_id}")
                if runner_node.descriptor.mandatory_verification:
                    unresolved.append(f"verification:{execution_id}")
                verification_precondition_ok = False

            if runner_node.descriptor.mandatory_verification and not result.failures:
                expected_targets = tuple(runner_node.descriptor.verification_target_ids)
                verification_targets = tuple(result.verification_target_ids)
                if result.verification_status is not VerificationStatus.PASSED:
                    add_failure(FailureState.INSUFFICIENT_EVIDENCE)
                    if FailureState.INSUFFICIENT_EVIDENCE not in execution_failures:
                        execution_failures.append(FailureState.INSUFFICIENT_EVIDENCE)
                    unresolved.append(f"verification:{execution_id}")
                    verification_precondition_ok = False
                elif verification_targets != expected_targets:
                    add_failure(FailureState.CONTRACT_VIOLATION)
                    if FailureState.CONTRACT_VIOLATION not in execution_failures:
                        execution_failures.append(FailureState.CONTRACT_VIOLATION)
                    unresolved.append(f"verification:{execution_id}")
                    verification_precondition_ok = False
                elif any(target_id not in visible_refs for target_id in expected_targets):
                    add_failure(FailureState.CONTRACT_VIOLATION)
                    if FailureState.CONTRACT_VIOLATION not in execution_failures:
                        execution_failures.append(FailureState.CONTRACT_VIOLATION)
                    unresolved.append(f"verification:{execution_id}")
                    verification_precondition_ok = False
                elif not any(
                    proposition.kind is PropositionKind.TEST_RESULT
                    and set(expected_targets).issubset(set(proposition.source_refs))
                    for proposition in result.emitted_propositions
                ):
                    add_failure(FailureState.CONTRACT_VIOLATION)
                    if FailureState.CONTRACT_VIOLATION not in execution_failures:
                        execution_failures.append(FailureState.CONTRACT_VIOLATION)
                    unresolved.append(f"verification:{execution_id}")
                    verification_precondition_ok = False

            if not result.failures and verification_precondition_ok:
                try:
                    admission_receipt = admit_execution_result(
                        episode,
                        runner_node.descriptor,
                        result,
                        expected_execution_id=execution_id,
                        expected_episode_snapshot_digest=canonical_snapshot_digest,
                        task_specification=executor_task_specification,
                        allowed_source_refs=governed_refs,
                        allowed_source_versions=input_source_versions,
                        allowed_source_bindings=input_source_bindings,
                    )
                    admitted_ids = tuple(p.proposition_id for p in result.emitted_propositions)
                    admission_ok = True
                    attempted_output_digest = admission_receipt.canonical_output_digest
                    canonical_producer_execution_id = (
                        admission_receipt.canonical_producer_execution_id
                    )
                except AdmissionError:
                    add_failure(FailureState.CONTRACT_VIOLATION)
                    if FailureState.CONTRACT_VIOLATION not in execution_failures:
                        execution_failures.append(FailureState.CONTRACT_VIOLATION)
                    unresolved.append(f"admission:{execution_id}")
                    if runner_node.descriptor.mandatory_verification:
                        unresolved.append(f"verification:{execution_id}")

            records.append(TraceRecord(
                execution_id=execution_id,
                node_id=runner_node.descriptor.node_id,
                episode_version=audit_view.episode_version,
                visible_proposition_ids=tuple(p.proposition_id for p in audit_view.propositions),
                blinded_proposition_ids=audit_view.blinded_proposition_ids,
                visible_relation_ids=tuple(r.relation_id for r in audit_view.relations),
                blinded_relation_ids=audit_view.blinded_relation_ids,
                emitted_proposition_ids=admitted_ids,
                independence_demonstrated=independence_ok,
                task_envelope_digest=task_digest,
                executor_task_specification_digest=executor_task_specification_digest,
                executor_episode_version=executor_episode_version,
                canonical_producer_execution_id=canonical_producer_execution_id,
                canonical_episode_snapshot_digest=canonical_snapshot_digest,
                canonical_output_digest=attempted_output_digest,
                source_refs=input_source_refs,
                source_versions=input_source_versions,
                reported_source_refs=reported_source_refs,
                reported_source_versions=reported_source_versions,
                duration_seconds=duration,
                failures=tuple(execution_failures),
            ))
            if runner_node.descriptor.independence_required and admission_ok:
                prior_independent.append(runner_node.independence)
                prior_independent_source_versions.append(
                    _view_potentially_consumed_evidence_versions(audit_view)
                )
            completed.append(runner_node.descriptor.node_id)
            used += 1

        final_snapshot = Episode.snapshot(episode)
        undispositioned_claim_ids = tuple(
            proposition.proposition_id
            for proposition in final_snapshot.current_propositions
            if proposition.kind is PropositionKind.CLAIM
        )
        unresolved.extend(
            f"claim_disposition:{claim_id}" for claim_id in undispositioned_claim_ids
        )

        receipt = ResultReceipt(
            task_id=task_id,
            episode_version=final_snapshot.version_ref,
            unresolved=tuple(dict.fromkeys(unresolved)),
            failures=tuple(failures),
            effect_state=EffectState.PLAN,
            source_versions=tuple(receipt_source_versions),
            execution_ids=tuple(record.execution_id for record in records),
            execution_output_digests=tuple(
                (
                    record.execution_id,
                    record.canonical_output_digest,
                )
                for record in records
                if record.canonical_output_digest is not None
            ),
            execution_producer_ids=tuple(
                (
                    record.execution_id,
                    record.canonical_producer_execution_id,
                )
                for record in records
                if record.canonical_producer_execution_id is not None
            ),
            task_envelope_digest=task_digest,
            claim_disposition_complete=False,
        )
        return RunOutcome(receipt, ExecutionTrace(tuple(records)))
