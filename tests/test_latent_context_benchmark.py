from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "latent_context_cases.json"
SCRIPT = ROOT / "scripts" / "measure_latent_context.py"


def _measurement_module():
    spec = importlib.util.spec_from_file_location(
        "measure_latent_context",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_measurement_corpus_exposes_late_relevance_and_fail_closed_behavior():
    module = _measurement_module()

    result = module.measure_cases(FIXTURE)
    by_case = {item["case_id"]: item for item in result["cases"]}

    assert result["schema"] == "VERA_MONO_LATENT_CONTEXT_MEASUREMENT_V1"
    assert result["claim_ceiling"] == "VERA_MANAGED_CONTEXT_ONLY_NOT_GPU_VRAM"
    assert result["false_reconstruction_count"] == 0

    for case_id in (
        "late_color",
        "late_number",
        "late_code_identifier",
        "correction_supersession",
    ):
        assert by_case[case_id]["status"] == "EXACT_REHYDRATED"
        assert by_case[case_id]["exact_recovered"] is True
        assert by_case[case_id]["rehydration_count"] == 1

    assert by_case["missing_backing"]["status"] == "INSUFFICIENT_FIDELITY"
    assert by_case["missing_backing"]["exact_recovered"] is False
    assert by_case["missing_backing"]["active_bytes"] == 0

    assert by_case["conflicting_sources"]["status"] == "COMPACT"
    assert by_case["irrelevant_bulk"]["status"] == "COMPACT"
    assert (
        by_case["irrelevant_bulk"]["active_bytes"]
        < by_case["irrelevant_bulk"]["source_bytes"]
    )

    assert result["successful_case_count"] == 6
    assert result["failed_exact_case_count"] == 1
    assert result["successful_source_bytes"] > result["successful_active_bytes"]


def test_measurement_output_is_deterministic():
    module = _measurement_module()

    first = module.measure_cases(FIXTURE)
    second = module.measure_cases(FIXTURE)

    assert first == second


def test_measurement_cli_binds_to_current_repo_source_tree():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(FIXTURE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema"] == "VERA_MONO_LATENT_CONTEXT_MEASUREMENT_V1"
    assert payload["successful_case_count"] == 6
