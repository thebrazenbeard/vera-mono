"""Pure, private-only projection from staged export rows to historical evidence.

This is a source-level adapter, NOT an importer, rights verifier, review
authority, or currentness provider. Caller-supplied review references remain
unverified declarations. No filesystem, network, ledger, training, or archive
effects occur here. Output can contain private text and source identifiers;
never publish it solely because the projection succeeds.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .historical_evidence import (
    HistoricalEvidenceAccessError,
    HistoricalEvidenceRecord,
    HistoricalEvidenceResult,
    query_historical_evidence,
)


MAX_STAGED_ROWS = 1024
MAX_TEXT_BYTES = 8192
MAX_ID_BYTES = 512
MAX_SCOPE_BYTES = 128
MAX_REVIEW_REF_BYTES = 512
MAX_TIME_BYTES = 64
MAX_AUTHORIZED_SOURCE_IDS = 256
MAX_AUTHORIZED_PRIVACY_SCOPES = 64
PROVENANCE_CEILING = "UNVERIFIED_EXPORT_SOURCE"
CURRENTNESS_RULE = "HISTORICAL_ONLY_NO_CURRENTNESS_CLAIM"
REVIEW_RECEIPT_STATUS = "REFERENCE_ONLY_UNVERIFIED"


class ExportProjectionError(ValueError):
    """Projection refuses an ambiguous or insufficiently bounded source."""


def _exact_nonempty(label: str, value: object, *, max_bytes: int) -> None:
    if type(value) is not str:
        raise ValueError(f"{label} must be an exact non-empty string without NUL")
    # Character count is a cheap rejection bound before encoding or stripping
    # potentially attacker-sized strings. UTF-8 byte length is authoritative.
    if len(value) > max_bytes:
        raise ValueError(f"{label} exceeds its UTF-8 byte limit")
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8 text") from exc
    if encoded_length > max_bytes:
        raise ValueError(f"{label} exceeds its UTF-8 byte limit")
    if not value.strip() or "\x00" in value:
        raise ValueError(f"{label} must be an exact non-empty string without NUL")


@dataclass(frozen=True, slots=True)
class StagedExportEvidence:
    """A caller-staged row; no review or data rights are authenticated here.

    ``source_sha256`` is a lineage identifier, not a privacy or rights grant.
    ``review_receipt_ref`` is an opaque citation, not a verified approval.
    Upstream private review must authorize each row before any real intake.
    """

    source_id: str
    source_sha256: str
    item_id: str
    privacy_scope: str
    review_authority_ref: str
    review_receipt_ref: str
    text: str
    event_time: str | None
    recorded_at: str | None
    effective_from: str | None

    def __post_init__(self) -> None:
        for label in ("source_id", "item_id"):
            _exact_nonempty(label, getattr(self, label), max_bytes=MAX_ID_BYTES)
        _exact_nonempty("privacy_scope", self.privacy_scope, max_bytes=MAX_SCOPE_BYTES)
        for label in ("review_authority_ref", "review_receipt_ref"):
            _exact_nonempty(label, getattr(self, label), max_bytes=MAX_REVIEW_REF_BYTES)
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.source_sha256)
        ):
            raise ValueError("source_sha256 must be a lowercase 64-character SHA-256 hex digest")
        if type(self.text) is not str:
            raise ValueError("text must be an exact string within the private row byte limit")
        if len(self.text) > MAX_TEXT_BYTES:
            raise ValueError("text exceeds its UTF-8 private row byte limit")
        try:
            text_length = len(self.text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise ValueError("text must be valid UTF-8 text") from exc
        if text_length > MAX_TEXT_BYTES:
            raise ValueError("text exceeds its UTF-8 private row byte limit")
        for label in ("event_time", "recorded_at", "effective_from"):
            value = getattr(self, label)
            if value is not None:
                _exact_nonempty(label, value, max_bytes=MAX_TIME_BYTES)


def project_staged_exports(
    rows: tuple[StagedExportEvidence, ...],
    *,
    authorized_privacy_scopes: tuple[str, ...],
    authorized_source_ids: tuple[str, ...],
    retrieved_at: str,
) -> HistoricalEvidenceResult:
    """Project bounded staged rows into scope-filtered, noncanonical evidence.

    The caller MUST separately authenticate the authority behind the supplied
    privacy scopes and source IDs. Duplicate row IDs and source digest
    collisions are rejected even for rows outside the selected scopes.
    This does not admit memory, authorize currentness, or write to any store.
    """

    if type(rows) is not tuple:
        raise TypeError("rows must be an exact tuple")
    if len(rows) > MAX_STAGED_ROWS:
        raise ExportProjectionError("staged export row limit exceeded")
    # The general historical query accepts iterables. At this untrusted
    # staging boundary, accepting a bare string could split it into character
    # scopes and inadvertently authorize a one-letter private scope.
    if type(authorized_privacy_scopes) is not tuple:
        raise TypeError("authorized_privacy_scopes must be an exact tuple")
    if not authorized_privacy_scopes or len(authorized_privacy_scopes) > MAX_AUTHORIZED_PRIVACY_SCOPES:
        raise HistoricalEvidenceAccessError("authorized_privacy_scopes count outside bounded range")
    for scope in authorized_privacy_scopes:
        _exact_nonempty("authorized_privacy_scopes", scope, max_bytes=MAX_SCOPE_BYTES)
    if len(authorized_privacy_scopes) != len(set(authorized_privacy_scopes)):
        raise HistoricalEvidenceAccessError("duplicate authorized privacy scope")
    if type(authorized_source_ids) is not tuple or not authorized_source_ids:
        raise ExportProjectionError("authorized_source_ids requires a non-empty exact tuple")
    if len(authorized_source_ids) > MAX_AUTHORIZED_SOURCE_IDS:
        raise ExportProjectionError("authorized_source_ids count exceeds limit")
    for source_id in authorized_source_ids:
        _exact_nonempty("authorized_source_ids", source_id, max_bytes=MAX_ID_BYTES)
    if len(authorized_source_ids) != len(set(authorized_source_ids)):
        raise ExportProjectionError("duplicate authorized source ID")
    _exact_nonempty("retrieved_at", retrieved_at, max_bytes=MAX_TIME_BYTES)

    selected_sources = set(authorized_source_ids)
    identities: set[tuple[str, str]] = set()
    source_digests: dict[str, str] = {}
    visible: list[HistoricalEvidenceRecord] = []
    for row in rows:
        if type(row) is not StagedExportEvidence:
            raise TypeError("rows must contain exact StagedExportEvidence values")
        identity = (row.source_id, row.item_id)
        if identity in identities:
            raise ExportProjectionError("duplicate staged export item identity")
        identities.add(identity)
        known_digest = source_digests.setdefault(row.source_id, row.source_sha256)
        if known_digest != row.source_sha256:
            raise ExportProjectionError("source ID rebinds to a different digest")
        if row.source_id not in selected_sources:
            continue
        # NUL is forbidden in the identity fields, keeping namespacing unique.
        key = sha256((row.source_id + "\x00" + row.item_id).encode("utf-8")).hexdigest()
        visible.append(
            HistoricalEvidenceRecord(
                memory_id="staged-export:" + key,
                privacy_scope=row.privacy_scope,
                event_time=row.event_time,
                recorded_at=row.recorded_at,
                effective_from=row.effective_from,
                source_ids=(row.source_id,),
                provenance_ceiling=PROVENANCE_CEILING,
                currentness_rule=CURRENTNESS_RULE,
                historical_canonicity="UNRESOLVED_HISTORY",
                content={
                    "text": row.text,
                    "source_sha256": row.source_sha256,
                    "review_authority_ref": row.review_authority_ref,
                    "review_receipt_ref": row.review_receipt_ref,
                    "review_receipt_status": REVIEW_RECEIPT_STATUS,
                },
            )
        )
    return query_historical_evidence(
        tuple(visible),
        authorized_privacy_scopes=authorized_privacy_scopes,
        retrieved_at=retrieved_at,
    )
