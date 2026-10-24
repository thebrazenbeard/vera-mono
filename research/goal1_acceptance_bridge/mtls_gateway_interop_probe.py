"""Exact PR #91 TLS -> PR #87 claim -> PR #90 gateway acceptance probe.

Runs disposable localhost mTLS test endpoint, inert backend and disposable
signer. No production services, raw model, independently held private truth,
gateway access policy or protected credentials are created or changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import tempfile

SOURCE = {
    "research/goal1_gateway/authenticated_claim_client.py":
        "1e89362990e250d197f71845f95d997f66b2384743db4ce2f8005ac1d565336a",
    "tests/research/test_goal1_authenticated_claim_client.py":
        "5351df5c2b72b654c174f6166417b7b1f0f6526bd2a987d904aad285f812cc32",
    "research/goal1_gateway/sole_route.py":
        "27f6f7832d4ea5f2da0f8616fe4f475d6953861910bd2f0e1328d22d35d970ce",
    "research/goal1_evaluator/reservation_status_contract.py":
        "eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc",
    "research/goal1_evaluator/dispatch_attestation.py":
        "fbf4c1e80747bea8a5191ddddb88299be6b3a6684b967a70de600571fe9e5df5",
}


def load(root: Path, name: str) -> dict:
    p = root / name
    if hashlib.sha256(p.read_bytes()).hexdigest() != SOURCE[name]:
        raise ValueError("immutable source pin mismatch: " + name)
    return runpy.run_path(str(p))


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def run(root: Path) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    load(root, "research/goal1_gateway/authenticated_claim_client.py")
    fixture_module = load(root, "tests/research/test_goal1_authenticated_claim_client.py")
    gateway = load(root, "research/goal1_gateway/sole_route.py")
    evaluator = load(root, "research/goal1_evaluator/reservation_status_contract.py")
    verifier_module = load(root, "research/goal1_evaluator/dispatch_attestation.py")
    Fixture = fixture_module["AuthenticatedClaimClientTests"]
    scenarios = ("COMPLETED", "BAD_JSON_BEFORE_REMOTE_CLAIM",
                 "REMOTE_CLAIMED_RESPONSE_LOST",
                 "REMOTE_CLAIMED_CHANGED_RUN", "BACKEND_OUTCOME_UNKNOWN")
    results = []

    for scenario in scenarios:
        fixture = Fixture(methodName="test_real_mutual_tls_claim_and_one_use_remote_replay")
        fixture.setUp()
        try:
            with tempfile.TemporaryDirectory(prefix="goal1-mtls-gateway-interop-") as work:
                rootwork = Path(work)
                signer_key = Ed25519PrivateKey.generate()
                pub = signer_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

                class EphemeralSigner:
                    key_id = "EPHEMERAL_SAME_PROCESS"
                    def sign(self, message):
                        return signer_key.sign(message)

                class InertBackend:
                    calls = 0
                    def generate(self, prompt, *, model, max_tokens):
                        self.calls += 1
                        if scenario == "BACKEND_OUTCOME_UNKNOWN":
                            raise TimeoutError("synthetic backend unavailable")
                        return gateway["ModelObservation"](
                            text="OK", model=model,
                            prompt_tokens=3, output_tokens=2, backend_wall_ms=4,
                        )

                if scenario == "BAD_JSON_BEFORE_REMOTE_CLAIM":
                    fixture.server.reply_mode = "badjson"
                elif scenario == "REMOTE_CLAIMED_CHANGED_RUN":
                    fixture.server.reply_mode = "mismatch"
                endpoint = fixture.client()
                if scenario == "REMOTE_CLAIMED_RESPONSE_LOST":
                    # Real mTLS remote commit, synthetic response-loss injection.
                    # This does not claim actual physical packet loss.
                    original_endpoint = endpoint
                    class LostResponseAfterRemoteClaim:
                        def claim_reservation(self, *, reservation, gateway_id, invocation_id):
                            original_endpoint.claim_reservation(
                                reservation=reservation, gateway_id=gateway_id,
                                invocation_id=invocation_id)
                            raise TimeoutError("synthetic loss after real mTLS claim")
                    endpoint = LostResponseAfterRemoteClaim()
                backend = InertBackend()
                store = gateway["GatewayAttemptStore"](rootwork / "gateway.sqlite")
                dispatcher = gateway["GatewayDispatch"](
                    store=store, gateway_id="test-gateway",
                    endpoint_client=endpoint,
                    claim_authorization=evaluator["claim_dispatch_authorization"],
                    backend=backend, signer=EphemeralSigner(),
                )
                model_name = "synthetic-model"
                prompt = "synthetic mTLS claim to fake backend: " + scenario
                request = {
                    "reservation_id": "res-" + scenario.lower().replace("_", "-"),
                    "run_id": "run-" + scenario.lower().replace("_", "-"),
                    "arm": "FROZEN",
                    "challenge_id": "case-" + scenario.lower().replace("_", "-"),
                    "challenge_view_digest": sha("public view " + scenario),
                    "model_prompt_sha256": sha(prompt),
                    "model_identity": model_name,
                    "model_artifact_sha256": sha("PLACEHOLDER NOT MODEL WEIGHTS"),
                }
                invocation = "inv-" + scenario.lower().replace("_", "-")
                terminal = None
                try:
                    terminal, signature = dispatcher.execute(
                        reservation=request, invocation_id=invocation,
                        prompt=prompt, max_tokens=8)
                except Exception as exc:
                    if scenario == "COMPLETED":
                        raise
                    if scenario in ("BAD_JSON_BEFORE_REMOTE_CLAIM", "REMOTE_CLAIMED_RESPONSE_LOST", "REMOTE_CLAIMED_CHANGED_RUN"):
                        if backend.calls != 0:
                            raise AssertionError("backend dispatched after invalid claim") from exc
                    elif not isinstance(exc, TimeoutError):
                        raise AssertionError("unexpected backend unknown classification") from exc
                else:
                    if scenario != "COMPLETED":
                        raise AssertionError("failed scenario was accepted")
                # A fresh SQLite connection confirms the correct local fence.
                row = gateway["GatewayAttemptStore"](store.path).history()
                if len(row) != 1:
                    raise AssertionError("missing durable gateway attempt")
                local = row[0]
                if fixture.server.received != 1:
                    raise AssertionError("expected exactly one real mTLS HTTP request")
                remote_claim_expected = scenario != "BAD_JSON_BEFORE_REMOTE_CLAIM"
                if bool(fixture.server.claimed) != remote_claim_expected:
                    raise AssertionError("synthetic remote claim marker mismatched scenario")
                if scenario == "COMPLETED":
                    if backend.calls != 1 or local["status"] != "COMPLETED":
                        raise AssertionError("valid mTLS path did not dispatch")
                    if not gateway["verify_terminal"](
                        terminal, signature, pinned_public_key=pub,
                        expected_key_id=EphemeralSigner.key_id,
                    ):
                        raise AssertionError("synthetic terminal signature mismatch")
                elif scenario == "BACKEND_OUTCOME_UNKNOWN":
                    if local["status"] != "OUTCOME_UNKNOWN" or backend.calls != 1:
                        raise AssertionError("unknown did not fail closed")
                    terminal = json.loads(local["terminal_json"])
                    signature = bytes.fromhex(local["signature_hex"])
                    if not gateway["verify_terminal"](
                        terminal, signature, pinned_public_key=pub,
                        expected_key_id=EphemeralSigner.key_id,
                    ):
                        raise AssertionError("unknown synthetic terminal signature invalid")
                    if terminal["response_sha256"] is not None:
                        raise AssertionError("unknown response hash invented")
                else:
                    if local["status"] != "RESERVED" or local["claim_id"] is not None:
                        raise AssertionError("ambiguous remote claim was locally promoted")
                    if backend.calls:
                        raise AssertionError("local model call without verified claim")
                # A new invocation on the same exact run, arm and challenge must
                # be rejected before any second network request or model call.
                before = fixture.server.received
                try:
                    dispatcher.execute(reservation={
                        **request, "reservation_id": request["reservation_id"] + "-fresh",
                    }, invocation_id=invocation + "-fresh", prompt=prompt, max_tokens=8)
                except gateway["GatewayHold"]:
                    pass
                else:
                    raise AssertionError("new reservation reused same run-arm-case")
                if fixture.server.received != before:
                    raise AssertionError("duplicate attempt sent another remote claim")
                results.append({
                    "scenario": scenario,
                    "synthetic_mtls_requests": fixture.server.received,
                    "synthetic_endpoint_claimed": bool(fixture.server.claimed),
                    "fake_backend_calls": backend.calls,
                    "local_status": local["status"],
                    "local_claim_id_present": local["claim_id"] is not None,
                    "replay_denied_before_network": True,
                    "independent_endpoint_custody": False,
                    "actual_model_invoked": False,
                    "independent_dispatch_qualified": False,
                })
        finally:
            fixture.doCleanups()
    return {
        "schema": "GOAL1_EXACT_MTLS_CLAIM_GATEWAY_INTEROP_V1",
        "source_sha256": SOURCE,
        "scenarios": results,
        "classification": "SOURCE_AND_SAME_PROCESS_MTLS_MECHANICS_ONLY",
        "goal1_qualified": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().source_root), sort_keys=True))
