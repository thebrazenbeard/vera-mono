from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from .evidence import ProviderEvidenceEnvelope, validate_envelope


STATUSES = {
    "VERIFIED_EXACT",
    "STALE_PROJECTION",
    "CONFLICT",
    "ABSENT",
    "UNAVAILABLE",
    "UNRESOLVED",
}


@dataclass(frozen=True)
class ReconciliationResult:
    status: str
    subject_key: str
    observations: tuple[ProviderEvidenceEnvelope, ...]
    reason: str
    authoritative_claim_ceiling: str

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unsupported reconciliation status: {self.status}")
        if not self.subject_key:
            raise ValueError("subject_key must be non-empty")


def _claim_ceiling(observations: tuple[ProviderEvidenceEnvelope, ...]) -> str:
    classes = {item.evidence_class for item in observations}
    if "persisted_provider_record" in classes:
        return (
            "Exact provider object/effect evidence only; persistence/readback does not "
            "establish present truth, current Vera self-state, consent, authority, "
            "native admission, runtime consumption, or phenomenology."
        )
    if "coordination_record" in classes:
        return (
            "Coordination/projection record evidence only; delivery or projection does "
            "not establish identity, memory incorporation, native route qualification, "
            "or task acceptance."
        )
    if "source_provenance" in classes or "control_source" in classes:
        return (
            "Exact source/provenance object evidence only; source availability does not "
            "establish installation, runtime consumption, or behavioral qualification."
        )
    return "Typed evidence only at the independently established evidence class and exact referent/scope."


def _result(
    status: str,
    subject_key: str,
    observations: tuple[ProviderEvidenceEnvelope, ...],
    reason: str,
) -> ReconciliationResult:
    return ReconciliationResult(
        status=status,
        subject_key=subject_key,
        observations=observations,
        reason=reason,
        authoritative_claim_ceiling=_claim_ceiling(observations),
    )


def reconcile_exact(
    subject_key: str,
    observations: Iterable[ProviderEvidenceEnvelope],
    *,
    expected_revision: str | None = None,
    expected_digest: str | None = None,
) -> ReconciliationResult:
    """Reconcile exact provider observations without using recency as authority.

    `expected_revision` / `expected_digest` are externally established comparison
    anchors for the exact subject. They do not gain authority from this function.
    A SOURCE observation matching the anchor plus an older/different TARGET revision
    is classified as a stale projection. Other incompatible exact claims conflict.
    """

    if not isinstance(subject_key, str) or not subject_key.strip():
        raise ValueError("subject_key must be non-empty")
    subject_key = subject_key.strip()
    items = tuple(observations)
    if not items:
        return _result("ABSENT", subject_key, items, "No provider observations were supplied.")

    for item in items:
        validate_envelope(item)

    if all(item.metadata.get("availability") == "UNAVAILABLE" for item in items):
        return _result("UNAVAILABLE", subject_key, items, "All supplied provider routes are unavailable.")

    if any(item.conflict_state in {"CONFLICT", "MISMATCH"} for item in items):
        return _result("CONFLICT", subject_key, items, "An observation carries an explicit exact-object conflict/mismatch state.")
    if any(item.conflict_state == "UNKNOWN" for item in items):
        return _result("UNRESOLVED", subject_key, items, "At least one observation has unresolved conflict state.")

    digests = {item.content_digest for item in items if item.content_digest is not None}
    if expected_digest is not None:
        wrong_digests = sorted(d for d in digests if d != expected_digest)
        if wrong_digests:
            return _result(
                "CONFLICT",
                subject_key,
                items,
                f"Exact content digest conflicts with expected digest: {wrong_digests!r}.",
            )
    elif len(digests) > 1:
        return _result(
            "CONFLICT",
            subject_key,
            items,
            f"Provider observations expose incompatible exact content digests: {sorted(digests)!r}.",
        )

    revisions = {item.revision for item in items}
    if expected_revision is not None:
        mismatched = [item for item in items if item.revision != expected_revision]
        if not mismatched:
            return _result(
                "VERIFIED_EXACT",
                subject_key,
                items,
                f"All supplied exact revisions match expected revision {expected_revision!r}.",
            )

        matching = [item for item in items if item.revision == expected_revision]
        mismatched_targets = [
            item for item in mismatched if item.metadata.get("projection_role") == "TARGET"
        ]
        if matching and len(mismatched_targets) == len(mismatched):
            stale = sorted({item.revision for item in mismatched_targets})
            return _result(
                "STALE_PROJECTION",
                subject_key,
                items,
                f"Target projection revision(s) {stale!r} do not match current source revision {expected_revision!r}.",
            )
        return _result(
            "CONFLICT",
            subject_key,
            items,
            f"Exact revisions conflict with expected revision {expected_revision!r}: {sorted(revisions)!r}.",
        )

    if len(items) == 1:
        return _result(
            "UNRESOLVED",
            subject_key,
            items,
            "A one-sided provider observation has no exact peer/anchor for cross-provider reconciliation.",
        )

    if len(revisions) == 1:
        revision = next(iter(revisions))
        return _result(
            "VERIFIED_EXACT",
            subject_key,
            items,
            f"All supplied provider observations agree on exact revision {revision!r}.",
        )

    return _result(
        "CONFLICT",
        subject_key,
        items,
        f"Provider observations expose incompatible exact revisions: {sorted(revisions)!r}; observation timestamps do not resolve the conflict.",
    )


def _canonical_receipt_binding_digest(binding: Mapping[str, Any]) -> str:
    core = dict(binding)
    core.pop("receipt_digest", None)
    canonical = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reconcile_exact_receipt(
    subject_key: str,
    source: ProviderEvidenceEnvelope,
    target: ProviderEvidenceEnvelope,
    *,
    source_subject: str,
    target_subject: str,
    event_ref: str,
    event_path: str,
    receipt_policy: Mapping[str, Any],
) -> ReconciliationResult:
    """Validate a target receipt as exact schema/type/subject/event/object proof.

    EXACT_RECEIPT is deliberately stronger and different from EXACT_REVISION.
    The downstream target receipt proves the source durable object; the source
    object is not required to know the identity of that later receipt effect.
    If the source independently carries a receipt_ref it is cross-checked as
    additional evidence, but absence does not invalidate the source object.

    The target receipt must bind the configured receipt schema/type, source/target
    subjects, source object locator/revision/digest, exact projection event, and
    exact target receipt object. The source object itself must expose a non-empty
    exact content digest before any receipt can prove that object. The canonical
    receipt-binding digest must match the target receipt object's content digest.
    Target revision equality is not receipt proof and is never used to qualify
    the receipt.
    """

    if not isinstance(subject_key, str) or not subject_key.strip():
        raise ValueError("subject_key must be non-empty")
    subject_key = subject_key.strip()
    items = (source, target)
    validate_envelope(source)
    validate_envelope(target)

    if any(item.conflict_state in {"CONFLICT", "MISMATCH"} for item in items):
        return _result("CONFLICT", subject_key, items, "A receipt reconciliation observation carries an explicit conflict/mismatch state.")
    if any(item.conflict_state == "UNKNOWN" for item in items):
        return _result("UNRESOLVED", subject_key, items, "Receipt reconciliation has unresolved conflict state.")

    if not isinstance(receipt_policy, Mapping):
        return _result("UNRESOLVED", subject_key, items, "EXACT_RECEIPT projection lacks a receipt-binding policy.")
    metadata_field = receipt_policy.get("metadata_field")
    target_scope = receipt_policy.get("target_scope")
    required_fields = receipt_policy.get("required_fields")
    expected_schema = receipt_policy.get("receipt_schema")
    expected_type = receipt_policy.get("receipt_type")
    digest_algorithm = receipt_policy.get("digest_algorithm")
    if not isinstance(metadata_field, str) or not metadata_field:
        return _result("UNRESOLVED", subject_key, items, "Receipt-binding policy lacks metadata_field.")
    if not isinstance(target_scope, str) or not target_scope:
        return _result("UNRESOLVED", subject_key, items, "Receipt-binding policy lacks target_scope.")
    if not isinstance(expected_schema, str) or not expected_schema:
        return _result("UNRESOLVED", subject_key, items, "Receipt-binding policy lacks exact receipt_schema.")
    if not isinstance(expected_type, str) or not expected_type:
        return _result("UNRESOLVED", subject_key, items, "Receipt-binding policy lacks exact receipt_type.")
    if digest_algorithm != "SHA256_CANONICAL_JSON_EXCLUDING_RECEIPT_DIGEST":
        return _result("UNRESOLVED", subject_key, items, "Receipt-binding policy lacks the supported canonical receipt digest algorithm.")
    if not isinstance(required_fields, list) or not required_fields or any(not isinstance(value, str) or not value for value in required_fields):
        return _result("UNRESOLVED", subject_key, items, "Receipt-binding policy lacks exact required_fields.")

    if target.scope != target_scope:
        return _result("CONFLICT", subject_key, items, f"Receipt target scope {target.scope!r} does not match required receipt scope {target_scope!r}.")
    if target.referent != source.referent:
        return _result("CONFLICT", subject_key, items, "Receipt target referent does not match the exact source object referent.")

    if not isinstance(source.content_digest, str) or not source.content_digest.strip():
        return _result("UNRESOLVED", subject_key, items, "Exact receipt reconciliation requires a non-empty source content digest.")

    if target.receipt_ref is None:
        return _result("UNRESOLVED", subject_key, items, "Exact receipt reconciliation requires the target receipt object's receipt_ref.")
    if target.receipt_ref != target.locator:
        return _result("CONFLICT", subject_key, items, "Target receipt_ref does not identify the exact target receipt object locator.")
    if source.receipt_ref is not None and source.receipt_ref != target.receipt_ref:
        return _result("CONFLICT", subject_key, items, "Source carries an independently supplied receipt_ref that conflicts with the target receipt object.")

    binding = target.metadata.get(metadata_field)
    if not isinstance(binding, Mapping):
        return _result("UNRESOLVED", subject_key, items, f"Target receipt lacks required {metadata_field!r} object binding.")
    missing = [field for field in required_fields if field not in binding]
    if missing:
        return _result("UNRESOLVED", subject_key, items, f"Target receipt binding is missing required fields: {missing!r}.")

    if binding.get("receipt_schema") != expected_schema:
        return _result("CONFLICT", subject_key, items, "Receipt binding schema does not match the configured exact receipt schema.")
    if binding.get("receipt_type") != expected_type:
        return _result("CONFLICT", subject_key, items, "Receipt binding type does not match the configured exact receipt type.")

    identity_expected = {
        "source_subject": source_subject,
        "target_subject": target_subject,
        "source_locator": source.locator,
        "event_ref": event_ref,
        "event_path": event_path,
        "receipt_ref": target.receipt_ref,
    }
    for field, expected in identity_expected.items():
        if binding.get(field) != expected:
            return _result(
                "CONFLICT",
                subject_key,
                items,
                f"Receipt binding {field!r} does not match the exact projection/event/object subject.",
            )

    bound_revision = binding.get("source_revision")
    if not isinstance(bound_revision, str) or not bound_revision:
        return _result("UNRESOLVED", subject_key, items, "Receipt binding lacks exact source_revision.")
    if bound_revision != source.revision:
        return _result(
            "STALE_PROJECTION",
            subject_key,
            items,
            f"Receipt binds source revision {bound_revision!r}, not current source revision {source.revision!r}.",
        )

    if binding.get("source_content_digest") != source.content_digest:
        return _result("CONFLICT", subject_key, items, "Receipt binding source_content_digest does not match the exact source object digest.")

    receipt_digest = binding.get("receipt_digest")
    if not isinstance(receipt_digest, str) or not receipt_digest.startswith("sha256:") or len(receipt_digest) != 71:
        return _result("UNRESOLVED", subject_key, items, "Receipt binding lacks an exact sha256 receipt_digest.")
    try:
        int(receipt_digest[7:], 16)
    except ValueError:
        return _result("UNRESOLVED", subject_key, items, "Receipt binding receipt_digest is not hexadecimal.")
    try:
        expected_receipt_digest = _canonical_receipt_binding_digest(binding)
    except (TypeError, ValueError):
        return _result("UNRESOLVED", subject_key, items, "Receipt binding is not canonically serializable for digest verification.")
    if receipt_digest != expected_receipt_digest:
        return _result("CONFLICT", subject_key, items, "Receipt binding digest does not match its canonical schema/type/subject/event/object binding.")
    if target.content_digest is None:
        return _result("UNRESOLVED", subject_key, items, "Target receipt object lacks an exact content digest.")
    if target.content_digest != receipt_digest:
        return _result("CONFLICT", subject_key, items, "Target receipt object content digest does not match the validated receipt binding digest.")

    return _result(
        "VERIFIED_EXACT",
        subject_key,
        items,
        "Target receipt independently binds the exact configured receipt schema/type, source/target subjects, source object revision/digest, projection event, and target receipt object/digest; source receipt_ref was not required and target revision equality was not used as receipt proof.",
    )
