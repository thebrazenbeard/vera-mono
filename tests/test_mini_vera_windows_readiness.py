"""Readiness display: synthetic source-only probes, zero model inference."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from tools.mini_vera import ollama_preflight, windows_readiness


BASE = {
    "status": "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE",
    "model_resident": True, "model_size_bytes": 1_322_069_277,
    "available_physical_ram_bytes": 2 * ollama_preflight.GIB,
    "required_physical_ram_bytes": ollama_preflight.GIB,
    "ollama_tag_digest": "a" * 64,
    "identity_provenance": "REVIEWED_CODE_SHA_PINS_NOT_HOST_ATTESTED",
}


class WindowsReadinessTests(unittest.TestCase):
    def test_good_resource_observation_does_not_create_launch_authority(self):
        seen = []

        def observer(**kw):
            seen.append(kw)
            return dict(BASE)

        result = windows_readiness.assess(probe=observer)
        self.assertEqual("RESOURCE_OBSERVED_NO_HOST_LEASE", result["status"])
        self.assertEqual("NOT_BOUND", result["host_lease"])
        self.assertIs(result["launch_allowed"], False)
        self.assertEqual(0, result["model_inference_calls"])
        self.assertEqual("NOT_PERFORMED", result["cpu_disk_workload_qualification"])
        self.assertIs(seen[0]["allow_cold_load"], False)

    def test_cold_model_resource_estimate_is_not_automatic_load(self):
        sample = dict(BASE, status="COLD_MODEL_NOT_AUTHORIZED_TO_LOAD",
                      model_resident=False)
        result = windows_readiness.assess(probe=lambda **_kw: sample)
        self.assertEqual("COLD_MODEL_NOT_AUTHORIZED", result["status"])
        self.assertFalse(result["launch_allowed"])

    def test_busy_host_refusal_is_explained_without_inference(self):
        def busy(**_kw):
            raise ollama_preflight.PreflightRefused("insufficient free physical RAM")

        output = io.StringIO()
        with redirect_stdout(output):
            code = windows_readiness.main([], probe=busy)
        self.assertEqual(2, code)
        self.assertIn("RESOURCE_REFUSED", output.getvalue())
        self.assertIn("Launch authority: NONE", output.getvalue())
        self.assertIn("NOT BOUND", output.getvalue())

    def test_unknown_preflight_status_fails_closed(self):
        result = windows_readiness.assess(probe=lambda **_kw: {"status": "NEW_UNREVIEWED"})
        self.assertEqual("UNKNOWN_PREFLIGHT_STATUS", result["status"])
        self.assertFalse(result["launch_allowed"])

    def test_json_is_machine_readable_and_non_effectful(self):
        out = io.StringIO()
        with patch.object(windows_readiness.ollama_preflight.local_session, "main",
                          side_effect=AssertionError("model launched")), redirect_stdout(out):
            code = windows_readiness.main(["--json"], probe=lambda **_kw: dict(BASE))
        self.assertEqual(0, code)
        receipt = json.loads(out.getvalue())
        self.assertFalse(receipt["launch_allowed"])
        self.assertEqual(0, receipt["model_inference_calls"])
        self.assertEqual("SERVER_DECLARED_NOT_WEIGHT_ATTESTATION",
                         receipt["model_digest_evidence"])

    def test_inference_flags_are_not_supported_by_display(self):
        called = []

        def observer(**_kw):
            called.append(True)
            return dict(BASE)

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            windows_readiness.main(["--execute", "--host-idle-confirmed"], probe=observer)
        self.assertEqual(2, error.exception.code)
        self.assertEqual([], called)

    def test_custom_model_and_digest_are_forwarded_without_mutation(self):
        captured = []

        def observer(**kw):
            captured.append(kw)
            return dict(BASE)

        windows_readiness.assess(model="qwen3.5:0.8b", expected_tag_digest="f" * 64,
                                 probe=observer)
        self.assertEqual("qwen3.5:0.8b", captured[0]["model"])
        self.assertEqual("f" * 64, captured[0]["expected_tag_digest"])

    def test_readiness_text_labels_missing_cpu_disk_and_external_lease(self):
        out = io.StringIO()
        with redirect_stdout(out):
            windows_readiness.main([], probe=lambda **_kw: dict(BASE))
        self.assertIn("Observed RAM: 2.00 GiB", out.getvalue())
        self.assertIn("CPU/disk workload qualification: NOT PERFORMED", out.getvalue())
        self.assertIn("Host-owned exclusive lease: NOT BOUND", out.getvalue())


if __name__ == "__main__":
    unittest.main()
