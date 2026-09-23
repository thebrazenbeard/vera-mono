from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .episode import Episode
from .epistemics import Proposition, PropositionKind
from .receipts import AdmissionStatus, RetrievalReceipt


class RetrievalAdmissionError(ValueError):
    pass


def _require_exact_nonempty_str(value, label: str) -> None:
    if type(value) is not str or not value:
        raise RetrievalAdmissionError(f"{label} must be a non-empty exact str")


def _require_exact_source_binding_component(value, label: str) -> None:
    _require_exact_nonempty_str(value, label)
    if "@" in value:
        raise RetrievalAdmissionError(
            f"{label} cannot contain the source-version binding separator '@'"
        )


def _require_exact_str_tuple(
    values,
    label: str,
    *,
    require_nonempty: bool = False,
) -> None:
    if type(values) is not tuple:
        raise RetrievalAdmissionError(f"{label} must be an exact tuple")
    if require_nonempty and not values:
        raise RetrievalAdmissionError(f"{label} must not be empty")
    if any(type(value) is not str or not value for value in values):
        raise RetrievalAdmissionError(
            f"{label} must contain non-empty exact str values"
        )


def digest_retrieved_content(content: str) -> str:
    if type(content) is not str or not content:
        raise ValueError("retrieved content must be a non-empty exact str")
    return sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RetrievalAdmissionEvidence:
    source_id: str
    source_version: str
    admission_authority_ref: str
    verification_refs: tuple[str, ...]
    currentness_ref: str
    authoritative_scope: str
    content_digest: str | None = None
    locator_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((
            self.source_id,
            self.source_version,
            self.admission_authority_ref,
            self.verification_refs,
            self.currentness_ref,
            self.authoritative_scope,
        )):
            raise ValueError("retrieval admission evidence must be complete")


@dataclass(frozen=True)
class RetrievalAdmissionPolicy:
    verified_admissions: tuple[RetrievalAdmissionEvidence, ...]

    def verify(
        self,
        receipt: RetrievalReceipt,
        content: str,
        required_scope: str | None,
    ) -> RetrievalAdmissionEvidence | None:
        _validate_policy(self)
        _validate_receipt(receipt)
        _require_exact_nonempty_str(content, "retrieved content")
        _require_exact_nonempty_str(required_scope, "required authoritative scope")

        content_digest = digest_retrieved_content(content)
        returned_refs = set(receipt.returned_refs)
        for evidence in self.verified_admissions:
            if (evidence.source_id, evidence.source_version) != (
                receipt.source_id,
                receipt.source_version,
            ):
                continue
            if evidence.authoritative_scope != required_scope:
                continue
            if evidence.content_digest != content_digest:
                continue
            if not returned_refs.issubset(set(evidence.locator_refs)):
                continue
            return evidence
        return None


def _validate_receipt(receipt: RetrievalReceipt) -> None:
    if type(receipt) is not RetrievalReceipt:
        raise RetrievalAdmissionError("retrieval receipt must be exact RetrievalReceipt")
    for value, label in (
        (receipt.retrieval_id, "retrieval id"),
        (receipt.query, "retrieval query"),
        (receipt.method, "retrieval method"),
    ):
        _require_exact_nonempty_str(value, label)
    _require_exact_source_binding_component(receipt.source_id, "retrieval source id")
    _require_exact_source_binding_component(
        receipt.source_version,
        "retrieval source version",
    )
    _require_exact_str_tuple(
        receipt.returned_refs,
        "retrieval returned refs",
        require_nonempty=True,
    )
    if type(receipt.admission_status) is not AdmissionStatus:
        raise RetrievalAdmissionError("retrieval admission status must be exact AdmissionStatus")
    _require_exact_str_tuple(receipt.verification_refs, "retrieval verification refs")
    for value, label in (
        (receipt.admission_authority_ref, "retrieval admission authority ref"),
        (receipt.currentness_ref, "retrieval currentness ref"),
        (receipt.authoritative_scope, "retrieval authoritative scope"),
    ):
        if value is not None:
            _require_exact_nonempty_str(value, label)


def _validate_evidence(evidence: RetrievalAdmissionEvidence) -> None:
    if type(evidence) is not RetrievalAdmissionEvidence:
        raise RetrievalAdmissionError(
            "retrieval admission evidence must be exact RetrievalAdmissionEvidence"
        )
    _require_exact_source_binding_component(evidence.source_id, "evidence source id")
    _require_exact_source_binding_component(
        evidence.source_version,
        "evidence source version",
    )
    for value, label in (
        (evidence.admission_authority_ref, "evidence admission authority ref"),
        (evidence.currentness_ref, "evidence currentness ref"),
        (evidence.authoritative_scope, "evidence authoritative scope"),
        (evidence.content_digest, "evidence content digest"),
    ):
        _require_exact_nonempty_str(value, label)
    _require_exact_str_tuple(
        evidence.verification_refs,
        "evidence verification refs",
        require_nonempty=True,
    )
    _require_exact_str_tuple(
        evidence.locator_refs,
        "evidence locator refs",
        require_nonempty=True,
    )


def _validate_policy(policy: RetrievalAdmissionPolicy) -> None:
    if type(policy) is not RetrievalAdmissionPolicy:
        raise RetrievalAdmissionError(
            "retrieval admission policy must be exact RetrievalAdmissionPolicy"
        )
    if type(policy.verified_admissions) is not tuple:
        raise RetrievalAdmissionError("verified admissions must be an exact tuple")
    for evidence in policy.verified_admissions:
        _validate_evidence(evidence)


def admit_retrieval_as_evidence(
    episode: Episode,
    receipt: RetrievalReceipt,
    proposition_id: str,
    content: str,
    *,
    policy: RetrievalAdmissionPolicy | None = None,
    required_scope: str | None = None,
) -> Proposition:
    if type(episode) is not Episode:
        raise RetrievalAdmissionError("episode must be exact Episode")
    _require_exact_nonempty_str(proposition_id, "evidence proposition id")
    _require_exact_nonempty_str(content, "retrieved content")
    if policy is None:
        raise RetrievalAdmissionError("retrieval admission requires an external admission policy")
    _validate_policy(policy)
    _validate_receipt(receipt)
    _require_exact_nonempty_str(required_scope, "required authoritative scope")

    if receipt.admission_status is not AdmissionStatus.ADMITTED:
        raise RetrievalAdmissionError("retrieved material has not been admitted as evidence")
    verified = policy.verify(receipt, content, required_scope)
    if verified is None:
        raise RetrievalAdmissionError(
            "retrieval content/locator/source/version/scope lacks exact independent admission evidence"
        )
    evidence = Proposition(
        proposition_id=proposition_id,
        episode_id=episode.episode_id,
        kind=PropositionKind.EVIDENCE,
        content=content,
        source_refs=(
            f"{receipt.source_id}@{receipt.source_version}",
            *receipt.returned_refs,
            f"content-sha256:{verified.content_digest}",
            f"scope:{verified.authoritative_scope}",
            f"retrieval:{receipt.retrieval_id}",
            f"admission:{verified.admission_authority_ref}",
            f"currentness:{verified.currentness_ref}",
            *verified.verification_refs,
        ),
        source_versions=(f"{receipt.source_id}@{receipt.source_version}",),
    )
    Episode.add_proposition(episode, evidence)
    return evidence
