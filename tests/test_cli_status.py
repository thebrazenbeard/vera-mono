import json

import pytest

from vera_core import VeraStateDirectory
from vera_core.cli import main
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"


def accepted_state(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    lifecycle = state.open()
    admitted = lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m1",
            text="CLI status state",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op1",
            project_id=PROJECT,
            governed_identity_id=IDENTITY,
        ),
        expected_head=lifecycle.memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-cli",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def test_status_cli_reconstructs_exact_existing_state(tmp_path, capsys):
    state = accepted_state(tmp_path)

    result = main(
        [
            "status",
            "--state-root",
            str(state.paths.root),
            "--project-id",
            PROJECT,
            "--identity-id",
            IDENTITY,
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "VERA_MONO_CLI_STATUS_V1"
    assert payload["project_id"] == PROJECT
    assert payload["identity_id"] == IDENTITY
    assert payload["runtime_context"]["status"] == "ACCEPTED_CURRENT"
    assert payload["runtime_context"]["accepted_runtime_id"] == "runtime-cli"
    assert payload["claim_ceiling"].endswith(
        "NOT_PROTECTED_EFFECT_AUTHORITY"
    )


def test_status_cli_refuses_to_guess_or_create_missing_state_root(
    tmp_path,
    capsys,
):
    missing = tmp_path / "missing"

    with pytest.raises(SystemExit) as exc:
        main(
            [
                "status",
                "--state-root",
                str(missing),
                "--project-id",
                PROJECT,
                "--identity-id",
                IDENTITY,
            ]
        )

    assert exc.value.code == 2
    assert not missing.exists()
    assert "existing state-root directory" in capsys.readouterr().err
