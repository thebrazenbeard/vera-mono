"""Explicit, synthetic-shaped Mini-Vera request -> local chat-completion adapter.

This is an opt-in experiment, not a model installer, a memory connection, or an
identity transfer.  The composed request and its hashes are operator-supplied;
they are not signatures or proof that the claimed model, public privacy label,
synthetic origin, or source bytes are genuine.  Malicious operator-provided
text can be rehashed into an otherwise structurally valid candidate.  Only a
numeric HTTP loopback endpoint can receive the bounded candidate, and this
adapter cannot attest to the server's own behavior or plugins.
"""

from __future__ import annotations

import argparse
import hashlib
from http.client import HTTPConnection as _HTTPConnection, HTTPException
import io
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from typing import Any


MAX_REQUEST_FILE = 32_768
MAX_RESPONSE_BYTES = 131_072
MAX_CONTENT_BYTES = 65_536
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")


class LoopbackRejected(ValueError):
    """An attempted local inference violates the bounded experimental contract."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for k, v in pairs:
        if k in result:
            raise LoopbackRejected("duplicate JSON key")
        result[k] = v
    return result


def _constant(value: str) -> None:
    raise LoopbackRejected(f"invalid JSON constant: {value}")


def _parse_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                           parse_constant=_constant)
    except (UnicodeError, ValueError) as exc:
        raise LoopbackRejected("invalid UTF-8 JSON object") from exc
    if type(value) is not dict:
        raise LoopbackRejected("JSON object required")
    return value


def _text(value: object, name: str, max_bytes: int) -> str:
    if (type(value) is not str or not value.strip()
            or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
            or len(value.encode("utf-8")) > max_bytes):
        raise LoopbackRejected(f"invalid {name}")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or HEX64.fullmatch(value) is None:
        raise LoopbackRejected(f"invalid {name}")
    return value


def read_candidate(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_REQUEST_FILE:
        raise LoopbackRejected("missing or oversized composed request")
    raw = path.read_bytes()
    if len(raw) > MAX_REQUEST_FILE:
        raise LoopbackRejected("oversized composed request")
    return _parse_object(raw)


def _endpoint(url: str) -> tuple[str, int, str]:
    if type(url) is not str:
        raise LoopbackRejected("explicit numeric loopback endpoint required")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise LoopbackRejected("invalid endpoint") from exc
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
            or type(port) is not int or not 1 <= port <= 65535
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"/v1", "/v1/"} or parsed.query or parsed.fragment):
        raise LoopbackRejected("only an exact numeric HTTP loopback /v1 endpoint is allowed")
    host = parsed.hostname
    netloc = f"[::1]:{port}" if host == "::1" else f"127.0.0.1:{port}"
    if url not in {f"http://{netloc}/v1", f"http://{netloc}/v1/"}:
        raise LoopbackRejected("noncanonical endpoint")
    return host, port, f"http://{netloc}/v1"


def validate_candidate(request: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Validate the composer's claimed *shape* and self-hash, not origin/privacy."""
    if type(request) is not dict or set(request) != {
        "schema", "inference", "request_sha256", "provenance", "evidence",
    } or request["schema"] != "MINI_VERA_COMPOSED_REQUEST_V1":
        raise LoopbackRejected("unknown composed request schema")
    evidence = request["evidence"]
    if evidence != {
        "class": "SOURCE_COMPOSED_ONLY", "model_calls": 0,
        "memory_admission": "NOT_PERFORMED", "authority_effect": "NONE",
        "behavioral_qualification": "NOT_TESTED",
    }:
        raise LoopbackRejected("composed request carries invalid effect evidence")
    provenance = request["provenance"]
    if type(provenance) is not dict or set(provenance) != {
        "identity_sha256", "behavior_sha256", "state_sha256", "state_revision",
        "turn_sha256", "model_registry_digest", "model_identity_level",
    } or provenance["model_identity_level"] != "OPERATOR_DECLARED_NOT_ATTESTED":
        raise LoopbackRejected("invalid provenance envelope")
    for field in ("identity_sha256", "behavior_sha256", "state_sha256",
                  "turn_sha256", "model_registry_digest"):
        _digest(provenance[field], field)
    if type(provenance["state_revision"]) is not int or provenance["state_revision"] < 0:
        raise LoopbackRejected("invalid declared state revision")

    inference = request["inference"]
    if type(inference) is not dict or set(inference) != {"model", "messages", "options", "stream"}:
        raise LoopbackRejected("invalid model request")
    if type(inference["model"]) is not str or MODEL.fullmatch(inference["model"]) is None:
        raise LoopbackRejected("invalid model alias")
    if inference["stream"] is not False or inference["options"] != {
        "temperature": 0, "seed": 20261106, "num_predict": 128,
    }:
        raise LoopbackRejected("only bounded non-streamed composer settings admitted")
    messages = inference["messages"]
    if (type(messages) is not list or len(messages) != 2
            or any(type(m) is not dict or set(m) != {"role", "content"} for m in messages)
            or [m["role"] for m in messages] != ["system", "user"]):
        raise LoopbackRejected("only composer system/user message pair admitted")
    _text(messages[0]["content"], "system content", 16_384)
    raw_user = _text(messages[1]["content"], "user content", 8192)
    inner = _parse_object(raw_user.encode("utf-8"))
    if set(inner) != {"synthetic_user_turn", "project_context_untrusted"}:
        raise LoopbackRejected("only synthetic turn envelope admitted")
    _text(inner["synthetic_user_turn"], "synthetic user text", 4096)
    records = inner["project_context_untrusted"]
    if type(records) is not list or len(records) > 8:
        raise LoopbackRejected("invalid synthetic record count")
    for record in records:
        if (type(record) is not dict
                or set(record) != {"record_id", "source_sha256", "text", "trust"}
                or record["trust"] != "UNVERIFIED_CONTEXT_DATA"):
            raise LoopbackRejected("untrusted synthetic record malformed")
        _text(record["record_id"], "record id", 80)
        if sha256(_text(record["text"], "record text", 384).encode("utf-8")) != _digest(
            record["source_sha256"], "record digest"
        ):
            raise LoopbackRejected("record digest mismatch")
    request_sha = _digest(request["request_sha256"], "request digest")
    if sha256(canonical(inference)) != request_sha:
        raise LoopbackRejected("composed request digest mismatch")
    payload = {
        "model": inference["model"], "messages": messages, "stream": False,
        "temperature": 0, "max_tokens": 128, "seed": 20261106,
    }
    return payload, sha256(canonical(payload))


def _remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("absolute local inference deadline exceeded")
    return value


class _DeadlineReader(io.RawIOBase):
    """Preserve one wall-clock deadline across response headers and body chunks."""

    def __init__(self, sock: Any, deadline: float) -> None:
        self.sock = sock
        self.deadline = deadline
        self.raw = sock.makefile("rb", buffering=0)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        self.sock.settimeout(_remaining(self.deadline))
        return self.raw.readinto(buffer)

    def close(self) -> None:
        try:
            self.raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    def __init__(self, sock: Any, deadline: float) -> None:
        self.sock, self.deadline = sock, deadline

    def sendall(self, data: bytes) -> None:
        self.sock.settimeout(_remaining(self.deadline))
        self.sock.sendall(data)

    def makefile(self, mode: str) -> io.BufferedReader:
        if mode != "rb":
            raise ValueError("response read mode must be rb")
        return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))

    def close(self) -> None:
        self.sock.close()


class _DeadlineConnection(_HTTPConnection):
    def __init__(self, host: str, port: int, *, timeout: int) -> None:
        super().__init__(host, port, timeout=timeout)
        self.deadline = time.monotonic() + timeout

    def connect(self) -> None:
        self.timeout = _remaining(self.deadline)
        super().connect()
        if self.sock is None:
            raise ConnectionError("local socket missing")
        self.sock = _DeadlineSocket(self.sock, self.deadline)


def _parse_response(raw: bytes, model: str) -> tuple[str, str]:
    body = _parse_object(raw)
    if body.get("model") != model:
        raise LoopbackRejected("local response does not echo the requested model alias")
    choices = body.get("choices")
    if type(choices) is not list or len(choices) != 1:
        raise LoopbackRejected("exactly one local response choice required")
    choice = choices[0]
    if type(choice) is not dict or type(choice.get("message")) is not dict:
        raise LoopbackRejected("malformed local model response")
    message = choice["message"]
    if (message.get("role") != "assistant" or message.get("tool_calls") is not None
            or message.get("function_call") is not None):
        raise LoopbackRejected("effectful or non-assistant output refused")
    result = _text(message.get("content"), "local response text", MAX_CONTENT_BYTES).strip()
    if any((ord(ch) < 32 and ch not in "\n\t") or 127 <= ord(ch) <= 159
           or ord(ch) in {0x061C, 0x200E, 0x200F}
           or 0x202A <= ord(ch) <= 0x202E or 0x2066 <= ord(ch) <= 0x206F
           for ch in result):
        raise LoopbackRejected("terminal or directional control in model output")
    finish = choice.get("finish_reason")
    if type(finish) is not str or finish not in {"stop", "length"}:
        raise LoopbackRejected("unsupported finish reason")
    return result, finish


def execute(request: dict[str, Any], *, endpoint: str, timeout_seconds: int = 30) -> dict[str, Any]:
    """One explicitly authorized local HTTP call; results confer zero authority."""
    host, port, canonical_url = _endpoint(endpoint)
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise LoopbackRejected("timeout must be 1..120 seconds")
    payload, payload_sha = validate_candidate(request)
    connection = _DeadlineConnection(host, port, timeout=timeout_seconds)
    response = None
    try:
        connection.request("POST", "/v1/chat/completions", body=canonical(payload),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise LoopbackRejected(f"local completion HTTP status {response.status}")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, HTTPException) as exc:
        raise LoopbackRejected("local completion transport unavailable or timed out") from exc
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            connection.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise LoopbackRejected("local model response oversized")
    text, finish = _parse_response(raw, payload["model"])
    return {
        "schema": "MINI_VERA_UNVERIFIED_LOOPBACK_RESULT_V1",
        "status": "UNVERIFIED_LOCAL_MODEL_OUTPUT" if finish == "stop" else "TRUNCATED_UNVERIFIED_OUTPUT",
        "response": {"text": text, "finish_reason": finish},
        "provenance": {
            "composed_request_sha256": request["request_sha256"],
            "sent_payload_sha256": payload_sha, "received_text_sha256": sha256(text.encode("utf-8")),
            "model_alias_requested": payload["model"],
            "model_identity": "LOOPBACK_RESPONSE_ECHO_NOT_ATTESTED",
            "candidate_source_trust": "OPERATOR_SUPPLIED_NOT_AUTHENTICATED",
            "endpoint": canonical_url,
        },
        "evidence": {
            "class": "REAL_LOOPBACK_HTTP_RESPONSE_ONLY", "http_calls": 1,
            "memory_admission": "NOT_PERFORMED", "authority_effect": "NONE",
            "behavioral_qualification": "NOT_TESTED", "model_weights_verified": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--execute", action="store_true", help="Opt into one local HTTP call")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    candidate = read_candidate(args.request)
    _endpoint(args.endpoint)
    payload, sha = validate_candidate(candidate)
    if not args.execute:
        print(json.dumps({"status": "VALIDATED_NOT_EXECUTED", "http_calls": 0,
                          "sent_payload_sha256": sha}))
        return 0
    if args.output is None:
        parser.error("--output required with --execute")
    if args.output.exists():
        raise LoopbackRejected("output already exists; refusing a repeated model call")
    result = execute(candidate, endpoint=args.endpoint, timeout_seconds=args.timeout_seconds)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical(result) + b"\n")
    print(json.dumps({"status": result["status"], "result_sha256": sha256(canonical(result)),
                      "http_calls": 1}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
