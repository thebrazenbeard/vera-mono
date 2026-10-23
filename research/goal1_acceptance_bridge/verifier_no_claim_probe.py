"""Reproducible negative control: a valid signature alone is not inference.

Loads Malaphor's exact pinned source from an explicit local path, creates a
disposable SAME-PROCESS signer, reserves without endpoint claim or model,
and demonstrates that cryptographic verification alone can succeed.

NOT a claim of a verifier implementation vulnerability: when actual keys
are independently controlled this forged-signing access should be impossible.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import closing
import gc
import hashlib
import json
from pathlib import Path
import runpy
import tempfile

PINNED_VERIFIER_SHA256 = "fbf4c1e80747bea8a5191ddddb88299be6b3a6684b967a70de600571fe9e5df5"


def run(path: Path) -> dict:
    source_bytes = path.read_bytes()
    actual = hashlib.sha256(source_bytes).hexdigest()
    if actual != PINNED_VERIFIER_SHA256:
        raise ValueError("evaluator source changed; review a new exact evidence cut")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    source = runpy.run_path(str(path))
    Verifier = source["Ed25519DispatchEvidenceVerifier"]
    canonical = source["canonical_attestation_bytes"]
    digest = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()
    ephemeral = Ed25519PrivateKey.generate()
    with tempfile.TemporaryDirectory(prefix="goal1-unsigned-claim-control-") as tmp:
        verifier = Verifier(
            trusted_public_key=ephemeral.public_key().public_bytes(
                Encoding.Raw, PublicFormat.Raw,
            ),
            trusted_gateway_id="EPHEMERAL_TEST_SIGNER",
            replay_db=str(Path(tmp) / "verifier.sqlite"),
            expected_model_identity="test-only-model",
            expected_model_artifact_sha256="a" * 64,
        )
        verifier.reserve_invocation(
            reservation_id="reservation-no-endpoint-claim",
            run_id="synthetic-run", arm="FROZEN", challenge_id="test-challenge",
            challenge_view_digest=digest("public test challenge"),
            model_prompt_sha256=digest("test prompt"),
            expected_model_identity="test-only-model",
            expected_model_artifact_sha256="a" * 64,
        )
        # Deliberately do not call claim_dispatch_authorization, do not
        # create an authenticated endpoint, and do not invoke any model.
        terminal = {
            "witness_kind": "independent_dispatch_gateway",
            "gateway_id": "EPHEMERAL_TEST_SIGNER",
            "attestation_id": "synthetic-attestation",
            "invocation_id": "synthetic-invocation",
            "reservation_id": "reservation-no-endpoint-claim",
            "run_id": "synthetic-run", "arm": "FROZEN",
            "challenge_id": "test-challenge",
            "challenge_view_digest": digest("public test challenge"),
            "model_prompt_sha256": digest("test prompt"),
            "model_response_sha256": digest("never computed by a model"),
            "model_identity": "test-only-model",
            "model_artifact_sha256": "a" * 64,
            "dispatch_monotonic_ns": 100,
            "response_monotonic_ns": 200,
            "outcome_status": "COMPLETED",
            "resource_usage": {
                "input_tokens": 1, "output_tokens": 1, "wall_time_ms": 1,
            },
        }
        terminal["signature"] = base64.b64encode(
            ephemeral.sign(canonical(terminal))
        ).decode("ascii")
        accepted = verifier.verify(terminal)
        if accepted is not True:
            raise AssertionError("unexpected verifier result")
        del verifier, terminal
        gc.collect()  # release verifier SQLite references on Windows
    return {
        "schema": "GOAL1_VERIFIER_NO_CLAIM_NEGATIVE_CONTROL_V1",
        "source_sha256": actual,
        "verifier_accepted_self_signed_control": bool(accepted),
        "authenticated_endpoint_claim_occurred": False,
        "actual_model_dispatch_occurred": False,
        "signer_custody": "SAME_PROCESS_EPHEMERAL_TEST_ONLY",
        "independent_attestation": False,
        "learning_qualified": False,
        "classification": "CRYPTOGRAPHIC_VALIDATION_ALONE_NOT_EXECUTION_PROOF",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verifier-source", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().verifier_source), sort_keys=True))
