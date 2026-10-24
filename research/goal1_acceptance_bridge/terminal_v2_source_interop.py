"""Exact PR #90 terminal -> Malaphor PR #87 V2 cross-owner source probe.

Pure research with disposable same-process keys, synthetic claim authority and
inert backend. Never authenticates independent custody, runtime route, weights,
resource usage, private truth or learning. Freeze immutable owner source hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import time

GATEWAY_SHA256 = "27f6f7832d4ea5f2da0f8616fe4f475d6953861910bd2f0e1328d22d35d970ce"
TERMINAL_V2_SHA256 = "cd6923597ada9bcfc07011fab43fbb75d8967f975590313e069cefa7e8ba81dc"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def freeze(path: Path, expected: str) -> dict:
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError("owner source bytes changed: " + str(path))
    return runpy.run_path(str(path))


def source_compatibility_exit_code(report: dict, *, require_compatible: bool) -> int:
    """Compatibility is not independent-transport/learning qualification."""
    if not require_compatible:
        return 0
    if type(report) is not dict or report.get("verdict") != "V2_SOURCE_COMPATIBLE_ONLY":
        return 2
    # Positive samples interoperate, but strict compatibility remains HOLD
    # while #90's signed zero-ms completion is rejected by Malaphor V2.
    if report.get("zero_ms_contract_boundary", {}).get("malaphor_v2_rejected_zero_ms") is True:
        return 2
    cases = report.get("cases")
    if type(cases) is not list or len(cases) != 2:
        return 2
    if {c.get("gateway_status") for c in cases if type(c) is dict} != {"COMPLETED", "OUTCOME_UNKNOWN"}:
        return 2
    if any(type(c) is not dict
           or c.get("signature_covers_exact_gateway_bytes") is not True
           or c.get("malaphor_v2_accepted") is not True
           or c.get("wrong_claim_rejected") is not True
           or c.get("tampered_bytes_rejected") is not True
           or c.get("independent_custody") is not False
           or c.get("learning_qualified") is not False
           for c in cases):
        return 2
    return 0



def zero_wall_source_negative(gateway: dict, evaluator: dict) -> dict:
    """Force gateway's actual monotonic difference to zero for a deterministic edge.

    Only the loaded isolated gateway function's time dependency is replaced.
    This is an injected boundary condition, NOT an observation about real
    Ollama latency or a proposed fix to either independently owned source.
    """
    from types import SimpleNamespace
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    class Signer:
        key_id = "SYNTHETIC_ZERO_MS"
        message = None
        def sign(self, message):
            self.message = message
            return key.sign(message)
    class Client:
        def claim_reservation(self, *, reservation, gateway_id, invocation_id):
            return {**reservation, "gateway_id":gateway_id, "invocation_id":invocation_id,
                    "status":"CLAIMED", "claim_id":"synthetic-zero-claim"}
    class Backend:
        def generate(self, prompt, *, model, max_tokens):
            return gateway["ModelObservation"](
                text="Z", model=model, prompt_tokens=1, output_tokens=1, backend_wall_ms=0)
    class LocalClaimVerifier:
        def verify_claim_evidence(self, *, expected_binding):
            return {**expected_binding, "status":"CLAIMED"}
    def claim(client, *, reservation, gateway_id, invocation_id):
        return client.claim_reservation(reservation=reservation, gateway_id=gateway_id,
                                        invocation_id=invocation_id)
    prompt = "Synthetic zero-millisecond boundary"
    reservation = {
        "reservation_id":"res-zero", "run_id":"run-zero", "arm":"FROZEN",
        "challenge_id":"case-zero", "challenge_view_digest":sha(b"view-zero"),
        "model_prompt_sha256":sha(prompt.encode()), "model_identity":"test-only-model",
        "model_artifact_sha256":sha(b"placeholder-not-real-weights"),
    }
    with tempfile.TemporaryDirectory(prefix="goal1-terminal-v2-zero-wall-") as scratch:
        signer = Signer()
        dispatch = gateway["GatewayDispatch"](
            store=gateway["GatewayAttemptStore"](Path(scratch)/"gateway.sqlite"),
            gateway_id="synthetic-gateway", endpoint_client=Client(),
            claim_authorization=claim, backend=Backend(), signer=signer)
        execute = gateway["GatewayDispatch"].execute
        original_time = execute.__globals__["time"]
        execute.__globals__["time"] = SimpleNamespace(monotonic_ns=lambda: 1000)
        try:
            payload, signature = dispatch.execute(
                reservation=reservation, invocation_id="inv-zero", prompt=prompt,
                max_tokens=8)
        finally:
            execute.__globals__["time"] = original_time
        if payload["gateway_wall_ms"] != 0:
            raise AssertionError("gateway no longer produces exact zero wall duration")
        wire = signer.message
        if wire is None or json.loads(wire) != payload:
            raise AssertionError("gateway did not sign the zero-ms terminal bytes")
        binding = {k:payload[k] for k in evaluator["_BINDING_FIELDS"]}
        try:
            evaluator["verify_terminal_v2"](
                payload_bytes=wire, signature=signature,
                pinned_gateway_public_key=public,
                expected_gateway_id="synthetic-gateway",
                expected_key_id=signer.key_id, expected_binding=binding,
                claim_evidence_verifier=LocalClaimVerifier())
        except ValueError as exc:
            if "gateway wall time must be positive" not in str(exc):
                raise
            rejected = True
        else:
            rejected = False
        if not rejected:
            raise AssertionError("zero-ms boundary unexpectedly admitted")
        return {
            "gateway_signed_zero_ms_completion":True,
            "malaphor_v2_rejected_zero_ms":True,
            "source_owner_disposition":"REVIEW_REQUIRED",
            "independent_custody":False,
            "learning_qualified":False,
        }

def run(root: Path) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    gateway = freeze(root / "research/goal1_gateway/sole_route.py", GATEWAY_SHA256)
    evaluator = freeze(root / "research/goal1_evaluator/terminal_v2.py", TERMINAL_V2_SHA256)
    results = []

    for status in ("COMPLETED", "OUTCOME_UNKNOWN"):
        with tempfile.TemporaryDirectory(prefix="goal1-terminal-v2-exact-") as scratch:
            key = Ed25519PrivateKey.generate()
            public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

            class ObservedBytesSigner:
                key_id = "SYNTHETIC_KEY"
                signed_messages = []
                def sign(self, message):
                    if type(message) is not bytes:
                        raise AssertionError("gateway signer did not receive bytes")
                    self.signed_messages.append(message)
                    return key.sign(message)

            class FakeEndpoint:
                claims = 0
                def claim_reservation(self, *, reservation, gateway_id, invocation_id):
                    self.claims += 1
                    return {**reservation, "gateway_id":gateway_id, "invocation_id":invocation_id,
                            "status":"CLAIMED", "claim_id":"test-claim-" + invocation_id}

            class FakeBackend:
                calls = 0
                def generate(self, prompt, *, model, max_tokens):
                    self.calls += 1
                    if status == "OUTCOME_UNKNOWN":
                        raise TimeoutError("synthetic unknown backend outcome")
                    # Ensure this positive fixture genuinely takes >1 ms.
                    # A fast sub-ms backend exposes the separate observed
                    # PR90 floor-ms vs PR87-V2 positive-ms contract mismatch.
                    time.sleep(0.005)
                    return gateway["ModelObservation"](
                        text="A", model=model, prompt_tokens=5,
                        output_tokens=1, backend_wall_ms=4)

            class FakeIndependentClaimVerifier:
                checks = 0
                mismatch = False
                def verify_claim_evidence(self, *, expected_binding):
                    self.checks += 1
                    value = {**expected_binding, "status":"CLAIMED"}
                    if self.mismatch:
                        value["claim_id"] = "forged-claim"
                    return value

            def claim_endpoint(client, *, reservation, gateway_id, invocation_id):
                return client.claim_reservation(reservation=reservation,
                                                gateway_id=gateway_id, invocation_id=invocation_id)

            prompt = "Synthetic V2 compatibility " + status
            reservation = {
                "reservation_id":"res-" + status.lower().replace("_","-"),
                "run_id":"test-run-" + status.lower().replace("_","-"),
                "arm":"FROZEN", "challenge_id":"case-" + status.lower().replace("_","-"),
                "challenge_view_digest":sha(("view-" + status).encode()),
                "model_prompt_sha256":sha(prompt.encode()), "model_identity":"test-only-model",
                "model_artifact_sha256":sha(b"placeholder-not-real-weights"),
            }
            invocation = "inv-" + status.lower().replace("_","-")
            signer = ObservedBytesSigner()
            backend = FakeBackend()
            endpoint = FakeEndpoint()
            store = gateway["GatewayAttemptStore"](Path(scratch) / "gateway.sqlite")
            dispatch = gateway["GatewayDispatch"](
                store=store, gateway_id="synthetic-gateway", endpoint_client=endpoint,
                claim_authorization=claim_endpoint, backend=backend, signer=signer)
            if status == "COMPLETED":
                payload, signature = dispatch.execute(
                    reservation=reservation, invocation_id=invocation,
                    prompt=prompt, max_tokens=8)
            else:
                try:
                    dispatch.execute(reservation=reservation, invocation_id=invocation,
                                     prompt=prompt, max_tokens=8)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("backend timeout unexpectedly completed")
                payload = None
                signature = None
            rows = gateway["GatewayAttemptStore"](store.path).history()
            if len(rows) != 1 or rows[0]["status"] != status:
                raise AssertionError("durable local terminal state mismatch")
            if len(signer.signed_messages) != 1:
                raise AssertionError("gateway did not sign exactly once")
            payload_bytes = signer.signed_messages[0]  # exact bytes observed at signer
            if payload_bytes != rows[0]["terminal_json"].encode("utf-8"):
                raise AssertionError("persisted terminal bytes differ from signed input")
            signed_signature = bytes.fromhex(rows[0]["signature_hex"])
            if signature is not None and signature != signed_signature:
                raise AssertionError("returned signature changed")
            if json.loads(payload_bytes)["status"] != status:
                raise AssertionError("signed status mismatch")
            if endpoint.claims != 1 or backend.calls != 1:
                raise AssertionError("not one synthetic claim and backend")
            parsed = json.loads(payload_bytes)
            if parsed["claim_id"] != "test-claim-" + invocation:
                raise AssertionError("claim binding mismatch")
            binding = {k:parsed[k] for k in evaluator["_BINDING_FIELDS"]}
            claim_verifier = FakeIndependentClaimVerifier()
            args = dict(payload_bytes=payload_bytes,signature=signed_signature,
                        pinned_gateway_public_key=public,expected_gateway_id="synthetic-gateway",
                        expected_key_id=signer.key_id,expected_binding=binding,
                        claim_evidence_verifier=claim_verifier)
            verdict = evaluator["verify_terminal_v2"](**args)
            expected_state = ("VERIFIED_COMPLETED" if status == "COMPLETED"
                              else "VERIFIED_OUTCOME_UNKNOWN")
            if verdict["status"] != expected_state or verdict["qualified"] is not False:
                raise AssertionError("V2 return result unexpectedly promoted")
            if verdict["automatic_retry_permitted"] is not False or not verdict["reservation_consumed"]:
                raise AssertionError("terminal permitted replay")
            if status == "OUTCOME_UNKNOWN":
                if verdict["score_eligible"] or any(
                    parsed[k] is not None for k in (
                        "response_sha256","prompt_tokens","output_tokens",
                        "gateway_wall_ms","backend_wall_ms")):
                    raise AssertionError("unknown terminal invented data")
            elif verdict["score_eligible"] is not True:
                raise AssertionError("completed terminal rejected for downstream gate")
            claim_verifier.mismatch = True
            try:
                evaluator["verify_terminal_v2"](**args)
            except ValueError:
                wrong_claim_rejected = True
            else:
                raise AssertionError("fake independent claim mutation accepted")
            claim_verifier.mismatch = False
            try:
                evaluator["verify_terminal_v2"](**{**args,"payload_bytes":payload_bytes+b" "})
            except ValueError:
                tampered_bytes_rejected = True
            else:
                raise AssertionError("transformed signed bytes accepted")
            results.append({
                "gateway_status":status,
                "signature_covers_exact_gateway_bytes":True,
                "malaphor_v2_accepted":True,
                "v2_status":verdict["status"],
                "score_eligible":verdict["score_eligible"],
                "wrong_claim_rejected":wrong_claim_rejected,
                "tampered_bytes_rejected":tampered_bytes_rejected,
                "synthetic_claims":endpoint.claims,
                "synthetic_backend_calls":backend.calls,
                "independent_custody":False,
                "learning_qualified":False,
                "payload_sha256":sha(payload_bytes),
            })
    zero_wall = zero_wall_source_negative(gateway, evaluator)
    return {
        "schema":"GOAL1_TERMINAL_V2_ACTUAL_CROSS_OWNER_SOURCE_V1",
        "zero_ms_contract_boundary":zero_wall,
        "gateway_source_sha256":GATEWAY_SHA256,
        "evaluator_v2_source_sha256":TERMINAL_V2_SHA256,
        "verdict":"V2_SOURCE_COMPATIBLE_ONLY",
        "cases":results,
        "selected_qvr_route_verified":False,
        "independent_claim_evidence_verified":False,
        "sole_route_verified":False,
        "private_holdout_verified":False,
        "learning_qualified":False,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--require-compatible", action="store_true")
    args = p.parse_args()
    report = run(args.source_root)
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(source_compatibility_exit_code(report, require_compatible=args.require_compatible))
