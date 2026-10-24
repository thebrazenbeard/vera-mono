"""Reproducible PR #82 QVR -> networkless Docker learner -> inert host broker.

Synthetic source/run verification ONLY. It cannot establish installed selected
QVR service, claim custodian, real model bytes, protected route or learning.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

QVR82_SHA256 = {
    "qualified_runtime.py": "0466d85a19519f1e2c77fd51cf2f4d60964ecd9d57434c7a5b8a4e8472feb714",
    "local_cognition.py": "b6820102bc569081f6bc298936970d3bb58406171298cc9d9b254a626646c14d",
    "local_cognition_journal.py": "4bff14c593c58dd5e328a02ad00d4f583dac4a04f6b55aa1ccebbe8adbee5351",
}

_CHILD = r"""
import hashlib,json,sys
from pathlib import Path
from vera_core import QualifiedVeraRuntime,VeraStateDirectory
from vera_core.local_cognition import InferencePermit,LocalTextReceipt
from research.goal1_acceptance_bridge.networkless_qvr_transport import NetworklessQVRTransport
IMAGE, STATE=sys.argv[1:3]
calls=[]
def outside_broker(prompt,*,permit,max_tokens):
    calls.append((permit.model,max_tokens))
    text='INERT QVR NETWORKLESS TEST'
    return LocalTextReceipt(
        text=text,model=permit.model,
        reported_model_digest=permit.digest,
        prompt_sha256=hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
        response_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())
permit=InferencePermit(
    model='qwen3:4b-instruct',digest='a'*64,
    scope='SYNTHETIC_LOCAL_INFERENCE_TEST')
adapter=NetworklessQVRTransport(
    image_id=IMAGE,model=permit.model,digest=permit.digest,
    host_gateway_callback=outside_broker)
runtime=QualifiedVeraRuntime.from_state_directory(
    VeraStateDirectory(Path(STATE),project_id='qvr-netless-research',
                       identity_id='synthetic-vera'),
    local_cognition_transport=adapter,
    local_cognition_route_ref='NETWORKLESS_GATEWAY_TEST_ONLY')
result=runtime.consume_local_cognition(
    'QVR networkless research request',permit=permit,
    invocation_id='test-qvr-invocation-1',max_tokens=3)
rows=runtime.local_cognition_history()
assert len(calls)==len(rows)==1 and result.text=='INERT QVR NETWORKLESS TEST'
assert rows[0]['route_ref']=='NETWORKLESS_GATEWAY_TEST_ONLY'
try:
    runtime.consume_local_cognition(
        'QVR networkless research request',permit=permit,
        invocation_id='test-qvr-invocation-1',max_tokens=3)
except ValueError:
    pass
else:
    raise AssertionError('duplicate QVR invocation accepted')
assert len(calls)==1
print(json.dumps({
 'schema':'GOAL1_REAL_PR82_CLASS_COGNITION_CELL_V1',
 'qvr_class':type(runtime).__name__,
 'adapter_class':type(adapter).__name__,
 'local_journal_entries':len(rows),
 'host_broker_callbacks':len(calls),
 'duplicate_call_denied':True,
 'real_model_invoked':False,
 'selected_production_route':False,
 'independent_claim_evidence':False,
 'qualified_learning':False},sort_keys=True))
"""


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--qvr82-overlay",type=Path,required=True)
    parser.add_argument("--image-id",required=True)
    args=parser.parse_args()
    root=args.qvr82_overlay.resolve()
    for name,digest in QVR82_SHA256.items():
        path=root/"vera_core"/name
        if not path.is_file():
            raise ValueError("missing PR82 source "+name)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError("PR82 source pin changed "+name)
    # Caller places exact QVR82 package first on PYTHONPATH, followed by
    # independently selected project-package dependencies from one checkout.
    env=dict(os.environ)
    overlay=str(root)
    parts=env.get("PYTHONPATH","").split(os.pathsep)
    if not parts or Path(parts[0]).resolve()!=root:
        raise ValueError("QVR82 overlay must be the first PYTHONPATH entry")
    with tempfile.TemporaryDirectory(prefix="goal1-qvr82-child-restart-") as td:
        state=Path(td)/"state"
        result=subprocess.run(
            [sys.executable,"-c",_CHILD,args.image_id,str(state)],
            capture_output=True,text=True,env=env,timeout=30)
        if result.returncode:
            raise RuntimeError("QVR82 child failed: "+result.stderr[-1600:])
        report=json.loads(result.stdout)
        if (report.get("qvr_class")!="QualifiedVeraRuntime"
                or report.get("local_journal_entries")!=1
                or report.get("host_broker_callbacks")!=1
                or report.get("qualified_learning") is not False):
            raise AssertionError("QVR82 runtime consumption mismatch")
        # Child is now dead and its SQLite handles are closed. Reopen through
        # actual PR82 runtime code, validate persisted metadata, then cleanup.
        from vera_core import QualifiedVeraRuntime,VeraStateDirectory
        from vera_core.local_cognition import LocalTextReceipt
        runtime=QualifiedVeraRuntime.from_state_directory(
            VeraStateDirectory(state,project_id="qvr-netless-research",
                               identity_id="synthetic-vera"))
        history=runtime.local_cognition_history()
        if len(history)!=1 or history[0]["invocation_id"]!="test-qvr-invocation-1":
            raise AssertionError("cold readback lost actual QVR journal")
        if "QVR networkless research request" in json.dumps(history):
            raise AssertionError("QVR journal leaked prompt")
        # Windows SQLite handles remain alive inside this parent until process
        # exit; do not claim immediate scratch deletion from this context.
        print(json.dumps({
            "schema":"GOAL1_QVR82_NETWORKLESS_ACTUAL_CLASS_ACCEPTANCE_V1",
            "child_exit":result.returncode,
            "child_report":report,
            "cold_readback_entries":len(history),
            "source_shas":QVR82_SHA256,
            "production_route_selected":False,
            "independent_gateway_claim_qualified":False,
        },sort_keys=True))
        # Avoid cleanup errors caused by open sqlite3 handle lifetimes on Win.
        # TemporaryDirectory cleanup is deferred/retained for process exit.


if __name__=="__main__":
    main()
