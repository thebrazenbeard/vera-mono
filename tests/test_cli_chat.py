"""The opt-in local chat path binds only minimal QVR state to an effectless model."""

from __future__ import annotations

from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from vera_core import VeraStateDirectory
from vera_core import cli
from vera_core.local_model_advisory import MAX_PROMPT_CHARS
from vera_control import local_r10_source_digest
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


def _interactive_args(root, *extra):
    args = _args(root, "--interactive", "--json", *extra)
    args.remove("What can I inspect?")
    return args


def test_interactive_chat_uses_stdin_without_history_memory_or_authority(
    tmp_path, capsys,
):
    root = tmp_path / "private-state-path-CANARY"
    root.mkdir()
    state = VeraStateDirectory(root, project_id="private-project-CANARY",
                               identity_id="private-identity-CANARY")
    memory_head = state.open().memory.current_head
    connections = [_Connection(), _Connection()]
    with patch.object(sys, "stdin", io.StringIO("First question\nSecond question\n:exit\n")), \
            patch("vera_core.local_model_advisory.HTTPConnection", side_effect=connections):
        assert cli.main(_interactive_args(root)) == 0

    output = capsys.readouterr()
    assert "UNVERIFIED_MODEL_OUTPUT: stateless local chat" in output.err
    records = [json.loads(line) for line in output.out.splitlines()]
    assert len(records) == 2
    assert all(record["claim_ceiling"] ==
               "UNVERIFIED_MODEL_OUTPUT_NOT_CURRENTNESS_NOT_EFFECT_AUTHORITY"
               for record in records)
    assert all(record["result"]["tool_execution"] == "NONE" and
               record["result"]["memory_admission"] == "NONE" and
               record["result"]["authority"] == "NONE" for record in records)
    prompts = [connection.requests[0][2]["messages"][1]["content"]
               for connection in connections]
    assert "First question" in prompts[0]
    assert "Second question" not in prompts[0]
    assert "Second question" in prompts[1]
    assert "First question" not in prompts[1]
    assert all("CANARY" not in prompt for prompt in prompts)
    assert "CANARY" not in output.out
    assert "First question" not in output.out + output.err
    assert "Second question" not in output.out + output.err
    assert state.open().memory.current_head == memory_head


def test_interactive_chat_eof_and_interrupt_before_prompt_send_nothing(tmp_path, capsys):
    root = tmp_path / "state"
    root.mkdir()
    with patch("vera_core.local_model_advisory.HTTPConnection") as ctor, \
            patch.object(sys, "stdin", io.StringIO("")):
        assert cli.main(_interactive_args(root)) == 0
    ctor.assert_not_called()
    assert capsys.readouterr().out == ""

    class InterruptingStdin:
        def isatty(self):
            return False

        def readline(self, limit):
            raise KeyboardInterrupt

    with patch("vera_core.local_model_advisory.HTTPConnection") as ctor, \
            patch.object(sys, "stdin", InterruptingStdin()):
        assert cli.main(_interactive_args(root)) == 0
    ctor.assert_not_called()
    assert capsys.readouterr().out == ""


def test_interactive_chat_rejects_arg_prompt_and_oversize_before_network(
    tmp_path, capsys,
):
    root = tmp_path / "state"
    root.mkdir()
    args = _interactive_args(root)
    args.insert(1, "SECRET_POSITIONAL_PROMPT")
    with patch("vera_core.local_model_advisory.HTTPConnection") as ctor:
        with pytest.raises(SystemExit) as exc:
            cli.main(args)
    assert exc.value.code == 2
    assert "forbids a positional prompt" in capsys.readouterr().err
    ctor.assert_not_called()

    oversized = "x" * (MAX_PROMPT_CHARS + 2) + "\n"
    with patch.object(sys, "stdin", io.StringIO(oversized)), \
            patch("vera_core.local_model_advisory.HTTPConnection") as ctor:
        with pytest.raises(SystemExit) as exc:
            cli.main(_interactive_args(root))
    assert exc.value.code == 2
    assert "prompt exceeds" in capsys.readouterr().err
    ctor.assert_not_called()

    with patch("vera_core.local_model_advisory.HTTPConnection") as ctor:
        with pytest.raises(SystemExit) as exc:
            cli.main([value for value in _interactive_args(root)
                      if value != "--interactive"])
    assert exc.value.code == 2
    assert "requires a prompt" in capsys.readouterr().err
    ctor.assert_not_called()


def test_interactive_chat_fails_closed_when_second_model_call_fails(tmp_path, capsys):
    root = tmp_path / "state"
    root.mkdir()
    connections = [_Connection(), _Connection(fail=OSError("offline"))]
    with patch.object(sys, "stdin", io.StringIO("First\nSecond\nThird\n")), \
            patch("vera_core.local_model_advisory.HTTPConnection", side_effect=connections) as ctor:
        with pytest.raises(SystemExit) as exc:
            cli.main(_interactive_args(root))
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "endpoint unavailable" in output.err
    assert len(output.out.splitlines()) == 1
    assert ctor.call_count == 2  # The third prompt was not sent or retried.


def test_interactive_chat_interrupt_during_model_call_is_not_success(tmp_path, capsys):
    root = tmp_path / "state"
    root.mkdir()
    with patch.object(sys, "stdin", io.StringIO("First\n")), \
            patch("vera_core.cli.advise_local_model", side_effect=KeyboardInterrupt):
        assert cli.main(_interactive_args(root)) == 130
    output = capsys.readouterr()
    assert "request delivery is unknown" in output.err
    assert output.out == ""


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
        assert set(emitted["context"]) == {"schema", "status"}
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
    assert set(result["context"]) == {"schema", "status"}
    sent = json.dumps(connection.requests[0][2])
    for forbidden in ("MEMORY_SECRET_CANARY", "COMMITMENT_SECRET_CANARY",
                      "WORK_SECRET_CANARY", "RUNTIME_SECRET_CANARY"):
        assert forbidden not in sent
        assert forbidden not in json.dumps(result)
    assert state.open().memory.current_head == head


def test_chat_reconciles_existing_durable_currentness_without_admitting_new_memory(
    tmp_path, capsys,
):
    """An interrupted final journal append can be repaired by QVR reconstruction."""
    root = tmp_path / "interrupted-state"
    root.mkdir()
    state = VeraStateDirectory(root, project_id="private-project-CANARY",
                               identity_id="private-identity-CANARY")
    lifecycle = state.open()
    admitted = lifecycle.memory.admit(AdmissionRequest(
        record_id="m1", text="RECOVERY_MEMORY_CANARY",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test", authority_ref="authority:test",
        privacy_ref="privacy:test", provenance_refs=("source:test",),
        operation_id="op1", project_id=state.project_id,
        governed_identity_id=state.identity_id,
    ), expected_head=lifecycle.memory.current_head)
    checkpoint = lifecycle.checkpoints.append(
        checkpoint_id="cp1", runtime_id="RUNTIME_SECRET_CANARY",
        memory_head_digest=admitted["store_head"],
        control_source_digest=local_r10_source_digest(),
        expected_head=lifecycle.checkpoints.current_head,
    )
    currentness_payload = {
        "project_id": state.project_id,
        "identity_id": state.identity_id,
        "runtime_id": checkpoint.runtime_id,
        "memory_head_digest": checkpoint.memory_head_digest,
        "recovery_checkpoint_digest": checkpoint.checkpoint_digest,
        "recovery_checkpoint_generation": checkpoint.generation,
        "control_source_digest": checkpoint.control_source_digest,
    }
    lifecycle.currentness.publish("vera-runtime", currentness_payload,
                                  expected_generation=None)
    original_head = lifecycle.memory.current_head
    assert not lifecycle.journal.has_event("cp1", "CURRENTNESS_COMMITTED")

    connection = _Connection()
    with patch("vera_core.local_model_advisory.HTTPConnection", return_value=connection):
        assert cli.main(_args(root, "--json")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["context"] == {
        "schema": "VERA_MONO_LOCAL_CHAT_CONTEXT_V1",
        "status": "ACCEPTED_RECONCILED",
    }
    assert lifecycle.journal.has_event("cp1", "RESTART_RECONCILED_COMMITTED")
    reconciled_journal_head = lifecycle.journal.head
    assert state.open().memory.current_head == original_head
    assert "CANARY" not in json.dumps(connection.requests)
    assert "CANARY" not in json.dumps(result)

    # A subsequent reconstruction sees the committed recovery event, not a
    # second journal append or model-driven memory admission.
    with patch("vera_core.local_model_advisory.HTTPConnection", return_value=_Connection()):
        assert cli.main(_args(root, "--json")) == 0
    restarted = json.loads(capsys.readouterr().out)
    assert restarted["context"]["status"] == "ACCEPTED_CURRENT"
    assert lifecycle.journal.head == reconciled_journal_head
    assert state.open().memory.current_head == original_head


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
