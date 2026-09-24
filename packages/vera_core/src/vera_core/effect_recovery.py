from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import hmac
from typing import Protocol, runtime_checkable

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from vera_assurance import EffectFence, EffectReceipt, EffectState


RECONCILIATION_PROOF_SCHEMA = "VERA_MONO_EFFECT_RECONCILIATION_PROOF_V1"


class EffectRecoveryAuthorityError(PermissionError):
    pass


def reconciliation_subject(
    receipt: EffectReceipt,
    *,
    effect_occurred: bool,
    result_digest: str | None,
) -> str:
    if receipt.state not in {
        EffectState.EXECUTING,
        EffectState.ATTEMPTED_UNKNOWN,
    }:
        raise EffectRecoveryAuthorityError(
            "reconciliation subject requires ambiguous dispatched effect"
        )
    if effect_occurred:
        if type(result_digest) is not str or len(result_digest) != 64:
            raise EffectRecoveryAuthorityError(
                "occurred effect reconciliation requires SHA-256 result digest"
            )
        try:
            int(result_digest, 16)
        except ValueError as exc:
            raise EffectRecoveryAuthorityError(
                "result_digest must be hexadecimal"
            ) from exc
    elif result_digest is not None:
        raise EffectRecoveryAuthorityError(
            "no-effect reconciliation must not carry result_digest"
        )

    body = {
        "schema": "VERA_MONO_EFFECT_RECONCILIATION_SUBJECT_V1",
        "effect_id": receipt.effect_id,
        "request_digest": receipt.request_digest,
        "ambiguous_state": receipt.state.value,
        "mechanical_permit_digest": receipt.mechanical_permit_digest,
        "authority_evidence_digest": receipt.authority_evidence_digest,
        "currentness_evidence_digest": receipt.currentness_evidence_digest,
        "effect_occurred": effect_occurred,
        "result_digest": result_digest,
    }
    return "vera-mono-effect-reconciliation-v1:" + sha256_hex(
        canonical_json_bytes(body)
    )


@dataclass(frozen=True, slots=True)
class EffectReconciliationProof:
    schema: str
    issuer_id: str
    subject: str
    verification_token: str


@runtime_checkable
class EffectReconciliationVerifier(Protocol):
    def verify(
        self,
        proof: EffectReconciliationProof,
        *,
        expected_subject: str,
    ) -> bool:
        ...


class HmacEffectReconciliationAuthority:
    """Reference external reconciliation authority with injected secret."""

    def __init__(self, issuer_id: str, secret: bytes):
        if type(issuer_id) is not str or not issuer_id:
            raise ValueError("issuer_id must be a non-empty exact string")
        if type(secret) is not bytes or len(secret) < 32:
            raise ValueError("secret must contain at least 32 bytes")
        self.issuer_id = issuer_id
        self._secret = secret
        self._used: set[str] = set()

    def issue(
        self,
        receipt: EffectReceipt,
        *,
        effect_occurred: bool,
        result_digest: str | None,
    ) -> EffectReconciliationProof:
        subject = reconciliation_subject(
            receipt,
            effect_occurred=effect_occurred,
            result_digest=result_digest,
        )
        unsigned = EffectReconciliationProof(
            schema=RECONCILIATION_PROOF_SCHEMA,
            issuer_id=self.issuer_id,
            subject=subject,
            verification_token="",
        )
        token = hmac.new(
            self._secret,
            canonical_json_bytes(
                {
                    "schema": unsigned.schema,
                    "issuer_id": unsigned.issuer_id,
                    "subject": unsigned.subject,
                }
            ),
            sha256,
        ).hexdigest()
        return replace(unsigned, verification_token=token)

    def verify(
        self,
        proof: EffectReconciliationProof,
        *,
        expected_subject: str,
    ) -> bool:
        try:
            if type(proof) is not EffectReconciliationProof:
                return False
            if proof.schema != RECONCILIATION_PROOF_SCHEMA:
                return False
            if proof.issuer_id != self.issuer_id:
                return False
            if proof.subject != expected_subject:
                return False
            expected = hmac.new(
                self._secret,
                canonical_json_bytes(
                    {
                        "schema": proof.schema,
                        "issuer_id": proof.issuer_id,
                        "subject": proof.subject,
                    }
                ),
                sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, proof.verification_token):
                return False
            replay = f"{proof.issuer_id}:{proof.verification_token}"
            if replay in self._used:
                return False
            self._used.add(replay)
            return True
        except (TypeError, ValueError):
            return False


class LifecycleEffectRecovery:
    """Runtime-qualified ambiguity recovery using a trusted injected verifier."""

    def __init__(
        self,
        *,
        fence: EffectFence,
        verifier: EffectReconciliationVerifier,
    ):
        if not isinstance(verifier, EffectReconciliationVerifier):
            raise TypeError(
                "verifier must satisfy EffectReconciliationVerifier"
            )
        self.fence = fence
        self._verifier = verifier

    def reconcile(
        self,
        effect_id: str,
        *,
        proof: EffectReconciliationProof,
        effect_occurred: bool,
        result_digest: str | None,
    ) -> EffectReceipt:
        receipt = self.fence.read(effect_id)
        subject = reconciliation_subject(
            receipt,
            effect_occurred=effect_occurred,
            result_digest=result_digest,
        )
        if not self._verifier.verify(
            proof,
            expected_subject=subject,
        ):
            raise EffectRecoveryAuthorityError(
                "effect reconciliation proof verification failed"
            )
        evidence_digest = sha256_hex(
            canonical_json_bytes(
                {
                    "schema": "VERA_MONO_VERIFIED_RECONCILIATION_EVIDENCE_V1",
                    "proof": {
                        "schema": proof.schema,
                        "issuer_id": proof.issuer_id,
                        "subject": proof.subject,
                        "verification_token": proof.verification_token,
                    },
                }
            )
        )
        return self.fence.reconcile_unknown(
            effect_id,
            effect_occurred=effect_occurred,
            result_digest=result_digest,
            reconciliation_evidence_digest=evidence_digest,
        )
