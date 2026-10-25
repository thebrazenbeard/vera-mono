"""Opt-in, cognition-only adapter for an operator-owned loopback model server.

This is deliberately not a Vera runtime route, a memory writer, or an effect
executor. It sends only the explicit prompt to one local inference endpoint and
returns a provenance-labelled, unverified model output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from http.client import HTTPConnection as _HTTPConnection, HTTPException
import io
import json
import os
import re
import time
from urllib.parse import urlsplit


MAX_PROMPT_CHARS = 12_000
MAX_RESPONSE_BYTES = 1_000_000
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+\-]{0,127}\Z")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class LocalModelError(RuntimeError):
    """A local inference request failed without granting any effect authority."""


def _time_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("local inference request exceeded its total deadline")
    return remaining


class _DeadlineReader(io.RawIOBase):
    """Recalculate the same absolute deadline before *every* socket receive."""

    def __init__(self, sock, deadline: float) -> None:
        super().__init__()
        self._sock = sock
        self._deadline = deadline
        # Native SocketIO keeps the descriptor alive when http.client closes
        # HTTP/1.0 / Connection: close after parsing headers but before the
        # response body is consumed. A direct recv_into wrapper does not.
        self._raw = sock.makefile("rb", buffering=0)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        self._sock.settimeout(_time_remaining(self._deadline))
        return self._raw.readinto(buffer)

    def close(self) -> None:
        try:
            self._raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    """Limited socket surface used by http.client, including its buffered parser."""

    def __init__(self, sock, deadline: float) -> None:
        self._sock = sock
        self._deadline = deadline

    def sendall(self, data) -> None:
        self._sock.settimeout(_time_remaining(self._deadline))
        self._sock.sendall(data)

    def makefile(self, mode: str):
        if mode != "rb":
            raise ValueError("only the HTTP response reader is supported")
        return io.BufferedReader(_DeadlineReader(self._sock, self._deadline))

    def close(self) -> None:
        self._sock.close()


class HTTPConnection(_HTTPConnection):
    """HTTPConnection with one wall-clock limit across connect, headers, body."""

    def __init__(self, host: str, port: int, *, timeout: int) -> None:
        super().__init__(host, port, timeout=timeout)
        self._deadline = time.monotonic() + timeout

    def connect(self) -> None:
        self.timeout = _time_remaining(self._deadline)
        super().connect()
        assert self.sock is not None
        self.sock = _DeadlineSocket(self.sock, self._deadline)


@dataclass(frozen=True, slots=True)
class AdvisoryResult:
    endpoint: str
    model_id: str
    prompt_sha256: str
    response_sha256: str
    text: str
    finish_reason: str | None
    status: str = "UNVERIFIED_MODEL_OUTPUT"
    authority: str = "NONE"
    memory_admission: str = "NONE"
    tool_execution: str = "NONE"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _endpoint_address(endpoint: str) -> tuple[str, int, str]:
    if type(endpoint) is not str:
        raise LocalModelError("endpoint must be an explicit loopback URL")
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise LocalModelError("invalid loopback endpoint") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"/v1", "/v1/"}
    ):
        raise LocalModelError("only an exact HTTP loopback /v1 endpoint is permitted")
    expected_netloc = (
        f"[::1]:{port}" if parsed.hostname == "::1" else f"127.0.0.1:{port}"
    )
    canonical = f"http://{expected_netloc}/v1"
    if parsed.netloc != expected_netloc or endpoint not in {canonical, canonical + "/"}:
        raise LocalModelError("noncanonical loopback endpoint")
    return parsed.hostname, port, canonical


def _model_id(value: str) -> str:
    if type(value) is not str or _MODEL_ID.fullmatch(value) is None:
        raise LocalModelError("model id must be a bounded explicit model alias")
    return value


def _authorization_header(api_key_env: str | None) -> dict[str, str]:
    if api_key_env is None:
        return {}
    if type(api_key_env) is not str or _ENV_NAME.fullmatch(api_key_env) is None:
        raise LocalModelError("invalid API-key environment variable name")
    key = os.environ.get(api_key_env)
    if not key or not key.isascii() or any(not 33 <= ord(char) <= 126 for char in key):
        raise LocalModelError("configured local API key unavailable or invalid")
    return {"Authorization": f"Bearer {key}"}


def advise_local_model(
    prompt: str,
    *,
    endpoint: str,
    model_id: str,
    api_key_env: str | None = None,
    max_tokens: int = 180,
    timeout_seconds: int = 60,
) -> AdvisoryResult:
    """Request one read-only advisory completion without disclosing Vera state."""
    host, port, canonical_endpoint = _endpoint_address(endpoint)
    model_id = _model_id(model_id)
    if type(prompt) is not str or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise LocalModelError("prompt must be nonempty and within the size limit")
    if type(max_tokens) is not int or not 1 <= max_tokens <= 512:
        raise LocalModelError("max_tokens must be within 1..512")
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
        raise LocalModelError("timeout_seconds must be within 1..300")
    authorization = _authorization_header(api_key_env)

    request = {
        "model": model_id,
        "stream": False,
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an unverified local advisory model, not Vera's "
                    "identity or a source of authority. State uncertainty. "
                    "No tools, memory changes, repository writes, or external "
                    "actions are available in this interaction."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    encoded = json.dumps(request, ensure_ascii=False, allow_nan=False).encode("utf-8")
    headers = {"Content-Type": "application/json", **authorization}

    # http.client uses the numeric loopback address directly: no DNS, proxy,
    # redirect following, browser-origin bridge, or model-supplied tool call.
    connection = HTTPConnection(host, port, timeout=timeout_seconds)
    response = None
    try:
        connection.request("POST", "/v1/chat/completions", body=encoded, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise LocalModelError(f"local inference HTTP status {response.status}")
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, HTTPException) as exc:
        raise LocalModelError("local inference endpoint unavailable") from exc
    finally:
        try:
            if response is not None:
                response.close()
        finally:
            connection.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise LocalModelError("local inference response exceeds size limit")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise LocalModelError("local inference response is not valid JSON") from exc
    if not isinstance(body, dict):
        raise LocalModelError("local inference response must be an object")
    if body.get("model") != model_id:
        raise LocalModelError("local inference did not confirm the exact model id")
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise LocalModelError("local inference must return exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise LocalModelError("local inference message is malformed")
    message = choice["message"]
    if (
        message.get("role") != "assistant"
        or message.get("tool_calls") is not None
        or message.get("function_call") is not None
    ):
        raise LocalModelError("local inference attempted unsupported tool behavior")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LocalModelError("local inference returned no advisory text")
    # Untrusted model text is printed to a terminal in the human-readable CLI.
    # Forbid terminal controls and directional formatting controls that can
    # visually reorder the answer, without banning benign shaping characters
    # such as U+200D (zero-width joiner).
    if any(
        (ord(char) < 32 and char not in "\n\t")
        or ord(char) == 127
        or 128 <= ord(char) <= 159
        or ord(char) in {0x061C, 0x200E, 0x200F}
        or 0x202A <= ord(char) <= 0x202E
        or 0x2066 <= ord(char) <= 0x206F
        for char in content
    ):
        raise LocalModelError("local inference returned terminal or directional control characters")
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and finish_reason not in {"stop", "length"}:
        raise LocalModelError("local inference finish reason is unsupported")
    return AdvisoryResult(
        endpoint=canonical_endpoint,
        model_id=model_id,
        prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
        response_sha256=sha256(content.strip().encode("utf-8")).hexdigest(),
        text=content.strip(),
        finish_reason=finish_reason,
    )
