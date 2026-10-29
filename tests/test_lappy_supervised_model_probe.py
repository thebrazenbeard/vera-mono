"""Harness-only safety tests; the real Lappy Ollama probe is run separately."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from scripts import lappy_supervised_model_probe as probe


def test_harness_rejects_missing_explicit_synthetic_guard(tmp_path):
    with patch.dict(os.environ, {"VERA_SYNTHETIC_DEMO_ONLY": ""}):
        with patch.object(probe, "_model") as model:
            with pytest.raises(RuntimeError, match="production use forbidden"):
                probe.main(["baseline", "--db", str(tmp_path / "fixture.sqlite3")])
            model.assert_not_called()


def test_harness_unapproved_retrieval_never_supplies_a_synthetic_answer(tmp_path):
    class EmptyJournal:
        head = "0" * 64

        def lookup(self, cue):
            assert cue == probe.CUE
            return None

    capture = io.StringIO()
    with patch.dict(os.environ, {"VERA_SYNTHETIC_DEMO_ONLY": "1"}):
        with patch.object(probe, "_open", return_value=EmptyJournal()):
            with patch.object(probe, "_model", return_value={"answer": "UNKNOWN", "model": "fake-local"}) as model:
                with redirect_stdout(capture):
                    assert probe.main(["query", "--db", str(tmp_path / "fixture.sqlite3"), "--head", "0" * 64]) == 0
    output = json.loads(capture.getvalue())
    assert output["retrieved"] is None
    assert output["answer"] == "UNKNOWN"
    model.assert_called_once_with(probe.CUE, None, "vera-local:latest")


@pytest.mark.skipif(os.name != "nt", reason="Windows drive containment rule")
def test_windows_harness_denies_journal_outside_isolated_test_root():
    with tempfile.TemporaryDirectory() as other_root:
        with pytest.raises(ValueError, match="fixture DB must stay beneath"):
            probe._scope(Path(other_root) / "not-in-vera.sqlite3")

