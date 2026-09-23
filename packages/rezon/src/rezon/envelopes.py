from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json


@dataclass(frozen=True)
class TaskSpecification:
    literal_request: str
    subject_refs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.literal_request:
            raise ValueError("literal_request is required")

    @property
    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


def _is_exact_str_tuple(values) -> bool:
    return type(values) is tuple and all(type(value) is str for value in values)


def task_specification_contract_is_exact(
    specification: TaskSpecification,
) -> bool:
    return bool(
        type(specification) is TaskSpecification
        and type(specification.literal_request) is str
        and specification.literal_request
        and _is_exact_str_tuple(specification.subject_refs)
        and _is_exact_str_tuple(specification.constraints)
    )


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    literal_request: str
    subject_refs: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    available_authority: tuple[str, ...] = ()
    privacy_scope: str | None = None
    resource_budget: int | None = None
    context_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.task_id or not self.literal_request:
            raise ValueError("task_id and literal_request are required")
        if self.resource_budget is not None and self.resource_budget < 0:
            raise ValueError("resource_budget cannot be negative")

    @property
    def digest(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()

    def to_task_specification(self) -> TaskSpecification:
        return TaskSpecification(
            literal_request=self.literal_request,
            subject_refs=self.subject_refs,
            constraints=self.constraints,
        )


def task_envelope_contract_is_exact(envelope: TaskEnvelope) -> bool:
    if type(envelope) is not TaskEnvelope:
        return False
    if (
        type(envelope.task_id) is not str
        or not envelope.task_id
        or type(envelope.literal_request) is not str
        or not envelope.literal_request
    ):
        return False
    for values in (
        envelope.subject_refs,
        envelope.constraints,
        envelope.available_authority,
        envelope.context_refs,
    ):
        if not _is_exact_str_tuple(values):
            return False
    if (
        envelope.privacy_scope is not None
        and type(envelope.privacy_scope) is not str
    ):
        return False
    if (
        envelope.resource_budget is not None
        and (
            type(envelope.resource_budget) is not int
            or envelope.resource_budget < 0
        )
    ):
        return False
    return task_specification_contract_is_exact(envelope.to_task_specification())


@dataclass(frozen=True)
class AuthorityVerificationEvidence:
    authority: str
    task_id: str
    task_envelope_digest: str
    issuer_ref: str
    source_ref: str
    currentness_ref: str
    verification_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all((
            self.authority,
            self.task_id,
            self.task_envelope_digest,
            self.issuer_ref,
            self.source_ref,
            self.currentness_ref,
            self.verification_refs,
        )):
            raise ValueError("authority verification evidence must be complete")
        if any(not ref for ref in self.verification_refs):
            raise ValueError("authority verification refs must be non-empty")


@dataclass(frozen=True)
class AuthorityVerificationPolicy:
    """Candidate authority-evidence matcher, not an authorization grant.

    Kernel V0 deliberately does not accept this in-process object as sufficient
    authority proof. It remains a structured evidence candidate for a future
    separately governed verifier boundary.
    """

    verified_evidence: tuple[AuthorityVerificationEvidence, ...]

    def verify(
        self,
        envelope: TaskEnvelope,
        required_authority: tuple[str, ...],
    ) -> bool:
        required = set(required_authority)
        if not required:
            return True
        if not required.issubset(set(envelope.available_authority)):
            return False
        for authority in required:
            if not any(
                evidence.authority == authority
                and evidence.task_id == envelope.task_id
                and evidence.task_envelope_digest == envelope.digest
                and evidence.issuer_ref
                and evidence.source_ref
                and evidence.currentness_ref
                and evidence.verification_refs
                for evidence in self.verified_evidence
            ):
                return False
        return True
