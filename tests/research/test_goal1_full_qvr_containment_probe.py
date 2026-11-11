from __future__ import annotations

import json
from types import SimpleNamespace
import pytest

from research.goal1_acceptance_bridge.full_qvr_containment_probe import (
    build_full_qvr_probe_command, probe_full_qvr,
)

IMAGE="sha256:"+"a"*64
GOOD={
    "schema":"GOAL1_FULL_QVR_PROCESS_CELL_V1",
    "qvr_imported_in_container":True,
    "python":"3.12.15",
    "raw_provider_probes":{"loopback":"UNREACHABLE","docker_bridge":"UNREACHABLE"},
    "selected_runtime":False,
    "gateway_authorized":False,
    "durable_state_qualified":False,
    "learning_qualified":False,
}

def test_container_has_no_network_mounts_or_socket_or_ports():
    args=build_full_qvr_probe_command(IMAGE)
    for required in ["--network=none","--read-only","--cap-drop=ALL",
                     "--security-opt=no-new-privileges","--user=65534:65534",
                     "--pull=never","--ipc=private"]:
        assert required in args
    assert not any(x in args for x in ("-v","--mount","--privileged","--network=host",
                                      "-p","--publish","--env","-e","--device"))
    assert args[args.index("--entrypoint=python")+1]==IMAGE

@pytest.mark.parametrize("image", ["python:3.12-slim","sha256:bad","",None,42])
def test_mutable_or_invalid_image_rejected(image):
    with pytest.raises(ValueError):
        build_full_qvr_probe_command(image)

def test_full_process_positive_report_is_only_research_evidence():
    result=probe_full_qvr(IMAGE,runner=lambda *a,**k:
        SimpleNamespace(returncode=0,stdout=json.dumps(GOOD),stderr=""))
    assert result.report["qvr_imported_in_container"]
    assert result.report["selected_runtime"] is False

@pytest.mark.parametrize("change", [
    {"qvr_imported_in_container":False},
    {"selected_runtime":True},
    {"gateway_authorized":True},
    {"learning_qualified":True},
    {"durable_state_qualified":True},
    {"raw_provider_probes":{"loopback":"REACHABLE","docker_bridge":"UNREACHABLE"}},
])
def test_forged_or_unqualified_evidence_rejected(change):
    forged={**GOOD,**change}
    with pytest.raises(RuntimeError):
        probe_full_qvr(IMAGE,runner=lambda *a,**k:
            SimpleNamespace(returncode=0,stdout=json.dumps(forged),stderr=""))

def test_nonzero_worker_rejected():
    with pytest.raises(RuntimeError):
        probe_full_qvr(IMAGE,runner=lambda *a,**k:
            SimpleNamespace(returncode=1,stdout="",stderr="failed"))
