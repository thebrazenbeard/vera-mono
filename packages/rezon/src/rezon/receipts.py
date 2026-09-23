from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureState(str, Enum):
    UNAVAILABLE = "unavailable"
    CONFLICT = "conflict"
    INVALID_SUBJECT = "invalid_subject"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RESOURCE_LIMIT = "resource_limit"
    ATTEMPTED_UNKNOWN = "attempted_unknown"
    CONTRACT_VIOLATION = "contract_violation"


class EffectState(str, Enum):
    PLAN = "plan"
    SOURCE_CREATED = "source_created"
    SOURCE_VERIFIED = "source_verified"
    REVIEWED = "reviewed"
    DELIVERED = "delivered"
    INSTALLED = "installed"
    ACTIVE = "active"
    EFFECT_OBSERVED = "effect_observed"
    QUALIFIED = "qualified"
    CLOSED = "closed"


class AdmissionStatus(str, Enum):
    RETRIEVED_ONLY = "retrieved_only"
    ADMITTED = "admitted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


_TRUSTED_INDEPENDENCE_BASIS_PREFIXES = ("policy:", "receipt:", "review:", "runtime:")


def _is_exact_nonempty_str(value) -> bool:
    return type(value) is str and bool(value)


def _is_exact_str_tuple(values, *, require_nonempty: bool = False) -> bool:
    return bool(
        type(values) is tuple
        and (not require_nonempty or values)
        and all(_is_exact_nonempty_str(value) for value in values)
    )


@dataclass(frozen=True)
class IndependenceMetadata:
    executor_id: str | None = None
    model_id: str | None = None
    provider_id: str | None = None
    prompt_lineage: str | None = None
    context_lineage: str | None = None
    saw_other_answer: bool | None = None
    common_evidence_refs: tuple[str, ...] = ()
    consumed_evidence_refs: tuple[str, ...] = ()
    independence_basis_refs: tuple[str, ...] = ()

    @property
    def is_demonstrably_independent(self) -> bool:
        """Whether the claim is complete enough to be externally verified.

        Prefix shape is only a claim-format check. The runner does not trust it by
        itself; independence-required execution also needs a matching external
        IndependenceVerificationPolicy.
        """
        if type(self) is not IndependenceMetadata:
            return False
        if not all(
            _is_exact_nonempty_str(value)
            for value in (
                self.executor_id,
                self.model_id,
                self.provider_id,
                self.prompt_lineage,
                self.context_lineage,
            )
        ):
            return False
        if self.saw_other_answer is not False:
            return False
        if not _is_exact_str_tuple(self.common_evidence_refs):
            return False
        if not _is_exact_str_tuple(self.consumed_evidence_refs):
            return False
        if not _is_exact_str_tuple(
            self.independence_basis_refs,
            require_nonempty=True,
        ):
            return False
        if self.common_evidence_refs:
            return False
        return all(
            ref.startswith(_TRUSTED_INDEPENDENCE_BASIS_PREFIXES)
            for ref in self.independence_basis_refs
        )

    def demonstrably_independent_from(self, other: "IndependenceMetadata") -> bool:
        if type(self) is not IndependenceMetadata or type(other) is not IndependenceMetadata:
            return False
        if not self.is_demonstrably_independent or not other.is_demonstrably_independent:
            return False
        if self.executor_id == other.executor_id:
            return False
        if self.model_id == other.model_id:
            return False
        if self.provider_id == other.provider_id:
            return False
        if self.prompt_lineage == other.prompt_lineage:
            return False
        if self.context_lineage == other.context_lineage:
            return False
        if set(self.common_evidence_refs) & set(other.common_evidence_refs):
            return False
        if set(self.consumed_evidence_refs) & set(other.consumed_evidence_refs):
            return False
        return True


@dataclass(frozen=True)
class IndependenceVerificationEvidence:
    basis_ref: str
    executor_id: str
    model_id: str
    provider_id: str
    prompt_lineage: str
    context_lineage: str
    verification_refs: tuple[str, ...]
    saw_other_answer: bool | None = None
    common_evidence_refs: tuple[str, ...] | None = None
    consumed_evidence_refs: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if not all((
            self.basis_ref,
            self.executor_id,
            self.model_id,
            self.provider_id,
            self.prompt_lineage,
            self.context_lineage,
            self.verification_refs,
        )):
            raise ValueError("independence verification evidence must be complete")
        if not self.basis_ref.startswith(_TRUSTED_INDEPENDENCE_BASIS_PREFIXES):
            raise ValueError("independence verification basis must use a governed namespace")
        if any(not ref for ref in self.verification_refs):
            raise ValueError("independence verification refs must be non-empty")
        for refs in (self.common_evidence_refs, self.consumed_evidence_refs):
            if refs is not None and any(not ref for ref in refs):
                raise ValueError("independence evidence refs must be non-empty")


def _is_exact_independence_verification_evidence(
    evidence: IndependenceVerificationEvidence,
) -> bool:
    if type(evidence) is not IndependenceVerificationEvidence:
        return False
    if not all(
        _is_exact_nonempty_str(value)
        for value in (
            evidence.basis_ref,
            evidence.executor_id,
            evidence.model_id,
            evidence.provider_id,
            evidence.prompt_lineage,
            evidence.context_lineage,
        )
    ):
        return False
    if not evidence.basis_ref.startswith(_TRUSTED_INDEPENDENCE_BASIS_PREFIXES):
        return False
    if not _is_exact_str_tuple(evidence.verification_refs, require_nonempty=True):
        return False
    if evidence.saw_other_answer is not False:
        return False
    if not _is_exact_str_tuple(evidence.common_evidence_refs):
        return False
    if not _is_exact_str_tuple(evidence.consumed_evidence_refs):
        return False
    return True


@dataclass(frozen=True)
class IndependenceVerificationPolicy:
    verified_evidence: tuple[IndependenceVerificationEvidence, ...]

    def verify(self, metadata: IndependenceMetadata) -> bool:
        if type(self) is not IndependenceVerificationPolicy:
            return False
        if type(metadata) is not IndependenceMetadata:
            return False
        if type(self.verified_evidence) is not tuple:
            return False
        if any(
            not _is_exact_independence_verification_evidence(evidence)
            for evidence in self.verified_evidence
        ):
            return False
        if not metadata.is_demonstrably_independent:
            return False
        claimed_basis = set(metadata.independence_basis_refs)
        for evidence in self.verified_evidence:
            if evidence.basis_ref not in claimed_basis:
                continue
            if (
                evidence.executor_id,
                evidence.model_id,
                evidence.provider_id,
                evidence.prompt_lineage,
                evidence.context_lineage,
            ) != (
                metadata.executor_id,
                metadata.model_id,
                metadata.provider_id,
                metadata.prompt_lineage,
                metadata.context_lineage,
            ):
                continue
            if evidence.saw_other_answer is not metadata.saw_other_answer:
                continue
            if evidence.saw_other_answer is not False:
                continue
            if evidence.common_evidence_refs is None:
                continue
            if tuple(evidence.common_evidence_refs) != tuple(metadata.common_evidence_refs):
                continue
            if evidence.consumed_evidence_refs is None:
                continue
            if tuple(evidence.consumed_evidence_refs) != tuple(metadata.consumed_evidence_refs):
                continue
            return True
        return False


@dataclass(frozen=True)
class RetrievalReceipt:
    retrieval_id: str
    query: str
    source_id: str
    source_version: str | None
    method: str
    returned_refs: tuple[str, ...] = ()
    admission_status: AdmissionStatus = AdmissionStatus.RETRIEVED_ONLY
    admission_authority_ref: str | None = None
    verification_refs: tuple[str, ...] = ()
    currentness_ref: str | None = None
    authoritative_scope: str | None = None

    def __post_init__(self) -> None:
        if not self.retrieval_id or not self.query or not self.source_id or not self.method:
            raise ValueError("retrieval identity, query, source, and method are required")



@dataclass(frozen=True)
class ResultReceipt:
    task_id: str
    episode_version: str
    accepted_claim_ids: tuple[str, ...] = ()
    rejected_claim_ids: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    failures: tuple[FailureState, ...] = ()
    effect_state: EffectState = EffectState.PLAN
    source_versions: tuple[str, ...] = ()
    execution_ids: tuple[str, ...] = ()
    execution_output_digests: tuple[tuple[str, str], ...] = ()
    execution_producer_ids: tuple[tuple[str, str], ...] = ()
    task_envelope_digest: str | None = None
    claim_disposition_complete: bool = False

    def __post_init__(self) -> None:
        if not self.task_id or not self.episode_version:
            raise ValueError("result receipt requires exact task_id and episode_version")
        overlap = set(self.accepted_claim_ids) & set(self.rejected_claim_ids)
        if overlap:
            raise ValueError(f"claims cannot be both accepted and rejected: {sorted(overlap)}")
        if type(self.execution_output_digests) is not tuple:
            raise ValueError(
                "execution output digests must be an exact tuple"
            )
        seen_execution_ids: set[str] = set()
        known_execution_ids = set(self.execution_ids)
        for binding in self.execution_output_digests:
            if (
                type(binding) is not tuple
                or len(binding) != 2
                or any(type(value) is not str or not value for value in binding)
            ):
                raise ValueError(
                    "execution output digests must contain non-empty exact str pairs"
                )
            execution_id, _output_digest = binding
            if execution_id not in known_execution_ids:
                raise ValueError(
                    "execution output digest must bind a receipt execution id"
                )
            if execution_id in seen_execution_ids:
                raise ValueError(
                    "execution output digest binding cannot duplicate execution id"
                )
            seen_execution_ids.add(execution_id)
        if type(self.execution_producer_ids) is not tuple:
            raise ValueError(
                "execution producer ids must be an exact tuple"
            )
        seen_producer_execution_ids: set[str] = set()
        for binding in self.execution_producer_ids:
            if (
                type(binding) is not tuple
                or len(binding) != 2
                or any(type(value) is not str or not value for value in binding)
            ):
                raise ValueError(
                    "execution producer ids must contain non-empty exact str pairs"
                )
            execution_id, _producer_id = binding
            if execution_id not in known_execution_ids:
                raise ValueError(
                    "execution producer id must bind a receipt execution id"
                )
            if execution_id in seen_producer_execution_ids:
                raise ValueError(
                    "execution producer binding cannot duplicate execution id"
                )
            seen_producer_execution_ids.add(execution_id)
        if self.accepted_claim_ids or self.rejected_claim_ids:
            raise ValueError(
                "generic ResultReceipt cannot assert accepted/rejected claim disposition; "
                "claim disposition requires a separately governed artifact"
            )
        if self.claim_disposition_complete:
            raise ValueError(
                "generic ResultReceipt cannot assert claim disposition completeness; "
                "claim disposition requires a separately governed artifact"
            )
        if self.effect_state is not EffectState.PLAN:
            raise ValueError(
                "ResultReceipt is non-promotional and may report PLAN only; "
                "higher lifecycle/effect states require a separately governed transition artifact"
            )
