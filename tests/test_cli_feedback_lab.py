"""CLI-level synthetic correction, heldout, approval and rollback probes."""

from __future__ import annotations

import json

import pytest

from vera_core import cli


def fixture():
    return {
        "schema": "VERA_MONO_SYNTHETIC_FEEDBACK_LAB_V1",
        "synthetic": True,
        "samples": [{
            "sample_id": "s1", "source_id": "training-fixture",
            "cue": "color of a ripe banana", "answer": "yellow",
            "consent_ref": "synthetic-opt-in",
            "privacy_review_ref": "synthetic-privacy-review",
            "provenance_ref": "synthetic-provenance",
        }],
        "holdout": [{
            "case_id": "h1", "source_id": "heldout-fixture",
            "cue": "color of a ripe banana", "expected": "yellow",
        }],
    }


def invoke(tmp_path, capsys, payload=None, *args):
    path = tmp_path / "synthetic.json"
    path.write_text(json.dumps(fixture() if payload is None else payload), encoding="utf-8")
    status = cli.main(["feedback-lab", "--fixture", str(path), *args])
    return status, json.loads(capsys.readouterr().out)


def test_candidate_holdout_requires_explicit_approval(tmp_path, capsys):
    result, body = invoke(tmp_path, capsys)
    assert result == 0
    assert body["candidate_qualified"] is True
    assert body["baseline_passes"] == 0
    assert body["candidate_passes"] == 1
    assert body["active_candidate"] is False
    assert body["correction_active"] is False
    assert body["memory_admission"] == "NONE"


def test_approval_activates_session_only_and_explicit_rollback_reverts(tmp_path, capsys):
    result, body = invoke(tmp_path, capsys, None, "--approval-ref", "operator-ack:synthetic")
    assert result == 0
    assert body["candidate_qualified"] is True
    assert body["active_candidate"] is True
    assert body["correction_active"] is True
    assert body["review_receipts"] == 1
    assert body["approval_authentication"] == "CALLER_ASSERTED_ONLY"

    result, body = invoke(tmp_path, capsys, None,
                          "--approval-ref", "operator-ack:synthetic",
                          "--rollback-ref", "operator-ack:rollback")
    assert result == 0
    assert body["candidate_qualified"] is True
    assert body["active_candidate"] is False
    assert body["correction_active"] is False
    assert body["review_receipts"] == 2
    assert body["rolled_back"] is True


def test_failed_holdout_never_activates_even_when_operator_asks(tmp_path, capsys):
    payload = fixture()
    payload["holdout"][0]["expected"] = "blue"
    result, body = invoke(tmp_path, capsys, payload, "--approval-ref", "ack:fail")
    assert result == 0
    assert body["candidate_qualified"] is False
    assert body["active_candidate"] is False
    assert body["review_receipts"] == 0


def test_output_never_includes_training_text(tmp_path, capsys):
    payload = fixture()
    payload["samples"][0]["answer"] = "PRIVATE_CANARY_CORRECTION"
    payload["holdout"][0]["expected"] = "PRIVATE_CANARY_CORRECTION"
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert cli.main(["feedback-lab", "--fixture", str(path),
                     "--approval-ref", "ack:synthetic"]) == 0
    stdout = capsys.readouterr().out
    assert "PRIVATE_CANARY_CORRECTION" not in stdout
    assert "color of a ripe banana" not in stdout


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(synthetic=False),
    lambda d: d.update(schema="WRONG"),
    lambda d: d.update(unknown="unexpected"),
    lambda d: d.update(holdout=[]),
])
def test_invalid_fixture_fails_closed(tmp_path, capsys, mutate):
    payload = fixture()
    mutate(payload)
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main(["feedback-lab", "--fixture", str(path)])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


def test_reject_ambiguous_json_duplicate_keys_and_oversize(tmp_path, capsys):
    path = tmp_path / "fixture.json"
    path.write_text('{"schema":"A","schema":"B"}', encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main(["feedback-lab", "--fixture", str(path)])
    assert exc.value.code == 2
    path.write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises(SystemExit) as exc:
        cli.main(["feedback-lab", "--fixture", str(path)])
    assert exc.value.code == 2


def test_rollback_requires_distinct_explicit_approval(tmp_path, capsys):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture()), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main(["feedback-lab", "--fixture", str(path),
                  "--rollback-ref", "ack:rollback"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        cli.main(["feedback-lab", "--fixture", str(path),
                  "--approval-ref", "ack:same", "--rollback-ref", "ack:same"])
    assert exc.value.code == 2


def test_partial_holdout_failure_cannot_activate_or_pin_canary(tmp_path, capsys):
    payload = fixture()
    payload["holdout"].append({
        "case_id": "h2", "source_id": "independent-2", "cue": "untrained cue",
        "expected": "a withheld answer",
    })
    result, body = invoke(tmp_path, capsys, payload, "--approval-ref", "ack:partial")
    assert result == 0
    assert body["heldout_cases"] == 2
    assert body["candidate_passes"] == 1
    assert body["candidate_qualified"] is False
    assert body["active_candidate"] is False
    assert body["review_receipts"] == 0


def test_candidate_identity_independent_of_caller_approval_ref(tmp_path, capsys):
    _, first = invoke(tmp_path, capsys, None, "--approval-ref", "operator:a")
    _, second = invoke(tmp_path, capsys, None, "--approval-ref", "operator:b")
    assert first["candidate_revision"] == second["candidate_revision"]
    assert first["heldout_sha256"] == second["heldout_sha256"]
    assert first["candidate_revision"] != first["baseline_revision"]


@pytest.mark.parametrize("raw", [
    b"\xff\xfe\x00\x00",
    b'{"schema":"VERA_MONO_SYNTHETIC_FEEDBACK_LAB_V1", "synthetic":NaN}',
    b'{"schema":"A","synthetic":true,"samples":[{"cue":"x","cue":"y"}],"holdout":[]}',
])
def test_malformed_ambiguous_or_nonfinite_input_never_outputs_receipt(tmp_path, capsys, raw):
    path = tmp_path / "fixture.json"
    path.write_bytes(raw)
    with pytest.raises(SystemExit) as exc:
        cli.main(["feedback-lab", "--fixture", str(path),
                  "--approval-ref", "synthetic:review"])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


def test_failed_candidate_cannot_report_requested_rollback_as_success(tmp_path, capsys):
    payload = fixture()
    payload["holdout"][0]["expected"] = "wrong"
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main(["feedback-lab", "--fixture", str(path),
                  "--approval-ref", "synthetic:review",
                  "--rollback-ref", "synthetic:rollback"])
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("bad_ref", ["", "  ", "x" * 257])
def test_bad_review_ref_rejected_before_evaluation(tmp_path, capsys, bad_ref):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture()), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main(["feedback-lab", "--fixture", str(path),
                  "--approval-ref", bad_ref])
    assert exc.value.code == 2
