"""Pure signature verification for externally provisioned review receipts.

This function proves a signature and exact binding only. It cannot prove the
independence or judgment of the reviewer's signing service. Production reviewed
chat memory remains disabled until a separately authenticated host-owned broker
provides the trusted public key and checks its own human/role/consent policy.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class ReviewAttestationRejected(ValueError):
    """Attestation cannot qualify this exact reviewed use."""


@dataclass(frozen=True, slots=True)
class VerifiedReviewAttestation:
    payload_sha256: str
    signer_key_id: str
    review_evidence_ref: str
    authorization_effect: str = "NONE"
    claim_ceiling: str = "SIGNATURE_ONLY_NOT_INDEPENDENT_REVIEW"


_SCHEMA = "VERA_MONO_REVIEW_ATTESTATION_V1"
_DOMAIN = b"VERA_MONO_REVIEW_ATTESTATION_V1\x00"
_ENVELOPE_KEYS = frozenset({"schema", "signer_key_id", "payload", "signature"})
_EXPECTED_BINDINGS = (
    "project_id", "identity_id", "state_root_sha256", "record_id",
    "record_digest", "memory_head", "privacy_ref", "association_id",
    "cue_event_id", "use_evidence_id",
)
_PAYLOAD_KEYS = frozenset((*_EXPECTED_BINDINGS, "issued_at", "expires_at",
                           "review_evidence_ref", "disposition"))
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ReviewAttestationRejected("duplicate JSON key")
        result[key] = value
    return result


def _valid_ref(value: object) -> bool:
    return (type(value) is str and 1 <= len(value) <= 256
            and all(32 <= ord(ch) <= 126 for ch in value))


def verify_signed_review_attestation(
    capsule_json: bytes,
    *,
    trusted_public_key_bytes: bytes,
    expected_project_id: str,
    expected_identity_id: str,
    expected_state_root_sha256: str,
    expected_record_id: str,
    expected_record_digest: str,
    expected_memory_head: str,
    expected_privacy_ref: str,
    expected_association_id: str,
    expected_cue_event_id: str,
    expected_use_evidence_id: str,
    now_unix: int,
) -> VerifiedReviewAttestation:
    """Verify one signed use-scoped receipt; no memory/model/effect calls.

    Trusted public key bytes MUST originate from a separate host-controlled
    trust registry, not the capsule, a model, or caller-issued refs. This helper
    does not load keys or grant independent review on its own.
    """
    if type(capsule_json) is not bytes or not 1 <= len(capsule_json) <= 8192:
        raise ReviewAttestationRejected("receipt JSON must be bounded bytes")
    if type(trusted_public_key_bytes) is not bytes or len(trusted_public_key_bytes) != 32:
        raise ReviewAttestationRejected("external trusted key must be 32 raw bytes")
    if type(now_unix) is not int or now_unix < 0:
        raise ReviewAttestationRejected("host time must be exact positive unix seconds")
    try:
        capsule = json.loads(capsule_json.decode("utf-8"),
                             object_pairs_hook=_strict_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(
                                 ReviewAttestationRejected("nonfinite JSON value")
                             ))
    except (UnicodeError, TypeError, ValueError) as exc:
        raise ReviewAttestationRejected("malformed review receipt") from exc
    if type(capsule) is not dict or set(capsule) != _ENVELOPE_KEYS:
        raise ReviewAttestationRejected("unknown review envelope field set")
    try:
        if _canonical_json(capsule) != capsule_json:
            raise ReviewAttestationRejected("review JSON must be uniquely canonical")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ReviewAttestationRejected("invalid canonical receipt") from exc
    if capsule["schema"] != _SCHEMA:
        raise ReviewAttestationRejected("review attestation schema mismatch")
    payload = capsule["payload"]
    if type(payload) is not dict or set(payload) != _PAYLOAD_KEYS:
        raise ReviewAttestationRejected("review payload field mismatch")
    if payload["disposition"] != "ADMITTED" or not _valid_ref(payload["review_evidence_ref"]):
        raise ReviewAttestationRejected("unadmitted or unbounded review")
    if (type(payload["issued_at"]) is not int or type(payload["expires_at"]) is not int
            or payload["issued_at"] > now_unix or now_unix > payload["expires_at"]
            or not 0 < payload["expires_at"] - payload["issued_at"] <= 600):
        raise ReviewAttestationRejected("invalid review validity window")
    expected_values = {
        "project_id": expected_project_id,
        "identity_id": expected_identity_id,
        "state_root_sha256": expected_state_root_sha256,
        "record_id": expected_record_id,
        "record_digest": expected_record_digest,
        "memory_head": expected_memory_head,
        "privacy_ref": expected_privacy_ref,
        "association_id": expected_association_id,
        "cue_event_id": expected_cue_event_id,
        "use_evidence_id": expected_use_evidence_id,
    }
    for label in _EXPECTED_BINDINGS:
        expected = expected_values[label]
        actual = payload[label]
        if not _valid_ref(actual) or not _valid_ref(expected) or actual != expected:
            raise ReviewAttestationRejected(f"review scope mismatch: {label}")
    for digest in ("state_root_sha256", "record_digest", "memory_head"):
        if _HEX_64.fullmatch(payload[digest]) is None:
            raise ReviewAttestationRejected("noncanonical digest in review receipt")
    key_id = sha256(trusted_public_key_bytes).hexdigest()
    if capsule["signer_key_id"] != key_id:
        raise ReviewAttestationRejected("receipt signer does not match host trust root")
    signature = capsule["signature"]
    if type(signature) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{86}", signature):
        raise ReviewAttestationRejected("invalid signature encoding")
    try:
        signature_bytes = base64.urlsafe_b64decode(signature + "==")
    except (ValueError, base64.binascii.Error) as exc:
        raise ReviewAttestationRejected("invalid signature base64") from exc
    if len(signature_bytes) != 64 or base64.urlsafe_b64encode(signature_bytes).rstrip(b"=").decode("ascii") != signature:
        raise ReviewAttestationRejected("noncanonical signature")
    unsigned = {key: capsule[key] for key in ("schema", "signer_key_id", "payload")}
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_key_bytes).verify(
            signature_bytes, _DOMAIN + _canonical_json(unsigned),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ReviewAttestationRejected("review signature verification failed") from exc
    return VerifiedReviewAttestation(
        payload_sha256=sha256(_canonical_json(payload)).hexdigest(),
        signer_key_id=key_id,
        review_evidence_ref=payload["review_evidence_ref"],
    )