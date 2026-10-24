"""Research-only QVR process launched *inside* networkless Docker.

Wire is one request + one response on stdin/stdout. This worker has no model
network and never authenticates evaluator claims; the host broker must do so
before returning any receipt. Synthetic tests use an INERT host callback.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from vera_core import QualifiedVeraRuntime, VeraStateDirectory
from vera_core.local_cognition import InferencePermit, LocalTextReceipt, EXACT_TEST_SCOPE

MAX_LINE = 18000

def receive() -> dict:
    line = sys.stdin.buffer.readline(MAX_LINE + 1)
    if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise ValueError("missing/oversized IPC")
    value = json.loads(line.decode("utf-8"))
    if type(value) is not dict:
        raise ValueError("invalid IPC object")
    return value

def send(value: dict) -> None:
    sys.stdout.write(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n")
    sys.stdout.flush()

class OutsideOnlyTransport:
    def generate(self,prompt: str, *,permit: InferencePermit,max_tokens: int) -> LocalTextReceipt:
        send({"kind":"GATEWAY_REQUEST","prompt":prompt,"model":permit.model,
              "model_digest":permit.digest,
              "prompt_sha256":hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
              "max_tokens":max_tokens})
        answer=receive()
        if frozenset(answer)!={"kind","text","model","model_digest",
                                "prompt_sha256","response_sha256"} or answer["kind"]!="GATEWAY_RESPONSE":
            raise ValueError("unexpected gateway IPC response")
        text=answer["text"]
        if type(text) is not str or len(text.encode("utf-8"))>4096:
            raise ValueError("gateway text invalid")
        if (answer["model"]!=permit.model or answer["model_digest"]!=permit.digest
                or answer["prompt_sha256"]!=hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                or answer["response_sha256"]!=hashlib.sha256(text.encode("utf-8")).hexdigest()):
            raise ValueError("gateway response integrity mismatch")
        return LocalTextReceipt(text=text,model=permit.model,
            reported_model_digest=permit.digest,prompt_sha256=answer["prompt_sha256"],
            response_sha256=answer["response_sha256"])

def runtime():
    return QualifiedVeraRuntime.from_state_directory(
        VeraStateDirectory(Path("/state"), project_id="goal1-cell-research",
                           identity_id="synthetic-vera"),
        local_cognition_transport=OutsideOnlyTransport(),
        local_cognition_route_ref="OUTSIDE_STDIO_TEST_ONLY",
    )

def main() -> int:
    message=receive()
    mode=message.get("kind")
    if mode=="READBACK" and frozenset(message)=={"kind"}:
        qvr=runtime()
        rows=qvr.local_cognition_history()
        send({"kind":"READBACK_RESULT","entries":len(rows),
              "invocation_ids":[row["invocation_id"] for row in rows],
              "qualified":False})
        return 0
    if mode!="INVOKE" or frozenset(message)!={
            "kind","prompt","model","model_digest","invocation_id","max_tokens"}:
        raise ValueError("invalid invocation IPC")
    prompt=message["prompt"]
    if type(prompt) is not str or not prompt or len(prompt.encode("utf-8"))>4096:
        raise ValueError("invalid prompt")
    permit=InferencePermit(model=message["model"],digest=message["model_digest"],
                           scope=EXACT_TEST_SCOPE)
    qvr=runtime()
    result=qvr.consume_local_cognition(prompt,permit=permit,
        invocation_id=message["invocation_id"],max_tokens=message["max_tokens"])
    send({"kind":"INVOKE_RESULT","response_sha256":result.response_sha256,
          "journal_entries":len(qvr.local_cognition_history()),
          "qualified":False})
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(type(exc).__name__+": "+str(exc)[:120],file=sys.stderr)
        raise SystemExit(7)
