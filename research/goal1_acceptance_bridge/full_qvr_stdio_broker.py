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
import time
from threading import Event, Thread
from typing import Callable

from .full_qvr_containment_probe import PIN

VOLUME=re.compile(r"goal1-qvr-[a-z0-9-]{1,48}\Z")
WORKER="/opt/vera/research/goal1_acceptance_bridge/full_qvr_stdio_worker.py"
WORKER_MAX_LINE=18000
BROKER_MAX_LINE=19000
EXCHANGE_TIMEOUT_SECONDS=20
INVOKE_TIMEOUT_SECONDS=90  # Cold start + bounded authenticated model callback.

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

def _wire(value: dict) -> bytes:
    try:
        encoded=(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
    except (TypeError,ValueError) as exc:
        raise ValueError("invalid QVR IPC payload") from exc
    if len(encoded)>WORKER_MAX_LINE:
        raise ValueError("oversized QVR IPC payload")
    return encoded


def _exchange(image_id: str, volume: str, first: dict, callback=None,
              *, timeout_seconds: float=EXCHANGE_TIMEOUT_SECONDS) -> dict:
    # Bound serialized input *before* starting any subprocess. A valid JSON
    # string can far exceed the worker's byte-limited receive() contract.
    first_bytes=_wire(first)
    if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=120:
        raise ValueError("invalid QVR exchange deadline")
    command=build_command(image_id,volume)
    deadline=time.monotonic()+timeout_seconds
    proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,bufsize=0)
    messages=queue.Queue(maxsize=3)
    overflow=Event()

    def remaining():
        left=deadline-time.monotonic()
        if left<=0:
            raise RuntimeError("QVR exchange timeout; outcome unknown")
        return left

    def bounded(call):
        # Threads cannot cancel a host callback; after timeout its eventual
        # effect remains UNKNOWN and the same experiment must not auto-retry.
        result=queue.Queue(maxsize=1)
        def run():
            if time.monotonic()>=deadline:
                result.put((False,RuntimeError("QVR exchange timeout; outcome unknown")))
                return
            try:
                result.put((True,call()))
            except BaseException as exc:
                result.put((False,exc))
        Thread(target=run,daemon=True).start()
        try:
            ok,value=result.get(timeout=remaining())
        except queue.Empty as exc:
            raise RuntimeError("QVR exchange timeout; outcome unknown") from exc
        if not ok:
            raise value
        return value

    def read():
        try:
            while True:
                line=proc.stdout.readline(BROKER_MAX_LINE+1)
                if not line:
                    break
                try:
                    messages.put_nowait(line)
                except queue.Full:
                    overflow.set()
                    break
        except (OSError,ValueError):
            # The timeout path kills/closes the subprocess while its daemon
            # reader may still be waiting. Only a live-child read failure is
            # a new protocol fault; cleanup must not emit a thread traceback.
            if proc.poll() is None:
                overflow.set()
        finally:
            try:
                messages.put_nowait(None)
            except queue.Full:
                overflow.set()

    def drain_stderr():
        # Stderr is diagnostic/untrusted. Drain it without retaining its bytes
        # so a noisy child cannot deadlock Docker or exhaust the host broker.
        try:
            while proc.stderr.read(8192):
                pass
        except (OSError,ValueError):
            # Normal after timeout teardown closes the pipe from the caller.
            pass

    reader=Thread(target=read,daemon=True)
    reader.start()
    stderr_reader=Thread(target=drain_stderr,daemon=True)
    stderr_reader.start()
    try:
        bounded(lambda: (proc.stdin.write(first_bytes),proc.stdin.flush()))
        def next_message():
            try:
                line=messages.get(timeout=remaining())
            except queue.Empty as exc:
                raise RuntimeError("QVR stdio timeout; outcome unknown") from exc
            if (overflow.is_set() or line is None or len(line)>BROKER_MAX_LINE
                or not line.endswith(b"\n")):
                raise RuntimeError("missing/oversized QVR IPC")
            try:
                value=json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError,json.JSONDecodeError) as exc:
                raise RuntimeError("invalid QVR IPC encoding") from exc
            if type(value) is not dict:
                raise RuntimeError("invalid QVR IPC")
            return value
        output=next_message()
        expected_response_sha=None
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
            reply=bounded(lambda: callback(prompt,model=first["model"],
                                           model_digest=first["model_digest"],
                                           max_tokens=first["max_tokens"]))
            if (type(reply) is not dict
                or frozenset(reply)!={"kind","text","model","model_digest",
                                          "prompt_sha256","response_sha256"}
                or reply["kind"]!="GATEWAY_RESPONSE"
                or type(reply["text"]) is not str
                or len(reply["text"].encode("utf-8"))>4096
                or reply["model"]!=first["model"]
                or reply["model_digest"]!=first["model_digest"]
                or reply["prompt_sha256"]!=sha
                or reply["response_sha256"]!=hashlib.sha256(
                    reply["text"].encode("utf-8")).hexdigest()):
                raise RuntimeError("invalid host gateway callback")
            expected_response_sha=reply["response_sha256"]
            reply_bytes=_wire(reply)
            bounded(lambda: (proc.stdin.write(reply_bytes),proc.stdin.flush()))
            output=next_message()
            if (output.get("kind")=="INVOKE_RESULT"
                and output.get("response_sha256")!=expected_response_sha):
                raise RuntimeError("QVR terminal response digest mismatch")
        bounded(proc.stdin.close)
        try:
            code=proc.wait(timeout=remaining())
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("QVR worker timeout; outcome unknown") from exc
        if code!=0:
            raise RuntimeError("QVR worker failed; outcome unknown")
        reader.join(timeout=remaining())
        if reader.is_alive() or overflow.is_set() or any(
                item is not None for item in list(messages.queue)):
            raise RuntimeError("unexpected/oversized QVR IPC")
        return output
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
        # These threads only own subprocess pipes; callback threads may still
        # execute and remain explicitly outcome-unknown after a deadline.
        reader.join(timeout=0.5)
        stderr_reader.join(timeout=0.5)

def invoke_with_host_callback(*,image_id: str,volume: str,prompt: str,
                              model: str,digest: str,invocation_id: str,
                              callback: Callable[...,dict],max_tokens: int=3) -> dict:
    if (type(prompt) is not str or not prompt or len(prompt.encode("utf-8"))>4096
        or type(max_tokens) is not int or not 1<=max_tokens<=128
        or type(model) is not str or not model or len(model.encode("utf-8"))>256
        or type(digest) is not str or not digest or len(digest.encode("utf-8"))>128
        or type(invocation_id) is not str or not invocation_id
        or len(invocation_id.encode("utf-8"))>128
        or not callable(callback)):
        raise ValueError("invalid bounded invocation")
    result=_exchange(image_id,volume,{
        "kind":"INVOKE","prompt":prompt,"model":model,"model_digest":digest,
        "invocation_id":invocation_id,"max_tokens":max_tokens},callback,
        timeout_seconds=INVOKE_TIMEOUT_SECONDS)
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
