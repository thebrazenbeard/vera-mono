"""Research-only cross-process terminal restart and verifier falsifier.

The emitter and reader are distinct OS processes, but both run under the
operator's test privilege domain. The public key, fake claim and receipt are
synthetic. Process separation NEVER proves independent issuer/key custody.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import tempfile

GATEWAY_SHA256 = "ba20f64cf92dc6e58f4c82cecbe85963a6895ab97d5a3d4abfa961708945558d"
V2_SHA256 = "153aed3f37e013f9fbb213af2539a1984bebf3086a1d77544d189e0c8104d187"
CLAIM_SHA256 = "eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc"


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def freeze(path: Path, expected: str) -> dict:
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError("pin mismatch for " + path.name)
    return runpy.run_path(str(path))


def frozen_source(root: Path) -> tuple[dict, dict, dict]:
    return (
        freeze(root/"research/goal1_gateway/sole_route.py", GATEWAY_SHA256),
        freeze(root/"research/goal1_evaluator/terminal_v2.py", V2_SHA256),
        freeze(root/"research/goal1_evaluator/reservation_status_contract.py", CLAIM_SHA256),
    )


def reservation(status: str) -> tuple[str,str,dict]:
    name = status.lower().replace("_","-")
    prompt = "research-only fake inference " + name
    invocation = "cold-inv-"+name
    record = {
        "reservation_id":"cold-res-"+name,
        "run_id":"cold-run-"+name,
        "arm":"FROZEN",
        "challenge_id":"cold-case-"+name,
        "challenge_view_digest":sha(("synthetic view "+name).encode()),
        "model_prompt_sha256":sha(prompt.encode()),
        "model_identity":"test-only-model",
        "model_artifact_sha256":sha(b"synthetic not real weight bytes"),
    }
    return invocation,prompt,record


def emit(root: Path, work: Path, status: str) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    gateway,_,claim_module = frozen_source(root)
    invocation,prompt,record=reservation(status)
    private=Ed25519PrivateKey.generate()
    public=private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    class Signer:
        key_id="ONE_PROCESS_TEST_SIGNER"
        signed=None
        def sign(self, message):
            self.signed=message
            return private.sign(message)
    class Endpoint:
        calls=0
        def claim_reservation(self, *, reservation, gateway_id, invocation_id):
            self.calls+=1
            return {**reservation,"gateway_id":gateway_id,
                    "invocation_id":invocation_id,"status":"CLAIMED",
                    "claim_id":"test-claim-"+invocation_id}
    class FakeBackend:
        calls=0
        def generate(self,prompt,*,model,max_tokens):
            self.calls+=1
            if status=="OUTCOME_UNKNOWN":
                raise TimeoutError("research-only artificial timeout")
            return gateway["ModelObservation"](
                text="Y",model=model,prompt_tokens=2,output_tokens=1,
                backend_wall_ms=0)
    signer,endpoint,backend=Signer(),Endpoint(),FakeBackend()
    db=work/"gateway.sqlite"
    dispatcher=gateway["GatewayDispatch"](
        store=gateway["GatewayAttemptStore"](db),gateway_id="research-gateway",
        endpoint_client=endpoint,
        claim_authorization=claim_module["claim_dispatch_authorization"],
        backend=backend,signer=signer)
    if status=="OUTCOME_UNKNOWN":
        try:
            dispatcher.execute(reservation=record,invocation_id=invocation,
                               prompt=prompt,max_tokens=8)
        except TimeoutError:
            pass
        else:
            raise AssertionError("synthetic timeout misclassified")
    else:
        dispatcher.execute(reservation=record,invocation_id=invocation,
                           prompt=prompt,max_tokens=8)
    if endpoint.calls!=1 or backend.calls!=1:
        raise AssertionError("claim->backend dispatch count mismatch")
    signed=gateway["GatewayAttemptStore"](db).signed_terminal(invocation)
    if signed.payload_bytes!=signer.signed:
        raise AssertionError("emitter did not persist original signing bytes")
    (work/"public-key.bin").write_bytes(public)
    (work/"expected-binding.json").write_text(
        json.dumps({k:json.loads(signed.payload_bytes)[k]
                    for k in _v2_binding_names(root)},sort_keys=True),
        encoding="utf-8")
    # NEVER store/ship disposable private key; emit process terminates.
    return {"phase":"EMITTED","status":signed.status,
            "synthetic_claims":endpoint.calls,"fake_backend_calls":backend.calls,
            "private_key_exported":False,"independent_custody":False}


def _v2_binding_names(root: Path) -> tuple[str,...]:
    # Separate owner source pinned on disk, not a caller-selected schema.
    v2=freeze(root/"research/goal1_evaluator/terminal_v2.py", V2_SHA256)
    return v2["_BINDING_FIELDS"]



def replace_all_local_receipt_and_test_key(work: Path, status: str) -> None:
    """Adversarial test: overwrite every local proof owned by same test user.

    Re-sign a DIFFERENT synthetic outcome using a fresh attacker key, replacing
    the local public key too. This simulates the entire trust root being
    supplied by the subject, NOT a break of Ed25519 or of a properly pinned
    independently held public key. Operates exclusively on disposable files.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    db = work/"gateway.sqlite"
    invocation,_,_=reservation(status)
    with closing(sqlite3.connect(db)) as connection:
        row=connection.execute(
            "SELECT terminal_bytes FROM attempts WHERE invocation_id=?",
            (invocation,)).fetchone()
    if row is None or type(row[0]) is not bytes:
        raise AssertionError("cannot stage fake receipt")
    original=json.loads(row[0])
    forged={**original}
    if status=="COMPLETED":
        forged["response_sha256"]=sha(b"FAKE MODEL OUTPUT NOT EMITTED")
    else:
        forged["terminal_utc"]="2030-01-01T00:00:00+00:00"
    if forged==original:
        raise AssertionError("adversarial rewrite did not change exact signed bytes")
    bytes_for_attacker=json.dumps(
        forged,sort_keys=True,separators=(",",":"),ensure_ascii=False,
        allow_nan=False).encode("utf-8")
    attacker=Ed25519PrivateKey.generate()
    attacker_signature=attacker.sign(bytes_for_attacker)
    # In real deployment the trusted verifier key MUST be pinned OUTSIDE this
    # learner/gateway-writable folder. Here the test control is fully local.
    with closing(sqlite3.connect(db)) as connection,connection:
        updated=connection.execute("""UPDATE attempts
          SET terminal_json=?,terminal_bytes=?,terminal_sha256=?,signature_hex=?
          WHERE invocation_id=?""",(
            bytes_for_attacker.decode("utf-8"),sqlite3.Binary(bytes_for_attacker),
            sha(bytes_for_attacker),attacker_signature.hex(),invocation,
        ))
        if updated.rowcount != 1:
            raise AssertionError("missing disposable receipt")
    (work/"public-key.bin").write_bytes(
        attacker.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw))

def read(root: Path, work: Path, status: str, tamper: str) -> dict:
    gateway,v2,_=frozen_source(root)
    common_owner_rewrite = tamper=="rewrite_all"
    prior_test_public_key = None
    if common_owner_rewrite:
        # Snapshot the previously trusted key before this disposable attack.
        prior_test_public_key = (work/"public-key.bin").read_bytes()
        replace_all_local_receipt_and_test_key(work,status)
        # Any independently pinned public key would reject this replacement.
        # The test's own mutable public-key file is intentionally untrusted.
        tamper="none"
    invocation,prompt,record=reservation(status)
    db=work/"gateway.sqlite"
    if tamper=="local_db":
        with closing(sqlite3.connect(db)) as con,con:
            con.execute("UPDATE attempts SET run_id=? WHERE invocation_id=?",
                        ("attacker-replaced-run",invocation))
    try:
        recovered=gateway["GatewayAttemptStore"](db).signed_terminal(invocation)
    except gateway["GatewayHold"]:
        if tamper!="local_db":
            raise
        return {"phase":"READ_DENIED","tamper":"local_db",
                "tamper_rejected":True,"qualified":False}
    if tamper=="local_db":
        raise AssertionError("locally altered reservation was read")
    if recovered.qualified or recovered.independent_claim_verified:
        raise AssertionError("local source promoted external authority")
    if recovered.status!=status or recovered.payload_sha256!=sha(recovered.payload_bytes):
        raise AssertionError("status or signed-byte SHA changed at restart")
    wire=recovered.payload_bytes
    signature=recovered.signature
    public=(work/"public-key.bin").read_bytes()
    binding=json.loads((work/"expected-binding.json").read_text(encoding="utf-8"))
    if frozenset(binding)!=frozenset(v2["_BINDING_FIELDS"]):
        raise AssertionError("expected binding shape mismatch")
    payload=json.loads(wire)
    if any(payload[k]!=v for k,v in binding.items()):
        raise AssertionError("frozen expected binding mismatch")
    class FakeIndependentClaim:
        def verify_claim_evidence(self,*,expected_binding):
            result={**expected_binding,"status":"CLAIMED"}
            if tamper=="claim":
                result["claim_id"]="fake-other-claim"
            return result
    if tamper=="wire":
        wire+=b" "
    if tamper=="signature":
        signature=b"\0"*len(signature)
    args={
        "payload_bytes":wire,"signature":signature,
        "pinned_gateway_public_key":public,
        "expected_gateway_id":"research-gateway",
        "expected_key_id":"ONE_PROCESS_TEST_SIGNER",
        "expected_binding":binding,
        "claim_evidence_verifier":FakeIndependentClaim(),
    }
    original_pin_rejects_rewrite = False
    if common_owner_rewrite:
        try:
            v2["verify_terminal_v2"](
                **{**args,"pinned_gateway_public_key":prior_test_public_key})
        except ValueError:
            original_pin_rejects_rewrite = True
        else:
            raise AssertionError("forged signature unexpectedly accepted with original pinned test key")
    try:
        result=v2["verify_terminal_v2"](**args)
    except ValueError:
        if tamper=="none":
            raise
        return {"phase":"READ_DENIED","tamper":tamper,
                "tamper_rejected":True,"qualified":False}
    if tamper!="none":
        raise AssertionError("tampered receipt passed V2")
    if result["qualified"] is not False:
        raise AssertionError("synthetic source verifier claimed independent qualification")
    expected="VERIFIED_"+status
    if result["status"]!=expected:
        raise AssertionError("unexpected verifier classification")
    if status=="OUTCOME_UNKNOWN":
        if result["score_eligible"] or any(payload[k] is not None for k in (
            "response_sha256","prompt_tokens","output_tokens",
            "gateway_wall_ms","backend_wall_ms")):
            raise AssertionError("unknown fabricated response or measured usage")
    if result["automatic_retry_permitted"]:
        raise AssertionError("terminal permits retry")
    # Even under different invocation IDs, same run/arm/challenge never redispatches.
    altered={**record,"reservation_id":record["reservation_id"]+"-different"}
    try:
        gateway["GatewayAttemptStore"](db).reserve(
            altered,"research-gateway",invocation+"-different")
    except gateway["GatewayHold"]:
        replay_refused=True
    else:
        raise AssertionError("cold restarted attempt was replayable")
    return {"phase":"VERIFIED_BY_NEW_PROCESS","status":result["status"],
            "score_eligible":result["score_eligible"],
            "cold_restart_replay_refused":replay_refused,
            "original_bytes_retained":True,"qualified":False,
            "claim_authority":"SYNTHETIC_SAME_USER_NOT_INDEPENDENT",
            "attacker_replaced_local_key_and_receipt_still_verified":common_owner_rewrite,
            "original_pin_rejects_rewrite":original_pin_rejects_rewrite}


def report_gate(report: dict, *, require_source: bool, require_independent: bool)->int:
    """Never confuse OS process separation with independent trust custody."""
    if require_independent:
        return 2
    if not require_source:
        return 0
    if type(report) is not dict or report.get("classification")!="PROCESS_SEPARATION_ONLY":
        return 2
    cases=report.get("cases")
    if type(cases) is not list or len(cases)!=2:
        return 2
    if {c.get("status") for c in cases if type(c) is dict}!={"COMPLETED","OUTCOME_UNKNOWN"}:
        return 2
    if any(type(c) is not dict
           or c.get("new_process_verified") is not True
           or c.get("source_restart_replay_refused") is not True
           or c.get("tamper_paths_rejected") is not True
           or c.get("common_owner_rewrite_accepted") is not True
           or c.get("original_pin_rejects_rewrite") is not True
           or c.get("independent_custody") is not False
           or c.get("qualified") is not False for c in cases):
        return 2
    return 0


def orchestrate(root: Path) -> dict:
    cases=[]
    # Subprocess evidence: every write and every verification genuinely occurs
    # in a separate OS process and survives process termination.
    with tempfile.TemporaryDirectory(prefix="goal1-durable-reader-restart-") as tmp:
        for status in ("COMPLETED","OUTCOME_UNKNOWN"):
            work=Path(tmp)/status
            work.mkdir()
            def call(mode, tamper="none"):
                command=[sys.executable,str(Path(__file__).resolve()),"--source-root",str(root),
                         "--work",str(work),"--status",status,
                         "--mode",mode,"--tamper",tamper]
                result=subprocess.run(command,capture_output=True,text=True)
                if result.returncode:
                    raise AssertionError(
                        f"child {mode} {status} {tamper} failed:\n"+result.stderr[-1300:])
                return json.loads(result.stdout)
            written=call("emit")
            good=call("read")
            negatives={}
            for bad in ("wire","signature","claim"):
                negatives[bad]=call("read",bad)
            # DB mutation is destructive *only* inside disposable test dir;
            # run it last after other readback paths.
            rewritten=call("read","rewrite_all")
            if (not rewritten["attacker_replaced_local_key_and_receipt_still_verified"]
                    or not rewritten["original_pin_rejects_rewrite"]):
                raise AssertionError("original key/whole-local-root falsifier failed")
            negatives["local_db"]=call("read","local_db")
            if written["status"]!=status or good["status"]!="VERIFIED_"+status:
                raise AssertionError("separate process did not recover correct terminal")
            if any(not x["tamper_rejected"] for x in negatives.values()):
                raise AssertionError("a tamper test was accepted")
            cases.append({
                "status":status,
                "new_process_verified":True,
                "source_restart_replay_refused":good["cold_restart_replay_refused"],
                "tamper_paths_rejected":True,
                "common_owner_rewrite_accepted":True,
                "original_pin_rejects_rewrite":True,
                "independent_custody":False,
                "qualified":False,
            })
    return {
        "schema":"GOAL1_CROSS_PROCESS_TERMINAL_RESTART_FALSIFIER_V1",
        "classification":"PROCESS_SEPARATION_ONLY",
        "cases":cases,
        "gateway_sha256":GATEWAY_SHA256,"malaphor_v2_sha256":V2_SHA256,
        "independent_issuer_or_key_custody":False,
        "real_provider_call":False,"selected_qvr_runtime":False,
        "learning_qualified":False,
    }


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--source-root",type=Path,required=True)
    p.add_argument("--mode",choices=("run","emit","read"),default="run")
    p.add_argument("--work",type=Path)
    p.add_argument("--status",choices=("COMPLETED","OUTCOME_UNKNOWN"))
    p.add_argument("--tamper",choices=("none","wire","signature","claim","local_db","rewrite_all"),default="none")
    p.add_argument("--require-source",action="store_true")
    p.add_argument("--require-independent",action="store_true")
    args=p.parse_args()
    if args.mode=="run":
        result=orchestrate(args.source_root)
        code=report_gate(result,require_source=args.require_source,
                         require_independent=args.require_independent)
    else:
        if args.work is None or args.status is None:
            p.error("--work and --status required for child mode")
        result=(emit(args.source_root,args.work,args.status)
                if args.mode=="emit" else
                read(args.source_root,args.work,args.status,args.tamper))
        code=0
    print(json.dumps(result,sort_keys=True))
    raise SystemExit(code)
