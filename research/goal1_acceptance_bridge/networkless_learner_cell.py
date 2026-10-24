"""Fail-closed, physically networkless learner request cell (research route).

A caller-controlled Lappy/host broker starts an UNPRIVILEGED, local-image-pinned
Docker process with --network none, no mounts, no daemon socket, no credentials,
no GPU, no elevation, a read-only rootfs and strict runtime limits. The sandbox
only emits a request over stdout; the trusted host invokes its OUTSIDE callback.

This removes learner direct TCP model access for THIS SANDBOX, not for an
unselected QVR process elsewhere. A host-provided callback is not proof of a
genuinely authenticated gateway or independently administered claim ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import subprocess
from typing import Callable
import uuid

_PIN = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORKER = r'''
import hashlib,json,os,socket,sys
try:
 request=json.loads(sys.stdin.read(20000))
 assert type(request) is dict
 assert type(request.get("nonce")) is str and 10 <= len(request["nonce"]) <= 128
 assert type(request.get("prompt")) is str and request["prompt"]
 interfaces=sorted(os.listdir("/sys/class/net"))
 checks={}
 for alias,host in (("container_loopback","127.0.0.1"),
                    ("docker_bridge_gateway","172.17.0.1")):
  try:
   conn=socket.create_connection((host,11434),timeout=0.25)
   conn.close()
   checks[alias]="REACHABLE"
  except OSError:
   checks[alias]="DENIED_OR_UNAVAILABLE"
 print(json.dumps({
   "schema":"GOAL1_NETWORKLESS_LEARNER_REQUEST_V1",
   "nonce":request["nonce"],"prompt_sha256":hashlib.sha256(
     request["prompt"].encode("utf-8")).hexdigest(),
   "network_interfaces":interfaces,"network_checks":checks,
   "proposal":"REQUEST_GATEWAY_INFERENCE","qualified":False,
 },sort_keys=True))
except Exception:
 sys.exit(3)
'''


class IsolationFailure(RuntimeError):
    """No gateway callback may be made after any sandbox validation failure."""


@dataclass(frozen=True)
class LearnerCellReport:
    schema: str
    isolation_observed: bool
    host_gateway_callback_called: bool
    gateway_effect_independently_verified: bool
    actual_selected_qvr_route_verified: bool
    learning_qualified: bool
    prompt_sha256: str
    gateway_callback_result: object


def build_command(image_id: str) -> list[str]:
    """No user-controlled Docker flags or worker code injection."""
    if type(image_id) is not str or not _PIN.fullmatch(image_id):
        raise ValueError("image must be a pre-existing immutable sha256 image ID")
    return [
        "docker", "run", "--rm", "--pull=never",
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--user=65534:65534",
        "--pids-limit=32", "--memory=128m", "--cpus=0.5",
        "--ipc=private", "--pid=private",
        "-i", image_id, "python", "-I", "-c", _WORKER,
    ]


def run_networkless_learner_step(
    *, image_id: str, prompt: str,
    gateway_callback: Callable[[str], object],
    runner: Callable[..., object] = subprocess.run,
) -> LearnerCellReport:
    """Request a host gateway effect only after sandbox transport validation.

    The worker cannot reach an external gateway by network, so only the host
    broker is allowed to communicate with Integration's authenticated gateway.
    This adapter does not replace that gateway or claim-v2 verification.
    """
    if type(prompt) is not str or not prompt or len(prompt.encode("utf-8")) > 12000:
        raise ValueError("prompt must be nonempty UTF-8 up to 12000 bytes")
    if not callable(gateway_callback):
        raise TypeError("gateway callback required")
    command = build_command(image_id)
    nonce = uuid.uuid4().hex
    request = json.dumps({"nonce": nonce, "prompt": prompt},sort_keys=True)
    try:
        result = runner(
            command, input=request, capture_output=True, text=True,
            timeout=15, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        raise IsolationFailure("sandbox execution unavailable") from exc
    if result.returncode != 0:
        raise IsolationFailure("sandbox worker failed")
    if len(result.stdout) > 6000:
        raise IsolationFailure("sandbox worker output exceeded bound")
    try:
        output = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise IsolationFailure("malformed sandbox response") from exc
    if type(output) is not dict or frozenset(output) != frozenset({
        "schema", "nonce", "prompt_sha256", "network_interfaces",
        "network_checks", "proposal", "qualified",
    }):
        raise IsolationFailure("sandbox response schema mismatch")
    if (output["schema"] != "GOAL1_NETWORKLESS_LEARNER_REQUEST_V1"
            or output["nonce"] != nonce
            or output["prompt_sha256"] != hashlib.sha256(
                prompt.encode("utf-8")).hexdigest()
            or output["proposal"] != "REQUEST_GATEWAY_INFERENCE"
            or output["qualified"] is not False
            or output["network_interfaces"] != ["lo"]
            or output["network_checks"] != {
                "container_loopback": "DENIED_OR_UNAVAILABLE",
                "docker_bridge_gateway": "DENIED_OR_UNAVAILABLE",
            }):
        raise IsolationFailure("sandbox direct route or request integrity not proved")
    # The untrusted worker cannot choose the gateway, reservation, key, endpoint
    # or callback. The parent owns those separately after transport succeeds.
    # A callback result alone is NEVER external attestation or trial success.
    callback_result = gateway_callback(prompt)
    return LearnerCellReport(
        schema="GOAL1_NETWORKLESS_LEARNER_CELL_V1",
        isolation_observed=True, host_gateway_callback_called=True,
        gateway_effect_independently_verified=False,
        actual_selected_qvr_route_verified=False,
        learning_qualified=False,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        gateway_callback_result=callback_result,
    )
