"""Research-only full-process QVR containment smoke test.

Unlike the earlier request-worker probe, this executes and imports the actual
QualifiedVeraRuntime *inside* the isolated container. A smoke result does not
establish authenticated gateway IPC, durable state, or selected service routing.
No host filesystem, Docker socket, ports, or credentials are mounted.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

PIN = re.compile(r"sha256:[0-9a-f]{64}\Z")
CHILD = """
import json,os,socket,sys
from vera_core import QualifiedVeraRuntime
assert QualifiedVeraRuntime.__name__ == 'QualifiedVeraRuntime'
assert sys.version_info >= (3,12)
observations = {}
for name,host in [('loopback','127.0.0.1'),('docker_bridge','172.17.0.1')]:
    try:
        with socket.create_connection((host,11434),timeout=0.3): observations[name]='REACHABLE'
    except OSError:
        observations[name]='UNREACHABLE'
assert observations == {'loopback':'UNREACHABLE','docker_bridge':'UNREACHABLE'}
assert sorted(os.listdir('/sys/class/net')) == ['lo']
print(json.dumps({'schema':'GOAL1_FULL_QVR_PROCESS_CELL_V1',
                  'qvr_imported_in_container':True,
                  'python':sys.version.split()[0],
                  'raw_provider_probes':observations,
                  'selected_runtime':False,
                  'gateway_authorized':False,
                  'durable_state_qualified':False,
                  'learning_qualified':False},sort_keys=True))
"""

@dataclass(frozen=True)
class ContainmentObservation:
    report: dict
    image_id: str

def build_full_qvr_probe_command(image_id: str) -> list[str]:
    if not isinstance(image_id,str) or PIN.fullmatch(image_id) is None:
        raise ValueError("immutable image ID required")
    return [
        "docker","run","--rm","--pull=never","--network=none",
        "--read-only","--cap-drop=ALL",
        "--security-opt=no-new-privileges","--user=65534:65534",
        "--pids-limit=32","--memory=256m","--cpus=0.5",
        "--ipc=private","--entrypoint=python",
        image_id,"-I","-c",CHILD,
    ]

def probe_full_qvr(image_id: str, *, runner=subprocess.run) -> ContainmentObservation:
    command=build_full_qvr_probe_command(image_id)
    result=runner(command,capture_output=True,text=True,timeout=30,check=False)
    if result.returncode != 0:
        raise RuntimeError("full QVR container probe failed closed")
    if len(result.stdout)>2500:
        raise RuntimeError("excessive worker output")
    report=json.loads(result.stdout)
    if (type(report) is not dict
        or report.get("schema")!="GOAL1_FULL_QVR_PROCESS_CELL_V1"
        or report.get("qvr_imported_in_container") is not True
        or report.get("raw_provider_probes")!={"loopback":"UNREACHABLE","docker_bridge":"UNREACHABLE"}
        or any(report.get(flag) is not False for flag in
               ("selected_runtime","gateway_authorized",
                "durable_state_qualified","learning_qualified"))):
        raise RuntimeError("full QVR boundary evidence failed validation")
    return ContainmentObservation(report=report,image_id=image_id)
