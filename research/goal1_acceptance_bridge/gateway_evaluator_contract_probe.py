"""Exact #90 gateway -> exact #87 evaluator signed-terminal incompatibility probe.

Synthetic endpoint, backend and disposable signer; NO real model, gateway,
authenticated server, production config or hidden evaluator truth. A gateway
signature cannot be rewritten into another verifier's signed schema.
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
import sqlite3
import tempfile
import sys

GATEWAY_SOURCE_SHA256 = "27f6f7832d4ea5f2da0f8616fe4f475d6953861910bd2f0e1328d22d35d970ce"
CLAIM_SOURCE_SHA256 = "eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc"
VERIFIER_SOURCE_SHA256 = "fbf4c1e80747bea8a5191ddddb88299be6b3a6684b967a70de600571fe9e5df5"


def load_source(path: Path, expected: str) -> dict:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("source bytes changed: " + path.name)
    return runpy.run_path(str(path))


def sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def run(source_root: Path) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    gateway = load_source(
        source_root / "research/goal1_gateway/sole_route.py", GATEWAY_SOURCE_SHA256)
    claim = load_source(
        source_root / "research/goal1_evaluator/reservation_status_contract.py",
        CLAIM_SOURCE_SHA256)
    verifier_module = load_source(
        source_root / "research/goal1_evaluator/dispatch_attestation.py",
        VERIFIER_SOURCE_SHA256)
    key = Ed25519PrivateKey.generate()  # explicitly NOT independent signer custody
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    class TestSigner:
        key_id = "SYNTHETIC_SAME_PROCESS_SIGNER"
        def sign(self, message: bytes) -> bytes:
            return key.sign(message)

    class TestEndpoint:
        calls = 0
        def claim_reservation(self, *, reservation, gateway_id, invocation_id):
            self.calls += 1
            return {**reservation, "gateway_id": gateway_id,
                    "invocation_id": invocation_id, "status": "CLAIMED",
                    "claim_id": "synthetic-claim-" + invocation_id}

    class TestBackend:
        calls = 0
        fail = False
        def generate(self, prompt, *, model, max_tokens):
            self.calls += 1
            if self.fail:
                raise TimeoutError("synthetic ambiguous backend")
            return gateway["ModelObservation"](
                text="OK", model=model,
                prompt_tokens=3, output_tokens=2, backend_wall_ms=17)

    results = []
    for outcome in ("COMPLETED", "OUTCOME_UNKNOWN"):
        with tempfile.TemporaryDirectory(prefix="goal1-gateway-evaluator-seam-") as work:
            work = Path(work)
            verb = "ok" if outcome == "COMPLETED" else "ambiguous"
            prompt = "synthetic prompt " + verb
            fields = {
                "reservation_id": "res-" + verb, "run_id": "run-" + verb,
                "arm": "FROZEN", "challenge_id": "case-" + verb,
                "challenge_view_digest": sha("public features " + verb),
                "model_prompt_sha256": sha(prompt),
                "model_identity": "qwen3:4b-instruct",
                "model_artifact_sha256": sha("PLACEHOLDER ARTIFACT NOT WEIGHTS"),
            }
            verifier = verifier_module["Ed25519DispatchEvidenceVerifier"](
                trusted_public_key=public,
                trusted_gateway_id="synthetic-gateway",
                replay_db=str(work / "evaluator.sqlite"),
                expected_model_identity=fields["model_identity"],
                expected_model_artifact_sha256=fields["model_artifact_sha256"],
            )
            verifier.reserve_invocation(
                reservation_id=fields["reservation_id"],
                run_id=fields["run_id"], arm=fields["arm"],
                challenge_id=fields["challenge_id"],
                challenge_view_digest=fields["challenge_view_digest"],
                model_prompt_sha256=fields["model_prompt_sha256"],
                expected_model_identity=fields["model_identity"],
                expected_model_artifact_sha256=fields["model_artifact_sha256"],
            )
            endpoint = TestEndpoint()
            backend = TestBackend()
            backend.fail = outcome == "OUTCOME_UNKNOWN"
            store = gateway["GatewayAttemptStore"](work / "gateway.sqlite")
            dispatch = gateway["GatewayDispatch"](
                store=store, gateway_id="synthetic-gateway",
                endpoint_client=endpoint,
                claim_authorization=claim["claim_dispatch_authorization"],
                backend=backend, signer=TestSigner(),
            )
            if outcome == "COMPLETED":
                payload, signature = dispatch.execute(
                    reservation=fields, invocation_id="inv-" + verb,
                    prompt=prompt, max_tokens=8,
                )
            else:
                try:
                    dispatch.execute(
                        reservation=fields, invocation_id="inv-" + verb,
                        prompt=prompt, max_tokens=8,
                    )
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("ambiguous simulated model treated as success")
                row = store.history()[0]
                if row["status"] != "OUTCOME_UNKNOWN":
                    raise AssertionError("signed unknown not persisted")
                payload = json.loads(row["terminal_json"])
                signature = bytes.fromhex(row["signature_hex"])
            if not gateway["verify_terminal"](
                payload, signature,
                pinned_public_key=public,
                expected_key_id=TestSigner.key_id,
            ):
                raise AssertionError("gateway self-verification failed")
            raw_evidence = {**payload, "signature": base64.b64encode(signature).decode()}
            required = verifier_module["_REQUIRED"]
            missing = sorted(required - frozenset(raw_evidence))
            extra = sorted(frozenset(raw_evidence) - required)
            if not missing or not extra:
                raise AssertionError("expected cross-owner signed schema mismatch vanished")
            try:
                verifier.verify(raw_evidence)
            except ValueError as exc:
                rejection = type(exc).__name__
            else:
                raise AssertionError("evaluator accepted incompatible gateway terminal")
            if endpoint.calls != 1 or backend.calls != 1:
                raise AssertionError("synthetic execution did not exercise claim->backend")
            if payload.get("claim_id") != "synthetic-claim-inv-" + verb:
                raise AssertionError("gateway did not bind local claim identity")
            results.append({
                "gateway_status": payload["status"],
                "gateway_signed_terminal_verified_with_ephemeral_test_key": True,
                "malaphor_evaluator_directly_accepted_terminal": False,
                "evaluator_rejection": rejection,
                "missing_evaluator_fields": missing,
                "gateway_only_fields": extra,
                "synthetic_endpoint_claims": endpoint.calls,
                "synthetic_backend_attempts": backend.calls,
                "real_model_attempts": 0,
                "independent_attestation": False,
                "learning_qualified": False,
            })
            # Explicitly release SQLite-backed verifier before Windows cleanup.
            del verifier, endpoint, backend, store, dispatch, raw_evidence
            gc.collect()
    return {
        "schema": "GOAL1_GATEWAY_EVALUATOR_CONTRACT_INTEROP_V1",
        "integration_pr90_source_sha256": GATEWAY_SOURCE_SHA256,
        "malaphor_pr87_claim_source_sha256": CLAIM_SOURCE_SHA256,
        "malaphor_pr87_verifier_source_sha256": VERIFIER_SOURCE_SHA256,
        "test_key_custody": "SAME_PROCESS_EPHEMERAL_NOT_INDEPENDENT",
        "terminal_cases": results,
        "verdict": "BLOCKED_DIFFERENT_SIGNED_TERMINAL_SCHEMAS",
    }


def compatibility_exit_code(report: dict, *, require_compatible: bool) -> int:
    """Diagnostic output and strict source-schema result are separate.

    A green strict result, after a future reviewed source update, would only
    mean the frozen source schemas directly interoperate in this synthetic
    test. It would NOT establish independent signer custody, authenticated
    endpoint/claim, restricted model route, or actual learning.
    """
    if not require_compatible:
        return 0
    if type(report) is not dict or report.get("verdict") != "SOURCE_SCHEMA_DIRECTLY_COMPATIBLE":
        return 2
    if report.get("test_key_custody") not in (None, "SAME_PROCESS_EPHEMERAL_NOT_INDEPENDENT"):
        return 2
    cases = report.get("terminal_cases")
    if type(cases) is not list or len(cases) != 2:
        return 2
    if {case.get("gateway_status") for case in cases if type(case) is dict} != {
        "COMPLETED", "OUTCOME_UNKNOWN",
    }:
        return 2
    if any(
        type(case) is not dict
        or case.get("malaphor_evaluator_directly_accepted_terminal") is not True
        or case.get("independent_attestation", False) is not False
        or case.get("learning_qualified", False) is not False
        for case in cases
    ):
        return 2
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--require-compatible", action="store_true",
                   help="exit 2 while exact signed terminal formats do not interoperate")
    args = p.parse_args()
    report = run(args.source_root)
    print(json.dumps(report, sort_keys=True))
    outcome = compatibility_exit_code(report, require_compatible=args.require_compatible)
    if outcome:
        print("GOAL1_TERMINAL_SCHEMA_GATE=BLOCKED_INCOMPATIBLE", file=sys.stderr)
    raise SystemExit(outcome)
