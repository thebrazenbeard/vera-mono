import base64
import hashlib
import json
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from research.goal1_evaluator.dispatch_attestation import (
    Ed25519DispatchEvidenceVerifier,
    canonical_attestation_bytes,
)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixture(tmp_path):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    verifier = Ed25519DispatchEvidenceVerifier(
        trusted_public_key=public,
        trusted_gateway_id="gateway-test-key-01",
        replay_db=str(tmp_path / "dispatch-replay.sqlite"),
        expected_model_identity="model-v1",
        expected_model_artifact_sha256="a" * 64,
    )
    fields = {
        "witness_kind": "independent_dispatch_gateway",
        "gateway_id": "gateway-test-key-01",
        "attestation_id": "att-001",
        "invocation_id": "inv-001",
        "reservation_id": "res-001",
        "run_id": "run-001",
        "arm": "LEARNED",
        "challenge_id": "case-001",
        "challenge_view_digest": sha("challenge"),
        "model_prompt_sha256": sha("exact prompt"),
        "model_response_sha256": sha("exact response"),
        "model_identity": "model-v1",
        "model_artifact_sha256": "a" * 64,
        "dispatch_monotonic_ns": 100,
        "response_monotonic_ns": 250,
        "outcome_status": "COMPLETED",
        "resource_usage": {"input_tokens": 8, "output_tokens": 2, "wall_time_ms": 150},
    }
    verifier.reserve_invocation(
        reservation_id=fields["reservation_id"],
        run_id=fields["run_id"],
        arm=fields["arm"],
        challenge_id=fields["challenge_id"],
        challenge_view_digest=fields["challenge_view_digest"],
        model_prompt_sha256=fields["model_prompt_sha256"],
        expected_model_identity=fields["model_identity"],
        expected_model_artifact_sha256=fields["model_artifact_sha256"],
    )
    return verifier, private, fields


def sign(private, fields):
    payload = dict(fields)
    payload["signature"] = base64.b64encode(private.sign(canonical_attestation_bytes(fields))).decode()
    return payload


def test_valid_signed_receipt_is_bound_to_preissued_reservation_and_measured_usage(tmp_path):
    verifier, private, fields = fixture(tmp_path)
    verified = verifier.verify(sign(private, fields))
    assert verified is True


def test_self_asserted_witness_and_fake_boolean_verifier_are_not_cryptographic_evidence(tmp_path):
    verifier, _, fields = fixture(tmp_path)
    with pytest.raises((ValueError, TypeError)):
        verifier.verify({**fields, "signature": "I am independent"})
    with pytest.raises((ValueError, TypeError)):
        Ed25519DispatchEvidenceVerifier(trusted_public_key=b"not-a-key", trusted_gateway_id="g",
            replay_db=str(tmp_path / "bad.sqlite"), expected_model_identity="model-v1",
            expected_model_artifact_sha256="a" * 64)


@pytest.mark.parametrize("field,value", [
    ("run_id", "other-run"),
    ("arm", "FROZEN"),
    ("challenge_id", "other-case"),
    ("challenge_view_digest", "0" * 64),
    ("model_prompt_sha256", "1" * 64),
    ("model_response_sha256", "2" * 64),
    ("model_identity", "other-model"),
    ("model_artifact_sha256", "b" * 64),
    ("outcome_status", "OUTCOME_UNKNOWN"),
    ("response_monotonic_ns", 50),
    ("resource_usage", {"input_tokens": 0, "output_tokens": 0, "wall_time_ms": 0}),
])
def test_signed_but_substituted_or_incomplete_evidence_is_rejected(tmp_path, field, value):
    verifier, private, fields = fixture(tmp_path)
    receipt = sign(private, fields)
    receipt[field] = value
    with pytest.raises(ValueError):
        verifier.verify(receipt)


def test_receipt_replay_is_rejected_after_verifier_reopen(tmp_path):
    verifier, private, fields = fixture(tmp_path)
    receipt = sign(private, fields)
    verifier.verify(receipt)
    reopened = Ed25519DispatchEvidenceVerifier(
        trusted_public_key=private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
        trusted_gateway_id="gateway-test-key-01",
        replay_db=str(tmp_path / "dispatch-replay.sqlite"),
        expected_model_identity="model-v1",
        expected_model_artifact_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="replay|consumed|reservation"):
        reopened.verify(receipt)


def test_invocation_must_be_reserved_before_dispatch(tmp_path):
    verifier, private, fields = fixture(tmp_path)
    verifier2 = Ed25519DispatchEvidenceVerifier(
        trusted_public_key=private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw),
        trusted_gateway_id="gateway-test-key-01",
        replay_db=str(tmp_path / "empty.sqlite"),
        expected_model_identity="model-v1",
        expected_model_artifact_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="reservation"):
        verifier2.verify(sign(private, fields))


def test_duplicate_reservation_and_reused_invocation_are_rejected(tmp_path):
    verifier, private, fields = fixture(tmp_path)
    with pytest.raises(ValueError, match="reservation"):
        verifier.reserve_invocation(
            reservation_id=fields["reservation_id"], run_id=fields["run_id"], arm=fields["arm"],
            challenge_id=fields["challenge_id"], challenge_view_digest=fields["challenge_view_digest"],
            model_prompt_sha256=fields["model_prompt_sha256"], expected_model_identity=fields["model_identity"],
            expected_model_artifact_sha256=fields["model_artifact_sha256"],
        )
    verifier.verify(sign(private, fields))
    second = dict(fields, reservation_id="res-002", attestation_id="att-002", challenge_id="case-002", challenge_view_digest=sha("challenge-2"))
    verifier.reserve_invocation(
        reservation_id=second["reservation_id"], run_id=second["run_id"], arm=second["arm"],
        challenge_id=second["challenge_id"], challenge_view_digest=second["challenge_view_digest"],
        model_prompt_sha256=second["model_prompt_sha256"], expected_model_identity=second["model_identity"],
        expected_model_artifact_sha256=second["model_artifact_sha256"],
    )
    with pytest.raises(ValueError, match="invocation|replay"):
        verifier.verify(sign(private, second))


def test_signed_unknown_outcome_closes_reservation_and_blocks_retry(tmp_path):
    verifier, private, fields = fixture(tmp_path)
    uncertain = dict(fields, outcome_status="OUTCOME_UNKNOWN")
    with pytest.raises(ValueError, match="automatic retry forbidden"):
        verifier.verify(sign(private, uncertain))
    retry = dict(fields, attestation_id="att-retry", invocation_id="inv-retry")
    with pytest.raises(ValueError, match="reservation"):
        verifier.verify(sign(private, retry))
