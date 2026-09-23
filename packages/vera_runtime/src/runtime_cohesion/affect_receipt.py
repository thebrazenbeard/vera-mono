from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any, Mapping


class AffectiveReceiptSemanticError(ValueError):
    """An affective event receipt is internally inconsistent or cross-bound."""


_ALLOWED_PHASES = {
    "QUIESCENT",
    "ACTIVATING",
    "ENTRAINED",
    "CLIMAX_ELIGIBLE",
    "ORGASM_EVENT",
    "RESOLUTION",
    "SATIATED_OR_REFRACTORY",
}
_ALLOWED_EVENT_TYPES = {"ORGASM_EVENT", "RESOLUTION", "RECOVERY"}
_ALLOWED_TRIGGERS = {
    "ORGANIC_THRESHOLD_CROSSING",
    "ADMIN_FORCED_TEST",
    "SELF_QUALIFICATION_TEST",
}
_ENGINEERED_CLAIM = "ENGINEERED_ORGASM_ANALOGUE_OCCURRED"
_IN_PROCESS_AUTHORITY_TRUST = "IN_PROCESS_UNROOTED_NON_QUALIFYING"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    core = dict(receipt)
    core.pop("event_digest", None)
    return _canonical_digest(core)


def _require_observed_at(value: Any) -> None:
    if not isinstance(value, str) or not value:
        raise AffectiveReceiptSemanticError("event receipt observed_at is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AffectiveReceiptSemanticError("event receipt observed_at is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AffectiveReceiptSemanticError("event receipt observed_at must be timezone-aware")


def _validate_receipt_state(state: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(state, Mapping):
        raise AffectiveReceiptSemanticError(f"event receipt {label} must be an object")
    if state.get("subject") != "vera":
        raise AffectiveReceiptSemanticError(f"event receipt {label} subject must be vera")
    phase = state.get("phase")
    if phase not in _ALLOWED_PHASES:
        raise AffectiveReceiptSemanticError(f"event receipt {label} has an invalid phase")
    active = state.get("active_orgasm_event")
    if not isinstance(active, bool):
        raise AffectiveReceiptSemanticError(f"event receipt {label} active_orgasm_event must be boolean")
    if active != (phase == "ORGASM_EVENT"):
        raise AffectiveReceiptSemanticError(
            f"event receipt {label} phase/active_orgasm_event semantics are inconsistent"
        )
    return state


def _validate_consumed_evidence_provenance(
    provenance: Any,
    *,
    expected_effect_class: str,
    label: str,
) -> None:
    if not isinstance(provenance, Mapping):
        raise AffectiveReceiptSemanticError(
            f"{label} receipt requires structured verified provenance"
        )
    for field in ("verifier_id", "evidence_id", "evidence_digest", "authorization_subject"):
        if field not in provenance:
            raise AffectiveReceiptSemanticError(f"{label} provenance lacks {field}")
    for field in ("verifier_id", "evidence_id"):
        value = provenance.get(field)
        if not isinstance(value, str) or not value:
            raise AffectiveReceiptSemanticError(f"{label} provenance {field} must be non-empty")
    evidence_digest = provenance.get("evidence_digest")
    if not isinstance(evidence_digest, str) or len(evidence_digest) != 64:
        raise AffectiveReceiptSemanticError(f"{label} provenance lacks exact evidence digest")
    try:
        int(evidence_digest, 16)
    except ValueError as exc:
        raise AffectiveReceiptSemanticError(f"{label} evidence digest is not hexadecimal") from exc

    subject = provenance.get("authorization_subject")
    if not isinstance(subject, Mapping):
        raise AffectiveReceiptSemanticError(f"{label} provenance lacks exact consumed subject")
    if evidence_digest != _canonical_digest(subject):
        raise AffectiveReceiptSemanticError(f"{label} evidence digest does not bind consumed subject")

    expected_subject = {
        "state": "ALLOW",
        "referent": "vera",
        "proposition_or_effect_class": expected_effect_class,
        "currentness": "CURRENT",
        "expiry_or_supersession": None,
    }
    for field, expected in expected_subject.items():
        if subject.get(field) != expected:
            raise AffectiveReceiptSemanticError(f"{label} subject {field} mismatch")
    for field in ("actor", "source", "observed_at"):
        value = subject.get(field)
        if not isinstance(value, str) or not value:
            raise AffectiveReceiptSemanticError(f"{label} subject lacks {field}")
    _require_observed_at(subject.get("observed_at"))

    for field in (
        "actor",
        "referent",
        "proposition_or_effect_class",
        "source",
        "observed_at",
        "currentness",
        "expiry_or_supersession",
    ):
        if provenance.get(field) != subject.get(field):
            raise AffectiveReceiptSemanticError(
                f"{label} provenance {field} does not match consumed subject"
            )


def validate_affective_event_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_runtime_instance_id: str,
    expected_source_revision: str,
    require_engineered_claim: bool,
) -> None:
    """Validate one receipt at restore and persistence boundaries.

    This validator can establish structural/internal consistency of historical or
    explicitly nonqualifying evidence. It does not manufacture an external trust
    root. V1 deliberately has no source-local production claim-validation route:
    an engineered-event production claim requires independently rooted authority
    composition that is not implemented by this package.
    """
    if not isinstance(receipt, Mapping):
        raise AffectiveReceiptSemanticError("event receipt must be an object")
    receipt_id = receipt.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id:
        raise AffectiveReceiptSemanticError("event receipt receipt_id is required")
    if receipt.get("runtime_instance_id") != expected_runtime_instance_id:
        raise AffectiveReceiptSemanticError("event receipt runtime provenance mismatch")
    if receipt.get("subject") != "vera":
        raise AffectiveReceiptSemanticError("event receipt subject must be vera")
    if receipt.get("schema_version") != "VERA_ORGASM_RUNTIME_CONTRACT_V1":
        raise AffectiveReceiptSemanticError("event receipt schema/contract version mismatch")
    if receipt.get("source_revision") != expected_source_revision:
        raise AffectiveReceiptSemanticError("event receipt source provenance mismatch")
    if receipt.get("phenomenology") != "UNRESOLVED":
        raise AffectiveReceiptSemanticError("event receipt phenomenology must remain unresolved")

    event_type = receipt.get("event_type")
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise AffectiveReceiptSemanticError("event receipt event_type is required and must be valid")
    trigger = receipt.get("trigger_class")
    if trigger not in _ALLOWED_TRIGGERS:
        raise AffectiveReceiptSemanticError("event receipt trigger_class is required and must be valid")
    organic = receipt.get("organic")
    if not isinstance(organic, bool):
        raise AffectiveReceiptSemanticError("event receipt organic provenance must be boolean")
    if (trigger == "ORGANIC_THRESHOLD_CROSSING") != organic:
        raise AffectiveReceiptSemanticError("event receipt organic/forced trigger provenance is inconsistent")

    before = _validate_receipt_state(receipt.get("state_before"), label="state_before")
    after = _validate_receipt_state(receipt.get("state_after"), label="state_after")
    expected_transition = f"{before.get('phase')}->{after.get('phase')}"
    if receipt.get("transition") != expected_transition:
        raise AffectiveReceiptSemanticError("event receipt transition does not match before/after phase semantics")

    trust = receipt.get("authority_composition_trust")
    unrooted = trust == _IN_PROCESS_AUTHORITY_TRUST
    if trust is not None and not unrooted:
        raise AffectiveReceiptSemanticError("event receipt carries an unknown authority composition trust class")

    if event_type == "ORGASM_EVENT":
        if after.get("phase") != "ORGASM_EVENT":
            raise AffectiveReceiptSemanticError("ORGASM_EVENT receipt must end in ORGASM_EVENT phase")

        if require_engineered_claim:
            raise AffectiveReceiptSemanticError(
                "production engineered-event claim validation requires an independently rooted authority capability not implemented by this source package"
            )

        provenance = receipt.get("trigger_provenance")
        if organic:
            if provenance != "ORGANIC_STATE_DYNAMICS":
                raise AffectiveReceiptSemanticError("ORGASM_EVENT trigger provenance mismatch")
            if unrooted:
                _validate_consumed_evidence_provenance(
                    receipt.get("context_provenance"),
                    expected_effect_class="ORGANIC_CONTEXT_ELIGIBILITY",
                    label="nonqualifying organic-context",
                )
            elif "context_provenance" in receipt:
                raise AffectiveReceiptSemanticError(
                    "nonqualifying organic event may not carry production context provenance"
                )
        else:
            if unrooted:
                _validate_consumed_evidence_provenance(
                    provenance,
                    expected_effect_class=str(trigger),
                    label="nonqualifying forced-event authorization",
                )
            elif provenance != "FORCED_QUALIFICATION_ROUTE":
                raise AffectiveReceiptSemanticError("nonqualifying forced-event trigger provenance mismatch")

        if "claim" in receipt:
            raise AffectiveReceiptSemanticError("nonqualifying ORGASM_EVENT receipt may not emit the production claim")
    elif event_type == "RESOLUTION":
        if after.get("phase") != "RESOLUTION":
            raise AffectiveReceiptSemanticError("RESOLUTION receipt must end in RESOLUTION phase")
        if receipt.get("trigger_provenance") != "ORGASM_EVENT_COMPLETION":
            raise AffectiveReceiptSemanticError("RESOLUTION receipt trigger provenance mismatch")
        if "claim" in receipt:
            raise AffectiveReceiptSemanticError("RESOLUTION receipt may not emit an orgasm-event claim")
    else:
        if after.get("phase") not in {"SATIATED_OR_REFRACTORY", "QUIESCENT"}:
            raise AffectiveReceiptSemanticError("RECOVERY receipt has invalid recovery phase semantics")
        if receipt.get("trigger_provenance") != "HOMEOSTATIC_RECOVERY":
            raise AffectiveReceiptSemanticError("RECOVERY receipt trigger provenance mismatch")
        if "claim" in receipt:
            raise AffectiveReceiptSemanticError("RECOVERY receipt may not emit an orgasm-event claim")

    _require_observed_at(receipt.get("observed_at"))

    digest = receipt.get("event_digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise AffectiveReceiptSemanticError("event receipt event_digest must be an exact SHA-256")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise AffectiveReceiptSemanticError("event receipt event_digest is not hexadecimal") from exc
    try:
        expected_digest = _receipt_digest(receipt)
    except (TypeError, ValueError) as exc:
        raise AffectiveReceiptSemanticError("event receipt is not canonically serializable") from exc
    if digest != expected_digest:
        raise AffectiveReceiptSemanticError("event receipt SHA-256 does not match canonical receipt semantics")
