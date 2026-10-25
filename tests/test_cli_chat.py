"""The opt-in local chat path binds only minimal QVR state to an effectless model."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from vera_core import VeraStateDirectory
from vera_core import cli
from vera_memory import AdmissionRequest, MemoryClass


class _Response:
    status = 200

    def __init__(self, message=None):
        self._body = json.dumps({
            "model": "gemma3:1b",
            "choices": [{
                "message": message or {"role": "assistant", "content": "An unverified reply."},
                "finish_reason": "stop",
            }],
        }).encode("utf-8")

    def read(self, limit):
        return self._body[:limit]


class _Connection:
    def __init__(self, response=None, fail=None):
        self.response = response or _Response()
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


def _args(root, *extra):
    return [
        "chat", "What can I inspect?", "--state-root", str(root),
        "--project-id", "private-project-CANARY",
        "--identity-id", "private-identity-CANARY",
        "--endpoint", "http://127.0.0.1:11434/v1",
        "--model", "gemma3:1b", *extra,
    ]


def test_chat_binds_only_minimal_qvr_metadata_and_cold_restart_has_no_memory_admission(
    tmp_path, capsys,
):
    root = tmp_path / "private-state-path-CANARY"
    root.mkdir()
    state = VeraStateDirectory(
        root, project_id="private-project-CANARY", identity_id="private-identity-CANARY",
    )
    initial_memory_head = state.open().memory.current_head
    requests = []

    for _ in range(2):
        connection = _Connection()
        with patch("vera_core.local_model_advisory.HTTPConnection", return_value=connection):
            assert cli.main(_args(root, "--json")) == 0
        emitted = json.loads(capsys.readouterr().out)
        assert emitted["schema"] == "VERA_MONO_LOCAL_CHAT_RESULT_V1"
        assert emitted["context"]["status"] == "EMPTY"
        assert emitted["context"]["accepted_runtime_id_sha256"] is None
        assert emitted["result"]["memory_admission"] == "NONE"
        assert emitted["result"]["authority"] == "NONE"
        assert emitted["result"]["tool_execution"] == "NONE"
        assert emitted["result"]["status"] == "UNVERIFIED_MODEL_OUTPUT"
        assert state.open().memory.current_head == initial_memory_head
        assert len(connection.requests) == 1
        method, path, request, headers = connection.requests[0]
        assert (method, path) == ("POST", "/v1/chat/completions")
        assert headers == {"Content-Type": "application/json"}
        assert "tools" not in request and "tool_choice" not in request
        bound_prompt = request["messages"][1]["content"]
        assert "Locally reconstructed Vera lifecycle status (unverified; not authority)" in bound_prompt
        assert '"status":"EMPTY"' in bound_prompt
        assert "What can I inspect?" in bound_prompt
        assert "CANARY" not in bound_prompt
        assert "private-state-path" not in bound_prompt
        assert "CANARY" not in json.dumps(emitted)
        requests.append(request)

    assert requests[0] == requests[1]
    assert not state.paths.trust.exists()


def test_chat_rejects_incomplete_or_missing_state_before_network(tmp_path, capsys):
    root = tmp_path / "missing"
    with patch("vera_core.local_model_advisory.HTTPConnection") as ctor:
        with pytest.raises(SystemExit) as exc:
            cli.main(_args(root))
    assert exc.value.code == 2
    assert "existing state-root" in capsys.readouterr().err
    ctor.assert_not_called()

    root.mkdir()
    with patch("vera_core.local_model_advisory.HTTPConnection") as ctor:
        with pytest.raises(SystemExit) as exc:
            cli.main(["chat", "Hello", "--state-root", str(root),
                      "--endpoint", "http://127.0.0.1:11434/v1", "--model", "gemma3:1b"])
    assert exc.value.code == 2
    assert "required" in capsys.readouterr().err
    ctor.assert_not_called()


def test_chat_rejects_nonloopback_and_unavailable_endpoint(tmp_path, capsys):
    root = tmp_path / "state"
    root.mkdir()
    args = _args(root)
    args[args.index("http://127.0.0.1:11434/v1")] = "http://192.168.1.71:11434/v1"
    with patch("vera_core.local_model_advisory.HTTPConnection") as ctor:
        with pytest.raises(SystemExit) as exc:
            cli.main(args)
    assert exc.value.code == 2
    assert "loopback" in capsys.readouterr().err
    ctor.assert_not_called()

    with patch("vera_core.local_model_advisory.HTTPConnection", return_value=_Connection(fail=OSError("offline"))):
        with pytest.raises(SystemExit) as exc:
            cli.main(_args(root))
    assert exc.value.code == 2
    assert "endpoint unavailable" in capsys.readouterr().err


def test_chat_never_executes_model_tool_calls(tmp_path, capsys):
    root = tmp_path / "state"
    root.mkdir()
    tool_reply = _Response({
        "role": "assistant", "content": "I will run it",
        "tool_calls": [{"id": "call-1", "type": "function", "function": {
            "name": "run_shell", "arguments": '{"command":"echo action"}',
        }}],
    })
    connection = _Connection(tool_reply)
    with patch("vera_core.local_model_advisory.HTTPConnection", return_value=connection):
        with pytest.raises(SystemExit) as exc:
            cli.main(_args(root))
    assert exc.value.code == 2
    assert "unsupported tool behavior" in capsys.readouterr().err
    assert connection.closed


def test_chat_context_digest_is_stable_and_model_prompt_is_hashed(tmp_path, capsys):
    root = tmp_path / "state"
    root.mkdir()
    connection = _Connection()
    with patch("vera_core.local_model_advisory.HTTPConnection", return_value=connection):
        assert cli.main(_args(root, "--json")) == 0
    payload = json.loads(capsys.readouterr().out)
    context = json.dumps(payload["context"], ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(",", ":"))
    assert payload["context_sha256"] == sha256(context.encode("utf-8")).hexdigest()
    prompt = connection.requests[0][2]["messages"][1]["content"]
    assert payload["result"]["prompt_sha256"] == sha256(prompt.encode("utf-8")).hexdigest()


def test_accepted_state_does_not_leak_memory_commitments_or_runtime_id(tmp_path, capsys):
    root = tmp_path / "accepted-state"
    root.mkdir()
    state = VeraStateDirectory(root, project_id="private-project-CANARY",
                               identity_id="private-identity-CANARY")
    lifecycle = state.open()
    admitted = lifecycle.memory.admit(AdmissionRequest(
        record_id="m1", text="MEMORY_SECRET_CANARY",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test", authority_ref="authority:test",
        privacy_ref="privacy:test", provenance_refs=("source:test",),
        operation_id="op1", project_id=state.project_id,
        governed_identity_id=state.identity_id,
    ), expected_head=lifecycle.memory.current_head)
    lifecycle.checkpoint(
        checkpoint_id="cp1", runtime_id="RUNTIME_SECRET_CANARY",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
        commitments=("COMMITMENT_SECRET_CANARY",),
        unfinished_work=("WORK_SECRET_CANARY",),
    )
    head = lifecycle.memory.current_head
    connection = _Connection()
    with patch("vera_core.local_model_advisory.HTTPConnection", return_value=connection):
        assert cli.main(_args(root, "--json")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["context"]["status"] == "ACCEPTED_CURRENT"
    assert result["context"]["accepted_runtime_id_sha256"] == sha256(
        b"RUNTIME_SECRET_CANARY"
    ).hexdigest()
    sent = json.dumps(connection.requests[0][2])
    for forbidden in ("MEMORY_SECRET_CANARY", "COMMITMENT_SECRET_CANARY",
                      "WORK_SECRET_CANARY", "RUNTIME_SECRET_CANARY"):
        assert forbidden not in sent
        assert forbidden not in json.dumps(result)
    assert state.open().memory.current_head == head


def test_cold_process_restart_reopens_same_minimal_state(tmp_path):
    root = tmp_path / "persistent-state"
    root.mkdir()
    script = """
import json, sys
from unittest.mock import patch
from vera_core import cli
from vera_core.local_model_advisory import AdvisoryResult
prompt = 'stub-model-output'
result = AdvisoryResult(endpoint='http://127.0.0.1:11434/v1', model_id='gemma3:1b',
    prompt_sha256='0' * 64, response_sha256='1' * 64, text=prompt,
    finish_reason='stop')
with patch('vera_core.cli.advise_local_model', return_value=result):
    sys.exit(cli.main(json.loads(sys.argv[1])))
"""
    env = dict(os.environ)
    # The test process's package roots are inherited by fresh Python processes.
    env["PYTHONPATH"] = os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)
    snapshots = []
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, "-c", script, json.dumps(_args(root, "--json"))],
            env=env, text=True, capture_output=True, check=True,
        )
        snapshots.append(json.loads(completed.stdout))
    assert snapshots[0] == snapshots[1]
    assert snapshots[0]["context"]["status"] == "EMPTY"
    assert snapshots[0]["result"]["memory_admission"] == "NONE"
