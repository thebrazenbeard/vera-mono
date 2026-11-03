"""Source-only Windows reparse probe; no user directory is inspected."""

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from tools.security.windows_nt_reparse_probe import (
    STATUS_REPARSE_POINT_ENCOUNTERED,
    _synthetic_pair_status,
    main,
    require_synthetic_build_pass,
    run_synthetic_reparse_probe,
)


class WindowsNativeReparseProbeTests(unittest.TestCase):
    def test_synthetic_fixture_is_never_lappy_qualification(self):
        result = run_synthetic_reparse_probe()
        if os.name != "nt":
            self.assertEqual(result, {"status": "NOT_RUN_NON_WINDOWS"})
            return
        require_synthetic_build_pass(result)
        self.assertTrue(result["windows_build"])
        self.assertTrue(result["architecture"])
        self.assertIn(result["python_pointer_bits"], (32, 64))
        self.assertFalse(result["live_host_qualified"])
        self.assertFalse(result["onedrive_hydration_proven_safe"])

    def test_unqualified_results_cannot_pass(self):
        for status in (
            "UNQUALIFIED_SYMLINK_FIXTURE_UNAVAILABLE",
            "UNQUALIFIED_NATIVE_OPEN_UNAVAILABLE",
            "SYNTHETIC_BUILD_PROBE_FAIL",
            "NOT_RUN_NON_WINDOWS",
        ):
            with self.subTest(status=status), self.assertRaisesRegex(AssertionError, "did not qualify"):
                require_synthetic_build_pass({"status": status})
        with self.assertRaisesRegex(AssertionError, "lacks pinned build"):
            require_synthetic_build_pass({"status": "SYNTHETIC_BUILD_PROBE_PASS"})

    def test_only_exact_native_pair_passes(self):
        self.assertEqual(
            _synthetic_pair_status(0, STATUS_REPARSE_POINT_ENCOUNTERED),
            "SYNTHETIC_BUILD_PROBE_PASS",
        )
        for pair in ((0, 0), (1, STATUS_REPARSE_POINT_ENCOUNTERED), (1, 0)):
            with self.subTest(pair=pair):
                self.assertEqual(_synthetic_pair_status(*pair), "SYNTHETIC_BUILD_PROBE_FAIL")

    def test_cli_receipt_is_visible_on_pass_and_fail(self):
        sample = {
            "status": "SYNTHETIC_BUILD_PROBE_PASS",
            "windows_build": "10.0.26100",
            "architecture": "AMD64",
            "python_pointer_bits": 64,
            "live_host_qualified": False,
            "onedrive_hydration_proven_safe": False,
            "genuine_child_status": "0x00000000",
            "reparse_child_status": "0xc000050b",
        }
        for status, should_pass in (
            ("SYNTHETIC_BUILD_PROBE_PASS", True),
            ("UNQUALIFIED_NATIVE_OPEN_UNAVAILABLE", False),
        ):
            with self.subTest(status=status):
                output = io.StringIO()
                with patch(
                    "tools.security.windows_nt_reparse_probe.run_synthetic_reparse_probe",
                    return_value={**sample, "status": status, "private_path": "must-not-leak"},
                ), redirect_stdout(output):
                    if should_pass:
                        self.assertEqual(main(), 0)
                    else:
                        with self.assertRaisesRegex(AssertionError, "did not qualify"):
                            main()
                self.assertEqual(json.loads(output.getvalue()), {**sample, "status": status})


if __name__ == "__main__":
    unittest.main()
