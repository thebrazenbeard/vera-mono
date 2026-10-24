"""Host-side research broker for a networkless *full* QVR process.

The host owns Docker execution and the only outside gateway callback. QVR lives
inside the container, not alongside it. A dedicated Docker named volume holds
QVR's journal across container restarts. No host path/daemon socket is mounted.
This is NOT authenticated gateway/evaluator custody or a production route.
"""
from __future__ import annotations

import hashlib
import json
import queue
import re
import subprocess
from threading import Thread
from typing import Callable

from .full_qvr_containment_probe import PIN

VOLUME=re.compile(r"goal1-qvr-[a-z0-9-]{1,48}\Z")
WORKER="/opt/vera/research/goal1_acceptance_bridge/full_qvr_stdio_worker.py"

def build_command(image_id: str, volume: str) -> list[str]:
    if type(image_id) is not str or not PIN.fullmatch(image_id):
        raise ValueError("immutable image ID required")
    if type(volume) is not str or not VOLUME.fullmatch(volume):
        raise ValueError("restricted experiment-owned volume required")
    return ["docker","run","--rm","--pull=never","--network=none",
            "--read-only","--cap-drop=ALL",
            "--security-opt=no-new-privileges","--user=65534:65534",
            "--pids-limit=32","--memory=256m","--cpus=0.5",
            "--ipc=private",
            "--mount=type=volume,src="+volume+",dst=/state",
            "--entrypoint=python","-i",image_id,"-u",WORKER]

def _exchange(image_id: str, volume: str, first: dict, callback=None) -> dict:
    command=build_command(image_id,volume)
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,text=True,bufsize=1)
    messages=queue.Queue()
    def read():
        for line in proc.stdout:
            messages.put(line)
        messages.put(None)
    Thread(target=read,daemon=True).start()
    try:
        proc.stdin.write(json.dumps(first,sort_keys=True)+"\n")
        proc.stdin.flush()
        def next_message():
            try:
                line=messages.get(timeout=20)
            except queue.Empty as exc:
                raise RuntimeError("QVR stdio timeout; outcome unknown") from exc
            if line is None or len(line)>19000:
                raise RuntimeError("missing/oversized QVR IPC")
            value=json.loads(line)
            if type(value) is not dict:
                raise RuntimeError("invalid QVR IPC")
            return value
        output=next_message()
        if callback is not None:
            if output.get("kind")!="GATEWAY_REQUEST":
                raise RuntimeError("QVR failed to request gateway")
            prompt=first["prompt"]
            sha=hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            if (frozenset(output)!={"kind","prompt","model","model_digest",
                                     "prompt_sha256","max_tokens"}
                or output["prompt"]!=prompt
                or output["model"]!=first["model"]
                or output["model_digest"]!=first["model_digest"]
                or output["prompt_sha256"]!=sha
                or output["max_tokens"]!=first["max_tokens"]):
                raise RuntimeError("QVR gateway identity mismatch")
            # Callback is outside the learner and must authenticate any actual
            # evaluator claim. Current research acceptance uses an inert double.
            reply=callback(prompt,model=first["model"],
                           model_digest=first["model_digest"],
                           max_tokens=first["max_tokens"])
            if type(reply) is not dict:
                raise RuntimeError("invalid host gateway callback")
            proc.stdin.write(json.dumps(reply,sort_keys=True)+"\n")
            proc.stdin.flush()
            output=next_message()
        proc.stdin.close()
        code=proc.wait(timeout=20)
        if code!=0:
            raise RuntimeError("QVR worker failed; outcome unknown")
        return output
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()

def invoke_with_host_callback(*,image_id: str,volume: str,prompt: str,
                              model: str,digest: str,invocation_id: str,
                              callback: Callable[...,dict],max_tokens: int=3) -> dict:
    if (type(prompt) is not str or not prompt or len(prompt.encode("utf-8"))>4096
        or type(max_tokens) is not int or not 1<=max_tokens<=128
        or type(invocation_id) is not str or not invocation_id
        or not callable(callback)):
        raise ValueError("invalid bounded invocation")
    result=_exchange(image_id,volume,{
        "kind":"INVOKE","prompt":prompt,"model":model,"model_digest":digest,
        "invocation_id":invocation_id,"max_tokens":max_tokens},callback)
    if (frozenset(result)!={"kind","response_sha256","journal_entries","qualified"}
        or result["kind"]!="INVOKE_RESULT" or result["qualified"] is not False
        or type(result["journal_entries"]) is not int
        or result["journal_entries"]<1):
        raise RuntimeError("unqualified/malformed QVR terminal")
    return result

def cold_readback(*,image_id: str,volume: str) -> dict:
    result=_exchange(image_id,volume,{"kind":"READBACK"})
    if (frozenset(result)!={"kind","entries","invocation_ids","qualified"}
        or result["kind"]!="READBACK_RESULT"
        or result["qualified"] is not False
        or type(result["entries"]) is not int
        or type(result["invocation_ids"]) is not list
        or result["entries"]!=len(result["invocation_ids"])):
        raise RuntimeError("unqualified/malformed cold readback")
    return result
