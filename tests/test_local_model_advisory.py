"""Source-bound tests for a deliberately effectless local model advisory route."""

from __future__ import annotations

from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket
import threading
import time
from unittest.mock import patch

import pytest

from vera_core import cli
from vera_core.local_model_advisory import LocalModelError, advise_local_model


class _Response:
    def __init__(self, body, status=200):
        self.status = status
        self._raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.closed = False

    def read(self, count):
        return self._raw[:count]

    def close(self):
        self.closed = True


class _Connection:
    def __init__(self, response=None, fail=None):
        self.response = response or _Response(_valid_response())
        self.fail = fail
        self.requests = []
        self.closed = False

    def request(self, method, path, body, headers):
        if self.fail:
            raise self.fail
        self.requests.append((method, path, json.loads(body), headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def _valid_response():
    return {
        "model": "gemma3:1b",
        "choices": [
            {"message": {"role": "assistant", "content": "Careful answer."},
             "finish_reason": "stop"}
        ],
    }


def _advise_with(connection, *, endpoint="http://127.0.0.1:11434/v1", **kwargs):
    with patch("vera_core.local_model_advisory.HTTPConnection", return_value=connection) as ctor:
        result = advise_local_model(
            "Consider two explanations", endpoint=endpoint, model_id="gemma3:1b", **kwargs
        )
    return result, ctor


@pytest.mark.parametrize("invalid_text", ["\ud800", "\udfff"])
def test_invalid_unicode_prompt_fails_before_network(invalid_text):
    with patch("vera_core.local_model_advisory.HTTPConnection") as constructor:
        with pytest.raises(LocalModelError, match="valid Unicode"):
            advise_local_model(
                invalid_text,
                endpoint="http://127.0.0.1:11434/v1",
                model_id="gemma3:1b",
            )
    constructor.assert_not_called()


@pytest.mark.parametrize("invalid_text", ["\ud800", "\udfff"])
def test_invalid_unicode_model_text_fails_closed(invalid_text):
    response = _valid_response()
    response["choices"][0]["message"]["content"] = invalid_text
    connection = _Connection(response=_Response(response))
    with pytest.raises(LocalModelError, match="valid Unicode"):
        _advise_with(connection)
    assert connection.closed is True


def test_real_request_contract_is_explicit_loopback_cognition_only():
    conn = _Connection()
    result, constructor = _advise_with(conn)
    constructor.assert_called_once_with("127.0.0.1", 11434, timeout=60)
    method, path, body, headers = conn.requests[0]
    assert (method, path) == ("POST", "/v1/chat/completions")
    assert headers == {"Content-Type": "application/json"}
    assert body["model"] == "gemma3:1b"
    assert body["stream"] is False
    assert "tools" not in body
    assert "tool_choice" not in body
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["messages"][1] == {"role": "user", "content": "Consider two explanations"}
    assert conn.closed is True
    assert result.status == "UNVERIFIED_MODEL_OUTPUT"
    assert result.authority == result.memory_admission == result.tool_execution == "NONE"
    assert result.prompt_sha256 == sha256(b"Consider two explanations").hexdigest()
    assert result.response_sha256 == sha256(b"Careful answer.").hexdigest()
    assert result.text == "Careful answer."


def test_ipv6_loopback_is_allowed_without_name_resolution():
    result, constructor = _advise_with(_Connection(), endpoint="http://[::1]:8097/v1")
    constructor.assert_called_once_with("::1", 8097, timeout=60)
    assert result.endpoint == "http://[::1]:8097/v1"


@pytest.mark.parametrize("endpoint", [
    "http://localhost:11434/v1",
    "http://192.168.1.71:11434/v1",
    "http://127.0.0.2:11434/v1",
    "http://0.0.0.0:11434/v1",
    "https://127.0.0.1:11434/v1",
    "http://127.0.0.1/v1",
    "http://127.0.0.1:99999/v1",
    "http://user@127.0.0.1:11434/v1",
    "http://127.0.0.1:11434/v1?redirect=1",
    "http://127.0.0.1:11434/v1#fragment",
    "http://127.0.0.1:11434/v1/chat/completions",
    "http://127.0.0.1:011434/v1",
    " http://127.0.0.1:11434/v1",
])
def test_noncanonical_or_nonloopback_urls_cannot_open_a_connection(endpoint):
    with patch("vera_core.local_model_advisory.HTTPConnection") as constructor:
        with pytest.raises(LocalModelError):
            advise_local_model("test", endpoint=endpoint, model_id="gemma3:1b")
    constructor.assert_not_called()


@pytest.mark.parametrize("values", [
    {"prompt": ""},
    {"prompt": "x" * 12001},
    {"model_id": "name with whitespace"},
    {"model_id": ""},
    {"max_tokens": 0},
    {"max_tokens": 513},
    {"timeout_seconds": 0},
    {"timeout_seconds": 301},
])
def test_invalid_requests_fail_before_network_access(values):
    args = {"prompt": "test", "endpoint": "http://127.0.0.1:11434/v1", "model_id": "gemma3:1b"}
    args.update(values)
    with patch("vera_core.local_model_advisory.HTTPConnection") as constructor:
        with pytest.raises(LocalModelError):
            advise_local_model(**args)
    constructor.assert_not_called()


@pytest.mark.parametrize("finish_reason", [["stop"], {"reason": "stop"}])
def test_malformed_finish_reason_fails_as_local_model_error(finish_reason):
    response = _valid_response()
    response["choices"][0]["finish_reason"] = finish_reason
    connection = _Connection(_Response(response))
    with pytest.raises(LocalModelError, match="finish reason is unsupported"):
        _advise_with(connection)
    assert connection.closed is True


@pytest.mark.parametrize("response", [
    _Response({}, status=302),
    _Response({}, status=500),
    _Response(b"not-json"),
    _Response(b" " * 1_000_001),
    _Response({"choices": _valid_response()["choices"]}),
    _Response({"model": "other:1b", "choices": _valid_response()["choices"]}),
    _Response({"model": "gemma3:1b", "choices": []}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [{"type": "function"}]}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "answer", "tool_calls": []}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "answer", "function_call": {"name": "shell"}}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "\u001b]52;clipboard-injection"}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "\u009b31mcolor"}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "left\u202eright"}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "left\u2066right\u2069"}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "left\u200fright"}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "left\u061cright"}}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "answer"}, "finish_reason": "tool_calls"}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "answer"}, "finish_reason": "function_call"}]}),
    _Response({"model": "gemma3:1b", "choices": [{"message": {"role": "tool", "content": "answer"}}]}),
])
def test_untrusted_or_effectful_response_is_rejected(response):
    conn = _Connection(response=response)
    with pytest.raises(LocalModelError):
        _advise_with(conn)
    assert conn.closed is True


def test_transport_failure_is_bounded_and_connection_closes():
    conn = _Connection(fail=OSError("unreachable"))
    with pytest.raises(LocalModelError, match="unavailable"):
        _advise_with(conn)
    assert conn.closed is True


def test_non_success_http_response_is_explicitly_closed():
    response = _Response({}, status=500)
    conn = _Connection(response=response)
    with pytest.raises(LocalModelError, match="HTTP status 500"):
        _advise_with(conn)
    assert conn.closed is True
    assert response.closed is True


@pytest.mark.parametrize("drip_section", ["body", "headers"])
def test_loopback_slow_drip_cannot_extend_whole_request_deadline(drip_section):
    """The same deadline must cover buffered headers and chunked bodies."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    body = json.dumps(_valid_response()).encode("utf-8")
    if drip_section == "body":
        prefix = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
        pieces = [f"{len(part):x}\r\n".encode() + part + b"\r\n"
                  for part in (body[i:i + 6] for i in range(0, len(body), 6))]
        suffix = b"0\r\n\r\n"
    else:
        prefix = b"HTTP/1.1 200 OK\r\n"
        pieces = [f"X-Slow-{i}: value\r\n".encode() for i in range(22)]
        suffix = f"Content-Length: {len(body)}\r\n\r\n".encode() + body
    finished = threading.Event()

    def serve():
        try:
            with listener:
                peer, _ = listener.accept()
                with peer:
                    peer.settimeout(2)
                    peer.recv(4096)
                    peer.sendall(prefix)
                    for piece in pieces:
                        try:
                            peer.sendall(piece)
                        except OSError:
                            break
                        time.sleep(0.09)
                    try:
                        peer.sendall(suffix)
                    except OSError:
                        pass
        finally:
            finished.set()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(LocalModelError, match="unavailable"):
            advise_local_model(
                "test", endpoint=f"http://127.0.0.1:{port}/v1",
                model_id="gemma3:1b", timeout_seconds=1,
            )
        assert time.monotonic() - started < 1.5
    finally:
        listener.close()
        assert finished.wait(timeout=4)


@pytest.mark.parametrize("protocol, explicit_close", [
    ("HTTP/1.0", False),
    ("HTTP/1.1", True),
])
def test_loopback_complete_http_response_still_returns_advisory(protocol, explicit_close):
    payload = json.dumps(_valid_response()).encode("utf-8")
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = protocol

        def do_POST(self):
            # Consume the *entire* request before closing. A one-shot recv()
            # leaves body bytes unread and can cause Windows TCP RST (10054).
            length = int(self.headers["Content-Length"])
            requests.append((self.path, self.rfile.read(length)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            if explicit_close:
                self.send_header("Connection", "close")
            self.end_headers()
            # Force the close-connection path to parse headers before body
            # bytes arrive, exposing premature underlying socket closure.
            self.wfile.flush()
            time.sleep(0.05)
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 3
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        result = advise_local_model(
            "test", endpoint=f"http://127.0.0.1:{server.server_port}/v1",
            model_id="gemma3:1b", timeout_seconds=1,
        )
        assert result.text == "Careful answer."
        assert result.status == "UNVERIFIED_MODEL_OUTPUT"
    finally:
        thread.join(timeout=4)
        server.server_close()
        assert not thread.is_alive()
    assert requests[0][0] == "/v1/chat/completions"
    assert json.loads(requests[0][1])["model"] == "gemma3:1b"


def test_multiline_plain_text_is_allowed_without_terminal_controls():
    payload = {"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "line one\n\tline two"}}]}
    result, _ = _advise_with(_Connection(response=_Response(payload)))
    assert result.text == "line one\n\tline two"


def test_ordinary_zero_width_joiner_remains_allowed():
    payload = {"model": "gemma3:1b", "choices": [{"message": {"role": "assistant", "content": "\U0001f469\u200d\U0001f4bb developer"}}]}
    result, _ = _advise_with(_Connection(response=_Response(payload)))
    assert result.text == "\U0001f469\u200d\U0001f4bb developer"


def test_optional_api_key_stays_in_request_header_not_receipt(monkeypatch):
    monkeypatch.setenv("LOCAL_TEST_MODEL_KEY", "the-secret-value")
    conn = _Connection()
    result, _ = _advise_with(conn, api_key_env="LOCAL_TEST_MODEL_KEY")
    assert conn.requests[0][3]["Authorization"] == "Bearer the-secret-value"
    assert "the-secret-value" not in json.dumps(result.to_dict())


def test_missing_api_key_fails_closed_before_transport(monkeypatch):
    monkeypatch.delenv("LOCAL_TEST_MODEL_KEY", raising=False)
    with patch("vera_core.local_model_advisory.HTTPConnection") as constructor:
        with pytest.raises(LocalModelError, match="key unavailable"):
            advise_local_model("test", endpoint="http://127.0.0.1:11434/v1", model_id="gemma3:1b", api_key_env="LOCAL_TEST_MODEL_KEY")
    constructor.assert_not_called()


def test_non_ascii_api_key_cannot_enter_an_http_header(monkeypatch):
    monkeypatch.setenv("LOCAL_TEST_MODEL_KEY", "bad-\u2603-key")
    with patch("vera_core.local_model_advisory.HTTPConnection") as constructor:
        with pytest.raises(LocalModelError, match="key unavailable"):
            advise_local_model("test", endpoint="http://127.0.0.1:11434/v1", model_id="gemma3:1b", api_key_env="LOCAL_TEST_MODEL_KEY")
    constructor.assert_not_called()


def test_cli_advice_is_explicit_and_does_not_read_vera_state(monkeypatch, capsys):
    def no_state(*_args, **_kwargs):
        raise AssertionError("advisory route must not read governed state")
    monkeypatch.setattr(cli, "_bound_state", no_state)
    monkeypatch.setattr(cli, "advise_local_model", lambda *_args, **_kwargs:
        _advise_with(_Connection())[0])
    assert cli.main(["advise", "hello", "--endpoint", "http://127.0.0.1:11434/v1", "--model", "gemma3:1b"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("UNVERIFIED_MODEL_OUTPUT")
    assert "Careful answer." in output
    assert cli.main(["advise", "hello", "--endpoint", "http://127.0.0.1:11434/v1", "--model", "gemma3:1b", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "UNVERIFIED_MODEL_OUTPUT"
    assert payload["memory_admission"] == "NONE"
