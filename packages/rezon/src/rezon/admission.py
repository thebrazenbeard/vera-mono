from __future__ import annotations

from dataclasses import dataclass, replace
from functools import wraps

from .envelopes import TaskSpecification, task_specification_contract_is_exact
from .episode import Episode, EpisodeInvariantError
from .epistemics import Hyperrelation, Participant, Proposition, PropositionKind, source_ref_version_bindings
from .nodes import ExecutionResult, NodeDescriptor, node_descriptor_contract_is_exact
from .receipts import FailureState
from .provenance import (
    canonical_episode_snapshot_digest,
    canonical_output_digest,
    canonical_producer_execution_id,
)


class AdmissionError(ValueError):
    pass


def _require_exact_str_tuple(values, label: str) -> None:
    if type(values) is not tuple or any(
        type(value) is not str or not value
        for value in values
    ):
        raise AdmissionError(
            f"{label} must be a tuple of non-empty exact str values"
        )


def _validate_admission_contract(
    episode: Episode,
    descriptor: NodeDescriptor,
    result: ExecutionResult,
    allowed_source_refs: tuple[str, ...] | None,
    allowed_source_versions: tuple[str, ...] | None,
    allowed_source_bindings: tuple[tuple[str, str], ...] | None,
) -> None:
    if type(episode) is not Episode:
        raise AdmissionError("episode must be exact Episode")
    if not node_descriptor_contract_is_exact(descriptor):
        raise AdmissionError("descriptor must satisfy exact NodeDescriptor contract")
    if type(result) is not ExecutionResult:
        raise AdmissionError("execution result must be exact ExecutionResult")

    if (
        type(descriptor.permitted_output_kinds) is not tuple
        or any(type(kind) is not PropositionKind for kind in descriptor.permitted_output_kinds)
    ):
        raise AdmissionError("permitted output kinds must be exact PropositionKind values")
    _require_exact_str_tuple(
        descriptor.permitted_relation_types,
        "permitted relation types",
    )

    if type(result.failures) is not tuple or any(
        type(failure) is not FailureState for failure in result.failures
    ):
        raise AdmissionError("execution failures must be exact FailureState values")
    if type(result.emitted_propositions) is not tuple:
        raise AdmissionError("emitted propositions must be an exact tuple")
    if type(result.emitted_relations) is not tuple:
        raise AdmissionError("emitted relations must be an exact tuple")

    for proposition in result.emitted_propositions:
        if type(proposition) is not Proposition:
            raise AdmissionError("emitted proposition must be exact Proposition")
        if (
            type(proposition.proposition_id) is not str
            or type(proposition.episode_id) is not str
            or type(proposition.content) is not str
        ):
            raise AdmissionError("proposition identity/content fields must be exact str")
        if type(proposition.kind) is not PropositionKind:
            raise AdmissionError("proposition kind must be exact PropositionKind")
        if (
            proposition.producer_execution_id is not None
            and type(proposition.producer_execution_id) is not str
        ):
            raise AdmissionError("proposition producer identity must be exact str")
        _require_exact_str_tuple(proposition.source_refs, "proposition source refs")
        _require_exact_str_tuple(
            proposition.source_versions,
            "proposition source versions",
        )

    for relation in result.emitted_relations:
        if type(relation) is not Hyperrelation:
            raise AdmissionError("emitted relation must be exact Hyperrelation")
        if (
            type(relation.relation_id) is not str
            or type(relation.episode_id) is not str
            or type(relation.relation_type) is not str
        ):
            raise AdmissionError("relation identity/type fields must be exact str")
        if (
            relation.producer_execution_id is not None
            and type(relation.producer_execution_id) is not str
        ):
            raise AdmissionError("relation producer identity must be exact str")
        _require_exact_str_tuple(relation.source_refs, "relation source refs")
        _require_exact_str_tuple(relation.source_versions, "relation source versions")
        if type(relation.participants) is not tuple:
            raise AdmissionError("relation participants must be an exact tuple")
        for participant in relation.participants:
            if type(participant) is not Participant:
                raise AdmissionError("relation participant must be exact Participant")
            if type(participant.ref_id) is not str or type(participant.role) is not str:
                raise AdmissionError("participant identity/role fields must be exact str")

    if allowed_source_refs is not None:
        _require_exact_str_tuple(allowed_source_refs, "allowed source refs")
    if allowed_source_versions is not None:
        _require_exact_str_tuple(allowed_source_versions, "allowed source versions")
    if allowed_source_bindings is not None:
        if type(allowed_source_bindings) is not tuple:
            raise AdmissionError("allowed source bindings must be an exact tuple")
        for binding in allowed_source_bindings:
            if (
                type(binding) is not tuple
                or len(binding) != 2
                or any(type(value) is not str for value in binding)
            ):
                raise AdmissionError(
                    "allowed source bindings must contain exact str pairs"
                )


def _atomic_episode_mutation(method):
    @wraps(method)
    def wrapped(episode, *args, **kwargs):
        with Episode.atomic_mutation(episode):
            return method(episode, *args, **kwargs)

    return wrapped


@dataclass(frozen=True)
class AdmissionReceipt:
    canonical_episode_snapshot_digest: str
    task_specification_digest: str | None
    canonical_output_digest: str | None
    canonical_producer_execution_id: str | None


def _prevalidate_episode_mutation(episode: Episode, result: ExecutionResult) -> None:
    snapshot = Episode.snapshot(episode)
    existing_props = {p.proposition_id: p for p in snapshot.all_propositions}
    active_props = {p.proposition_id for p in snapshot.current_propositions}
    existing_relations = {r.relation_id: r for r in snapshot.all_relations}
    active_relations = {r.relation_id for r in snapshot.current_relations}

    staged_props = {}
    for proposition in result.emitted_propositions:
        previous = staged_props.get(proposition.proposition_id, existing_props.get(proposition.proposition_id))
        if previous is not None and previous != proposition:
            raise AdmissionError("duplicate proposition ID has conflicting content")
        if proposition.proposition_id in existing_props and proposition.proposition_id not in active_props:
            raise AdmissionError("retracted proposition ID cannot be silently reactivated")
        staged_props[proposition.proposition_id] = proposition

    known_current = set(active_props) | set(active_relations) | set(staged_props)
    staged_relations = {}
    for relation in result.emitted_relations:
        previous = staged_relations.get(relation.relation_id, existing_relations.get(relation.relation_id))
        if previous is not None and previous != relation:
            raise AdmissionError("duplicate relation ID has conflicting content")
        if relation.relation_id in existing_relations and relation.relation_id not in active_relations:
            raise AdmissionError("invalidated relation ID cannot be silently reactivated")
        unavailable = [
            participant.ref_id
            for participant in relation.participants
            if participant.ref_id not in known_current
        ]
        if unavailable:
            raise AdmissionError(
                f"relation references inactive or unknown objects: {unavailable}"
            )
        staged_relations[relation.relation_id] = relation
        known_current.add(relation.relation_id)


@_atomic_episode_mutation
def admit_execution_result(
    episode: Episode,
    descriptor: NodeDescriptor,
    result: ExecutionResult,
    *,
    expected_episode_snapshot_digest: str,
    expected_execution_id: str | None = None,
    task_specification: TaskSpecification | None = None,
    allowed_source_refs: tuple[str, ...] | None = None,
    allowed_source_versions: tuple[str, ...] | None = None,
    allowed_source_bindings: tuple[tuple[str, str], ...] | None = None,
) -> AdmissionReceipt:
    _validate_admission_contract(
        episode,
        descriptor,
        result,
        allowed_source_refs,
        allowed_source_versions,
        allowed_source_bindings,
    )

    if type(descriptor.node_id) is not str or type(result.node_id) is not str:
        raise AdmissionError("node identity must use exact str values")
    if result.node_id != descriptor.node_id:
        raise AdmissionError("execution result node does not match descriptor")
    if type(result.execution_id) is not str or not result.execution_id:
        raise AdmissionError(
            "execution result identity must be a non-empty exact str"
        )
    if (
        expected_execution_id is not None
        and (
            type(expected_execution_id) is not str
            or not expected_execution_id
        )
    ):
        raise AdmissionError(
            "expected execution identity must be a non-empty exact str"
        )
    if expected_execution_id is not None and result.execution_id != expected_execution_id:
        raise AdmissionError("execution result identity does not match runner-issued execution")
    if result.failures:
        raise AdmissionError("failed execution results cannot mutate canonical episode state")

    snapshot_digest = canonical_episode_snapshot_digest(Episode.snapshot(episode))
    if (
        type(expected_episode_snapshot_digest) is not str
        or snapshot_digest != expected_episode_snapshot_digest
    ):
        raise AdmissionError(
            "canonical episode state changed after execution view was captured"
        )

    if (
        task_specification is not None
        and not task_specification_contract_is_exact(task_specification)
    ):
        raise AdmissionError(
            "task specification must satisfy exact TaskSpecification contract"
        )

    task_specification_digest = (
        task_specification.digest if task_specification is not None else None
    )
    output_digest = canonical_output_digest(result)
    derived_producer_execution_id = (
        canonical_producer_execution_id(
            descriptor.node_id,
            snapshot_digest,
            task_specification_digest,
            output_digest,
        )
        if output_digest is not None
        else None
    )

    required_execution_id = expected_execution_id or result.execution_id
    permitted = set(descriptor.permitted_output_kinds)
    permitted_relation_types = {
        relation_type.lower() for relation_type in descriptor.permitted_relation_types
    }
    governed_refs = set(allowed_source_refs or ())
    governed_source_versions = set(allowed_source_versions or ())
    governed_source_bindings = set(allowed_source_bindings or ())

    for proposition in result.emitted_propositions:
        if type(proposition.episode_id) is not str:
            raise AdmissionError("proposition episode identity must be exact str")
        if (
            proposition.producer_execution_id is not None
            and type(proposition.producer_execution_id) is not str
        ):
            raise AdmissionError("proposition producer identity must be exact str")
        if proposition.kind not in permitted:
            raise AdmissionError(f"node {descriptor.node_id} may not emit {proposition.kind.value}")
        if proposition.kind is PropositionKind.EVIDENCE:
            raise AdmissionError("worker output cannot self-promote to evidence")
        if proposition.producer_execution_id != required_execution_id:
            raise AdmissionError("execution-emitted proposition must bind exact producer execution")
        if proposition.episode_id != episode.episode_id:
            raise AdmissionError("proposition belongs to a different episode")
        if allowed_source_refs is not None:
            ungoverned = [ref for ref in proposition.source_refs if ref not in governed_refs]
            if ungoverned:
                raise AdmissionError(
                    f"proposition reports provenance not present in governed execution view: {ungoverned}"
                )
        if allowed_source_versions is not None:
            ungoverned_versions = [
                version
                for version in proposition.source_versions
                if version not in governed_source_versions
            ]
            if ungoverned_versions:
                raise AdmissionError(
                    "proposition reports source versions not present in governed "
                    f"execution view: {ungoverned_versions}"
                )
        if allowed_source_bindings is not None and proposition.source_versions:
            bindings = source_ref_version_bindings(
                proposition.source_refs,
                proposition.source_versions,
            )
            if bindings is None:
                raise AdmissionError(
                    "proposition source versions lack exact source-ref association"
                )
            ungoverned_bindings = [
                binding for binding in bindings if binding not in governed_source_bindings
            ]
            if ungoverned_bindings:
                raise AdmissionError(
                    "proposition reports source ref/version association not present "
                    f"in governed execution view: {ungoverned_bindings}"
                )

    staged_prop_ids = {p.proposition_id for p in result.emitted_propositions}
    relation_participant_refs = governed_refs | staged_prop_ids
    for relation in result.emitted_relations:
        if type(relation.episode_id) is not str:
            raise AdmissionError("relation episode identity must be exact str")
        if (
            relation.producer_execution_id is not None
            and type(relation.producer_execution_id) is not str
        ):
            raise AdmissionError("relation producer identity must be exact str")
        if relation.relation_type.lower() not in permitted_relation_types:
            raise AdmissionError(
                f"node {descriptor.node_id} may not emit relation type {relation.relation_type}"
            )
        if relation.producer_execution_id != required_execution_id:
            raise AdmissionError("execution-emitted relation must bind exact producer execution")
        if relation.episode_id != episode.episode_id:
            raise AdmissionError("relation belongs to a different episode")
        if allowed_source_refs is not None:
            ungoverned_sources = [ref for ref in relation.source_refs if ref not in governed_refs]
            if ungoverned_sources:
                raise AdmissionError(
                    f"relation reports provenance not present in governed execution view: {ungoverned_sources}"
                )
            ungoverned_participants = [
                participant.ref_id
                for participant in relation.participants
                if participant.ref_id not in relation_participant_refs
            ]
            if ungoverned_participants:
                raise AdmissionError(
                    f"relation references objects outside governed execution view: {ungoverned_participants}"
                )
        if allowed_source_versions is not None:
            ungoverned_versions = [
                version
                for version in relation.source_versions
                if version not in governed_source_versions
            ]
            if ungoverned_versions:
                raise AdmissionError(
                    "relation reports source versions not present in governed "
                    f"execution view: {ungoverned_versions}"
                )
        if allowed_source_bindings is not None and relation.source_versions:
            bindings = source_ref_version_bindings(
                relation.source_refs,
                relation.source_versions,
            )
            if bindings is None:
                raise AdmissionError(
                    "relation source versions lack exact source-ref association"
                )
            ungoverned_bindings = [
                binding for binding in bindings if binding not in governed_source_bindings
            ]
            if ungoverned_bindings:
                raise AdmissionError(
                    "relation reports source ref/version association not present "
                    f"in governed execution view: {ungoverned_bindings}"
                )

    admitted_result = replace(
        result,
        emitted_propositions=tuple(
            replace(
                proposition,
                producer_execution_id=derived_producer_execution_id,
            )
            for proposition in result.emitted_propositions
        ),
        emitted_relations=tuple(
            replace(
                relation,
                producer_execution_id=derived_producer_execution_id,
            )
            for relation in result.emitted_relations
        ),
    )

    _prevalidate_episode_mutation(episode, admitted_result)
    try:
        for proposition in admitted_result.emitted_propositions:
            Episode.add_proposition(episode, proposition)
        for relation in admitted_result.emitted_relations:
            Episode.add_relation(episode, relation)
    except EpisodeInvariantError as exc:
        raise AdmissionError(str(exc)) from exc

    return AdmissionReceipt(
        canonical_episode_snapshot_digest=snapshot_digest,
        task_specification_digest=task_specification_digest,
        canonical_output_digest=output_digest,
        canonical_producer_execution_id=derived_producer_execution_id,
    )
