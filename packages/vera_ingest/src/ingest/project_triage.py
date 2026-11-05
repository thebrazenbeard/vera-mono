"""Pure, private-only review of ChatGPT Project inventory metadata.

This module never accesses a provider, reads an archive, publishes material,
grants memory admission, or deletes anything.  Input receipt references are
caller claims; a separate host-owned verifier must authenticate them.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json


MAX_PROJECTS = 512
_COVERAGES = frozenset({"COMPLETE", "PARTIAL", "UNKNOWN"})
_MEMORY_SCOPES = frozenset({"DEFAULT", "PROJECT_ONLY", "UNKNOWN"})


class ProjectTriageError(ValueError):
    """Reject malformed, ambiguous, or unbounded inventory evidence."""


def _bounded_text(label: str, value: object, limit: int = 512) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ProjectTriageError(f"{label} must be a nonempty exact string without NUL")
    if len(value) > limit:
        raise ProjectTriageError(f"{label} exceeds byte limit")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ProjectTriageError(f"{label} must be UTF-8") from exc
    if length > limit or not value.strip():
        raise ProjectTriageError(f"{label} exceeds byte limit or is blank")
    return value


@dataclass(frozen=True, slots=True)
class ProjectEvidence:
    """Metadata claims from a separately controlled, private inventory.

    ``source_digest`` binds an observed inventory source, NOT proof that every
    underlying conversation, attachment, hidden file or native memory migrated.
    Optional truth values mean explicitly unknown when None, not false.
    """

    project_id: str
    source_digest: str
    coverage: str
    active_work: bool | None
    unique_material: bool | None
    outstanding_references: bool | None
    memory_scope: str = "UNKNOWN"
    file_library_enabled: bool | None = None
    duplicate_of: str | None = None
    duplicate_review_ref: str | None = None
    archive_copy_receipt_ref: str | None = None

    def __post_init__(self) -> None:
        _bounded_text("project_id", self.project_id)
        if type(self.source_digest) is not str or len(self.source_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.source_digest
        ):
            raise ProjectTriageError("source_digest must be lowercase SHA-256 hex")
        if type(self.coverage) is not str or self.coverage not in _COVERAGES:
            raise ProjectTriageError("coverage is not a recognized exact value")
        if type(self.memory_scope) is not str or self.memory_scope not in _MEMORY_SCOPES:
            raise ProjectTriageError("memory_scope is not a recognized exact value")
        for label in ("active_work", "unique_material", "outstanding_references", "file_library_enabled"):
            value = getattr(self, label)
            if value is not None and type(value) is not bool:
                raise ProjectTriageError(f"{label} must be bool or None")
        for label in ("duplicate_of", "duplicate_review_ref", "archive_copy_receipt_ref"):
            value = getattr(self, label)
            if value is not None:
                _bounded_text(label, value)
        if self.duplicate_of == self.project_id:
            raise ProjectTriageError("project cannot duplicate itself")
        if self.duplicate_review_ref is not None and self.duplicate_of is None:
            raise ProjectTriageError("orphan duplicate review reference")


def triage_projects(projects: tuple[ProjectEvidence, ...]) -> dict:
    """Return deterministic non-mutating triage; no result means DELETE.

    These decisions are conservative **review labels**, not verified factual
    claims about project content, owner authorization, or archive completeness.
    In particular, caller-provided receipts are never independently validated.
    """
    if type(projects) is not tuple or len(projects) > MAX_PROJECTS:
        raise ProjectTriageError("projects must be a bounded exact tuple")
    by_id: dict[str, ProjectEvidence] = {}
    for item in projects:
        if type(item) is not ProjectEvidence:
            raise ProjectTriageError("all items must be exact ProjectEvidence instances")
        if item.project_id in by_id:
            raise ProjectTriageError("duplicate project id")
        by_id[item.project_id] = item
    # A proposed duplicate chain must have a retained endpoint. In particular,
    # mutually referencing retirement candidates cannot delete each other.
    for item in projects:
        visited = {item.project_id}
        target = item.duplicate_of
        while target in by_id:
            if target in visited:
                raise ProjectTriageError("duplicate-target cycle")
            visited.add(target)
            target = by_id[target].duplicate_of
    referenced_targets = {item.duplicate_of for item in projects if item.duplicate_of is not None}
    rows: list[dict] = []
    for item in sorted(projects, key=lambda row: row.project_id):
        reasons: list[str] = []
        if item.project_id in referenced_targets:
            reasons.append("DUPLICATE_TARGET_MUST_BE_RETAINED")
        if item.active_work is True:
            reasons.append("ACTIVE_WORK")
        if item.unique_material is True:
            reasons.append("UNIQUE_MATERIAL")
        if item.outstanding_references is True:
            reasons.append("OUTSTANDING_REFERENCES")
        if item.memory_scope == "PROJECT_ONLY" and item.file_library_enabled is False:
            reasons.append("PROJECT_ONLY_WITHOUT_FILE_LIBRARY")
        if reasons:
            disposition = "PRESERVE"
        elif item.coverage != "COMPLETE" or any(
            value is None for value in (item.active_work, item.unique_material, item.outstanding_references)
        ) or item.memory_scope == "UNKNOWN" or item.file_library_enabled is None:
            disposition = "INSPECT_MISSING_EVIDENCE"
            reasons.append("INCOMPLETE_OR_UNKNOWN_COVERAGE")
        elif item.duplicate_of is None or item.duplicate_review_ref is None:
            disposition = "REVIEW_FOR_CONSOLIDATION"
            reasons.append("NO_REFERENCED_DUPLICATE_REVIEW")
        elif item.duplicate_of not in by_id:
            disposition = "INSPECT_MISSING_EVIDENCE"
            reasons.append("DUPLICATE_TARGET_ABSENT")
        elif item.archive_copy_receipt_ref is None:
            disposition = "REVIEW_FOR_CONSOLIDATION"
            reasons.append("NO_COPY_RECEIPT_REFERENCE")
        else:
            disposition = "REVIEW_FOR_RETIREMENT"
            reasons.append("CLAIMED_DUPLICATE_AND_COPY_RECEIPTS_REQUIRE_INDEPENDENT_CHECK")
        rows.append({
            "project_id": item.project_id,
            "source_digest": item.source_digest,
            "disposition": disposition,
            "reasons": reasons,
            "duplicate_of": item.duplicate_of,
            "receipt_refs_claimed_only": {
                "duplicate_review": item.duplicate_review_ref,
                "archive_copy": item.archive_copy_receipt_ref,
            },
            "delete_authorized": False,
        })
    body = {
        "schema": "VERA_CHATGPT_PROJECT_TRIAGE_V1",
        "status": "DRY_RUN_ONLY",
        "source_evidence": "CALLER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED",
        "privacy": "OWNER_PRIVATE_DO_NOT_PUBLISH",
        "memory_admission_effect": "NONE",
        "native_project_effect": "NONE",
        "delete_api_available": False,
        "records": rows,
    }
    body["sha256"] = sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    return body
