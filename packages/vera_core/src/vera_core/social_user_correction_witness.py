"""Host-assertion signature verifier for synthetic correction source research.

This module *cannot* authenticate a host, create a trusted key, determine
semantic truth, grant current consent, or admit canonical memory. An authorized
runtime owner must pin the expected public key, head and live session outside
the caller's messages. Signed data is only a signer assertion about exact bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import re

from .social_appraisal_preflight import (
    _ed25519_public_key,
    _ed25519_signature_valid,
)
from .social_revision_ledger import (
    CorrectionEntry,
    CorrectionLedger,
    PropositionType,
    RevisionConflict,
    SourceKind,
)


SCHEMA = "VERA_HOST_USER_CORRECTION_WITNESS_V1"
DOMAIN = b"VERA_HOST_USER_CORRECTION_V1\0"
ACTOR_ROLE = "authenticated_user"


def _exact_id(value: object, field: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValueError(f"{field} must be a nonblank exact ID <=256 characters")


def _sha256_id(value: object, field: str) -> None:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class SignedUserCorrectionV1:
    """Public-key signed correction claim, not a user-authentication token."""

    issuer_id: str
    key_id: str
    actor_id: str
    session_id: str
    turn_id: str
    subject_ref: str
    proposition_type: PropositionType
    source_kind: SourceKind
    event_id: str
    supersedes: str | None
    statement_sha256: str
    expected_previous_head: str
    resulting_head: str
    signature_b64: str

    def signed_bytes(self) -> bytes:
        """Canonical domain-separated claim including transition and referent."""
        for name in (
            "issuer_id", "key_id", "actor_id", "session_id",
            "turn_id", "subject_ref", "event_id",
        ):
            _exact_id(getattr(self, name), name)
        if self.supersedes is not None:
            _exact_id(self.supersedes, "supersedes")
        if type(self.proposition_type) is not PropositionType:
            raise ValueError("proposition_type must be a typed enum")
        if type(self.source_kind) is not SourceKind:
            raise ValueError("source_kind must be a typed enum")
        for name in (
            "statement_sha256", "expected_previous_head", "resulting_head"
        ):
            _sha256_id(getattr(self, name), name)
        payload = {
            "schema": SCHEMA,
            "issuer_id": self.issuer_id,
            "key_id": self.key_id,
            "actor_id": self.actor_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "subject_ref": self.subject_ref,
            "proposition_type": self.proposition_type.value,
            "source_kind": self.source_kind.value,
            "event_id": self.event_id,
            "supersedes": self.supersedes,
            "statement_sha256": self.statement_sha256,
            "expected_previous_head": self.expected_previous_head,
            "resulting_head": self.resulting_head,
        }
        return DOMAIN + json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class TrustedCorrectionVerifier:
    """Verifier for a public key pinned by the *external* host owner.

    Constructing this with an untrusted caller's public key does NOT establish
    trusted-host provenance; the caller must not provide its own trust roots.
    """

    issuer_id: str
    key_id: str
    public_key_bytes: bytes

    def __post_init__(self) -> None:
        _exact_id(self.issuer_id, "issuer_id")
        _exact_id(self.key_id, "key_id")
        if type(self.public_key_bytes) is not bytes or len(self.public_key_bytes) != 32:
            raise ValueError("Ed25519 public key must be exactly 32 bytes")
        _ed25519_public_key(self.public_key_bytes)

    def verify(
        self,
        witness: SignedUserCorrectionV1,
        *,
        ledger: CorrectionLedger,
        entry: CorrectionEntry,
        expected_session_id: str,
        expected_turn_id: str,
        expected_previous_head: str,
    ) -> bool:
        """Pure check of signer assertion, never commits or grants authority."""
        if (
            type(witness) is not SignedUserCorrectionV1
            or type(ledger) is not CorrectionLedger
            or type(entry) is not CorrectionEntry
        ):
            return False
        try:
            _exact_id(expected_session_id, "expected_session_id")
            _exact_id(expected_turn_id, "expected_turn_id")
            _sha256_id(expected_previous_head, "expected_previous_head")
            if (
                witness.issuer_id != self.issuer_id
                or witness.key_id != self.key_id
                or witness.actor_id != ACTOR_ROLE
                or witness.session_id != expected_session_id
                or witness.turn_id != expected_turn_id
                or entry.session_id != expected_session_id
                or entry.turn_id != expected_turn_id
                or entry.source_kind is not SourceKind.CURRENT_USER
                or witness.source_kind is not entry.source_kind
                or witness.proposition_type is not entry.proposition_type
                or witness.subject_ref != entry.subject_ref
                or witness.event_id != entry.event_id
                or witness.supersedes != entry.supersedes
                or witness.statement_sha256
                != hashlib.sha256(entry.statement.encode("utf-8")).hexdigest()
                or witness.expected_previous_head != expected_previous_head
                or ledger.head != expected_previous_head
            ):
                return False
            preview = ledger.append(entry, expected_head=expected_previous_head)
            if witness.resulting_head != preview.head:
                return False
            signed = witness.signed_bytes()
            if type(witness.signature_b64) is not str:
                return False
            signature = base64.b64decode(
                witness.signature_b64.encode("ascii"), validate=True
            )
            if len(signature) != 64:
                return False
            return _ed25519_signature_valid(
                self.public_key_bytes, signature, signed
            )
        except (
            UnicodeEncodeError, ValueError, TypeError, RevisionConflict,
        ):
            return False

    def public_receipt(
        self,
        witness: SignedUserCorrectionV1,
        *,
        ledger: CorrectionLedger,
        entry: CorrectionEntry,
        expected_session_id: str,
        expected_turn_id: str,
        expected_previous_head: str,
    ) -> dict[str, object]:
        """Recompute the check; never accept a caller-minted valid boolean.

        Still only an assertion under a caller-provided pin, not actual proof
        that a release-authorized host owns the pinned key.
        """
        valid = self.verify(
            witness, ledger=ledger, entry=entry,
            expected_session_id=expected_session_id,
            expected_turn_id=expected_turn_id,
            expected_previous_head=expected_previous_head,
        )
        return {
            "schema": SCHEMA,
            "signer_assertion_valid": valid,
            "qualification": "SIGNER_ASSERTION_ONLY_NOT_IDENTITY_OR_AUTHORITY",
            "verified_user_identity": False,
            "actual_host_currentness_established": False,
            "canonical_memory_admitted": False,
            "external_effect_authorized": False,
        }
