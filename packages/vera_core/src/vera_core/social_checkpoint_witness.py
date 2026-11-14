"""Source-only signed checkpoint assertion for host-controlled correction ledgers.

A signature is not proof of independent host custody, current user input,
one-time use, consent or production authorization. External epoch/head must
come from a separately protected source, never the caller's own snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import re

from .social_appraisal_preflight import (
    _ed25519_public_key, _ed25519_signature_valid,
)

SCHEMA = "VERA_SOCIAL_CHECKPOINT_HOST_ASSERTION_V1"
DOMAIN = b"VERA_SOCIAL_CHECKPOINT_ATTESTATION_V1\0"
CHECKPOINT_GENESIS = hashlib.sha256(
    b"VERA_SOCIAL_CHECKPOINT_GENESIS_V1\0"
).hexdigest()


def _text(value: object, field: str) -> None:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ValueError(f"{field} must be a bounded nonblank exact string")


def _digest(value: object, field: str, width: int = 64) -> None:
    if type(value) is not str or re.fullmatch(
        rf"[0-9a-f]{{{width}}}", value
    ) is None:
        raise ValueError(f"{field} must be lowercase hex digest")


def _count(value: object, field: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not (minimum <= value <= maximum):
        raise ValueError(f"{field} must be integer between {minimum} and {maximum}")


@dataclass(frozen=True, slots=True)
class SignedSocialCheckpointV1:
    """Host signer *assertion* of a social correction candidate fence head."""

    issuer_id: str
    key_id: str
    installation_id: str
    source_session_id: str
    release_commit: str
    correction_key_sha256: str
    candidate_count: int
    fence_head: str
    previous_checkpoint_digest: str
    monotonic_epoch: int
    signature_b64: str

    def signed_bytes(self) -> bytes:
        for field in (
            "issuer_id", "key_id", "installation_id", "source_session_id"
        ):
            _text(getattr(self, field), field)
        _digest(self.release_commit, "release_commit", 40)
        for field in (
            "correction_key_sha256", "fence_head", "previous_checkpoint_digest"
        ):
            _digest(getattr(self, field), field)
        _count(self.candidate_count, "candidate_count", 0, 256)
        _count(self.monotonic_epoch, "monotonic_epoch", 1, 2**63 - 1)
        payload = {
            "schema": SCHEMA,
            "issuer_id": self.issuer_id,
            "key_id": self.key_id,
            "installation_id": self.installation_id,
            "source_session_id": self.source_session_id,
            "release_commit": self.release_commit,
            "correction_key_sha256": self.correction_key_sha256,
            "candidate_count": self.candidate_count,
            "fence_head": self.fence_head,
            "previous_checkpoint_digest": self.previous_checkpoint_digest,
            "monotonic_epoch": self.monotonic_epoch,
        }
        return DOMAIN + json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")


@dataclass(frozen=True, slots=True)
class TrustedCheckpointVerifier:
    """Uses an external pinned key; caller-chosen pins are NOT trusted hosts."""

    issuer_id: str
    key_id: str
    public_key_bytes: bytes

    def __post_init__(self) -> None:
        _text(self.issuer_id, "issuer_id")
        _text(self.key_id, "key_id")
        if type(self.public_key_bytes) is not bytes or len(self.public_key_bytes) != 32:
            raise ValueError("host public key must be raw Ed25519 32 bytes")
        _ed25519_public_key(self.public_key_bytes)

    def verify(
        self, checkpoint: SignedSocialCheckpointV1, *,
        expected_installation_id: str,
        expected_session_id: str,
        expected_release_commit: str,
        expected_correction_key_sha256: str,
        expected_candidate_count: int,
        expected_fence_head: str,
        expected_previous_checkpoint_digest: str,
        expected_monotonic_epoch: int,
    ) -> bool:
        if type(checkpoint) is not SignedSocialCheckpointV1:
            return False
        try:
            for field, value in (
                ("expected_installation_id", expected_installation_id),
                ("expected_session_id", expected_session_id),
            ):
                _text(value, field)
            _digest(expected_release_commit, "expected_release_commit", 40)
            for field, value in (
                ("expected_correction_key_sha256", expected_correction_key_sha256),
                ("expected_fence_head", expected_fence_head),
                ("expected_previous_checkpoint_digest", expected_previous_checkpoint_digest),
            ):
                _digest(value, field)
            _count(expected_candidate_count, "expected_candidate_count", 0, 256)
            _count(expected_monotonic_epoch, "expected_monotonic_epoch", 1, 2**63 - 1)
            if (
                checkpoint.issuer_id != self.issuer_id
                or checkpoint.key_id != self.key_id
                or checkpoint.installation_id != expected_installation_id
                or checkpoint.source_session_id != expected_session_id
                or checkpoint.release_commit != expected_release_commit
                or checkpoint.correction_key_sha256 != expected_correction_key_sha256
                or checkpoint.candidate_count != expected_candidate_count
                or checkpoint.fence_head != expected_fence_head
                or checkpoint.previous_checkpoint_digest != expected_previous_checkpoint_digest
                or checkpoint.monotonic_epoch != expected_monotonic_epoch
            ):
                return False
            payload = checkpoint.signed_bytes()
            if type(checkpoint.signature_b64) is not str:
                return False
            signature = base64.b64decode(
                checkpoint.signature_b64.encode("ascii"), validate=True
            )
            if len(signature) != 64:
                return False
            return _ed25519_signature_valid(
                self.public_key_bytes, signature, payload
            )
        except (ValueError, TypeError, UnicodeEncodeError):
            return False

    def public_receipt(
        self, checkpoint: SignedSocialCheckpointV1, **expected: object
    ) -> dict[str, object]:
        """Recompute signed assertion, never trust a caller-minted boolean."""
        valid = self.verify(checkpoint, **expected)
        return {
            "schema": SCHEMA,
            "signature_valid_under_supplied_key": valid,
            "qualification": "SIGNED_ASSERTION_ONLY_NO_HOST_OWNERSHIP",
            "independent_host_custody_verified": False,
            "actual_user_source_verified": False,
            "canonical_memory_admitted": False,
            "external_effect_authorized": False,
        }

def reopen_synthetic_fence_from_signed_checkpoint(
    *,
    path: str,
    installation_id: str,
    source_session_id: str,
    release_commit: str,
    correction_verifier: object,
    checkpoint_verifier: TrustedCheckpointVerifier,
    checkpoint: SignedSocialCheckpointV1,
    expected_monotonic_epoch: int,
    expected_previous_checkpoint_digest: str,
):
    """Open a synthetic fence only after a second key signs its exact state.

    The checkpoint signer is not authenticated by this interface. Its public
    key and external epoch MUST be pinned by a separate owner in any eventual
    real host. This method does not admit corrections or authorize effects.
    """
    from .social_correction_replay_fence import (
        CorrectionReplayFence, FenceBlocked,
    )
    from .social_user_correction_witness import TrustedCorrectionVerifier

    if (
        type(correction_verifier) is not TrustedCorrectionVerifier
        or type(checkpoint_verifier) is not TrustedCheckpointVerifier
        or type(checkpoint) is not SignedSocialCheckpointV1
    ):
        raise FenceBlocked("typed signer and checkpoint verifier required")
    correction_key_sha256 = hashlib.sha256(
        correction_verifier.public_key_bytes
    ).hexdigest()
    if not checkpoint_verifier.verify(
        checkpoint,
        expected_installation_id=installation_id,
        expected_session_id=source_session_id,
        expected_release_commit=release_commit,
        expected_correction_key_sha256=correction_key_sha256,
        expected_candidate_count=checkpoint.candidate_count,
        expected_fence_head=checkpoint.fence_head,
        expected_previous_checkpoint_digest=expected_previous_checkpoint_digest,
        expected_monotonic_epoch=expected_monotonic_epoch,
    ):
        raise FenceBlocked("host checkpoint signature/scope rejected")
    fence = CorrectionReplayFence(
        path, installation_id=installation_id,
        verifier=correction_verifier,
        trusted_checkpoint_head=checkpoint.fence_head,
        synthetic_fixture_mode=True,
    )
    if fence.recorded_count != checkpoint.candidate_count:
        raise FenceBlocked("checkpoint candidate count diverged")
    return fence
