"""Pinned PR95 gateway persisted original bytes -> PR87 V2 verifier.

Source-only disposable test: synthetic same-process claim authority, fake model,
ephemeral Ed25519 signer. Positive source interoperability NEVER proves custody,
selected runtime, real model inference, independent resource truth or learning.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import runpy
import sqlite3
import tempfile
from types import SimpleNamespace

GATEWAY_SHA256 = "ba20f64cf92dc6e58f4c82cecbe85963a6895ab97d5a3d4abfa961708945558d"
V2_SHA256 = "153aed3f37e013f9fbb213af2539a1984bebf3086a1d77544d189e0c8104d187"
CLAIM_SHA256 = "eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def freeze(path: Path, pinned: str) -> dict:
    content = path.read_bytes()
    if digest(content) != pinned:
        raise ValueError(f"source changed; exact pin failed: {path.name}")
    return runpy.run_path(str(path))


def compatibility_gate(report: dict, *, require_source: bool, require_independent: bool) -> int:
    """Three exact-source cases can pass; no local report can prove independence."""
    if require_independent:
        return 2
    if not require_source:
        return 0
    if type(report) is not dict or report.get("classification") != "SOURCE_INTEROP_ONLY":
        return 2
    if report.get("independent_claim_custody") is not False:
        return 2
    cases = report.get("cases")
    if type(cases) is not list or len(cases) != 3:
        return 2
    expected = {"COMPLETED_0MS", "COMPLETED_1MS", "OUTCOME_UNKNOWN"}
    if {c.get("case") for c in cases if type(c) is dict} != expected:
        return 2
    if any(type(c) is not dict
           or c.get("original_signed_bytes_read_back") is not True
           or c.get("exact_v2_accepted") is not True
           or c.get("claim_substitution_rejected") is not True
           or c.get("wire_tamper_rejected") is not True
           or c.get("local_metadata_tamper_rejected") is not True
           or c.get("qualified") is not False for c in cases):
        return 2
    return 0


def run(root: Path) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    gw = freeze(root / "research/goal1_gateway/sole_route.py", GATEWAY_SHA256)
    v2 = freeze(root / "research/goal1_evaluator/terminal_v2.py", V2_SHA256)
    c = freeze(root / "research/goal1_evaluator/reservation_status_contract.py", CLAIM_SHA256)
    cases = []
    for label, runtime_ns in (
        ("COMPLETED_0MS", 654321),
        ("COMPLETED_1MS", 1654321),
        ("OUTCOME_UNKNOWN", 456789),
    ):
        with tempfile.TemporaryDirectory(prefix="goal1-v2-real-readback-") as td:
            key = Ed25519PrivateKey.generate()
            pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
            class Signer:
                key_id = "EPHEMERAL_ONLY"
                signed = None
                def sign(self, message):
                    self.signed = message
                    return key.sign(message)
            class Endpoint:
                count = 0
                def claim_reservation(self, *, reservation, gateway_id, invocation_id):
                    self.count += 1
                    return {**reservation, "gateway_id":gateway_id,
                            "invocation_id":invocation_id,
                            "status":"CLAIMED", "claim_id":"test-claim-"+invocation_id}
            class Backend:
                count = 0
                def generate(self, prompt, *, model, max_tokens):
                    self.count += 1
                    if label == "OUTCOME_UNKNOWN":
                        raise TimeoutError("inert timeout")
                    return gw["ModelObservation"](
                        text="A", model=model, prompt_tokens=2,
                        output_tokens=1, backend_wall_ms=runtime_ns//1_000_000)
            class FakeClaimAuthority:
                mutate = False
                count = 0
                def verify_claim_evidence(self, *, expected_binding):
                    self.count += 1
                    row = {**expected_binding, "status":"CLAIMED"}
                    if self.mutate:
                        row["claim_id"] = "NOT-EVALUATOR-ISSUED"
                    return row
            signer, endpoint, backend = Signer(), Endpoint(), Backend()
            prompt = "synthetic only " + label
            suff = label.lower().replace("_","-")
            reservation = {
                "reservation_id":"res-"+suff,"run_id":"run-"+suff,
                "arm":"FROZEN","challenge_id":"case-"+suff,
                "challenge_view_digest":digest(("view-"+suff).encode()),
                "model_prompt_sha256":digest(prompt.encode()),
                "model_identity":"synthetic-model",
                "model_artifact_sha256":digest(b"not-real-weight-attestation"),
            }
            invocation = "inv-"+suff
            path = Path(td) / "gateway.sqlite"
            store = gw["GatewayAttemptStore"](path)
            dispatch = gw["GatewayDispatch"](
                store=store, gateway_id="synthetic-gateway",
                endpoint_client=endpoint,
                claim_authorization=c["claim_dispatch_authorization"],
                backend=backend,signer=signer)
            execute = gw["GatewayDispatch"].execute
            old = execute.__globals__["time"]
            observed = iter((0, runtime_ns))
            execute.__globals__["time"] = SimpleNamespace(monotonic_ns=lambda: next(observed))
            try:
                if label == "OUTCOME_UNKNOWN":
                    try:
                        dispatch.execute(reservation=reservation,
                                         invocation_id=invocation,prompt=prompt,max_tokens=8)
                    except TimeoutError:
                        pass
                    else:
                        raise AssertionError("unknown did not raise")
                else:
                    _, signature = dispatch.execute(reservation=reservation,
                                                      invocation_id=invocation,prompt=prompt,max_tokens=8)
            finally:
                execute.__globals__["time"] = old
            if endpoint.count!=1 or backend.count!=1:
                raise AssertionError("expected one synthetic claim and backend")
            # Fresh store instance, not caller-returned payload.
            restored = gw["GatewayAttemptStore"](path)
            preserved = restored.signed_terminal(invocation)
            if preserved.payload_bytes != signer.signed:
                raise AssertionError("readback did not preserve signer-input bytes")
            if preserved.payload_sha256 != digest(preserved.payload_bytes):
                raise AssertionError("signed terminal readback digest incorrect")
            if preserved.qualified or preserved.independent_claim_verified:
                raise AssertionError("gateway has promoted local evidence")
            payload = json.loads(preserved.payload_bytes)
            expected_status = ("OUTCOME_UNKNOWN" if label=="OUTCOME_UNKNOWN" else "COMPLETED")
            if preserved.status != expected_status or payload["status"] != expected_status:
                raise AssertionError("terminal status wrong")
            if label=="COMPLETED_0MS" and payload["gateway_wall_ms"]!=0:
                raise AssertionError("0ms was rounded or invented")
            if label=="COMPLETED_1MS" and payload["gateway_wall_ms"]!=1:
                raise AssertionError("1ms floor value not preserved")
            if label=="OUTCOME_UNKNOWN" and (
                payload["response_sha256"] is not None or any(
                payload[k] is not None for k in (
                    "prompt_tokens","output_tokens","backend_wall_ms","gateway_wall_ms"))):
                raise AssertionError("unknown response/usage invented")
            authority=FakeClaimAuthority()
            args = dict(
                payload_bytes=preserved.payload_bytes,signature=preserved.signature,
                pinned_gateway_public_key=pub,expected_gateway_id="synthetic-gateway",
                expected_key_id=signer.key_id,
                expected_binding={k:payload[k] for k in v2["_BINDING_FIELDS"]},
                claim_evidence_verifier=authority)
            outcome=v2["verify_terminal_v2"](**args)
            if outcome["qualified"] is not False:
                raise AssertionError("source test was qualified")
            if outcome["status"] != ("VERIFIED_"+expected_status):
                raise AssertionError("evaluator outcome mismatch")
            if outcome["score_eligible"] != (label!="OUTCOME_UNKNOWN"):
                raise AssertionError("unknown eligibility incorrect")
            authority.mutate=True
            try:
                v2["verify_terminal_v2"](**args)
            except ValueError:
                claim_substitution_rejected=True
            else:
                raise AssertionError("fake evaluator claim substitution accepted")
            authority.mutate=False
            try:
                v2["verify_terminal_v2"](**{**args, "payload_bytes":preserved.payload_bytes+b" "})
            except ValueError:
                wire_tamper_rejected=True
            else:
                raise AssertionError("tampered signed bytes accepted")
            # Same-user SQLite mutation: the gateway must refuse inconsistent
            # local metadata, *not* claim that this establishes independent custody.
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE attempts SET run_id=? WHERE invocation_id=?",
                           ("attacker-replaced-run",invocation))
            try:
                gw["GatewayAttemptStore"](path).signed_terminal(invocation)
            except gw["GatewayHold"]:
                local_metadata_tamper_rejected=True
            else:
                raise AssertionError("local metadata tamper accepted")
            cases.append({
                "case":label,"status":outcome["status"],
                "gateway_wall_ms":payload["gateway_wall_ms"],
                "original_signed_bytes_read_back":True,
                "exact_v2_accepted":True,
                "claim_substitution_rejected":claim_substitution_rejected,
                "wire_tamper_rejected":wire_tamper_rejected,
                "local_metadata_tamper_rejected":local_metadata_tamper_rejected,
                "qualified":False,
                "actual_model_inference":False,
                "independent_claim_custody":False,
            })
    return {
        "schema":"GOAL1_PR95_PR87_CROSS_OWNER_CUSTODY_SEAM_V1",
        "classification":"SOURCE_INTEROP_ONLY",
        "source_pins_sha256":{"integration_pr95":GATEWAY_SHA256,
                              "malaphor_pr87":V2_SHA256,"claim_contract":CLAIM_SHA256},
        "cases":cases,"independent_claim_custody":False,
        "selected_learner_sole_route":False,"private_holdout":False,
        "learning_qualified":False,
    }


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--require-source",action="store_true")
    p.add_argument("--require-independent",action="store_true")
    opts=p.parse_args()
    report=run(opts.source_root)
    print(json.dumps(report,sort_keys=True))
    raise SystemExit(compatibility_gate(
        report,require_source=opts.require_source,
        require_independent=opts.require_independent))
