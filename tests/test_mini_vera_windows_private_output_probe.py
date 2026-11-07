"""Safety envelope for the optional Windows temp-only DACL experiment.

The live Windows API experiment is deliberately opt-in; these tests do not
qualify the private-output writer or impersonate a foreign security principal.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from tools.mini_vera import qualification_workflow, windows_private_output_probe
from tools.mini_vera.loopback import LoopbackRejected


class WindowsPrivateOutputProbeSafetyTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt" and sys.platform == "win32",
                         "requires Windows DOS short-name API")
    def test_native_short_alias_expands_to_declared_long_path(self):
        import ctypes
        from ctypes import wintypes

        source = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        method = kernel.GetShortPathNameW
        method.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        method.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(4096)
        count = method(str(source), buffer, len(buffer))
        if not count or count >= len(buffer) or buffer.value == str(source):
            self.skipTest("Windows volume does not expose a short-name alias")
        self.assertEqual(windows_private_output_probe._long_declared_dos_path(
            Path(buffer.value)), source)

    @unittest.skipUnless(os.name == "nt" and sys.platform == "win32",
                         "requires native Windows junction behavior")
    def test_declared_path_normalization_does_not_follow_junction_target(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "actual-target"
            target.mkdir()
            alias = Path(folder) / "junction-alias"
            result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J",
                                     str(alias), str(target)], capture_output=True,
                                    text=True, timeout=10)
            if result.returncode:
                self.skipTest("Windows temporary filesystem cannot create junctions")
            self.assertEqual(windows_private_output_probe._long_declared_dos_path(alias),
                             alias)

    @unittest.skipUnless(os.name == "nt" and sys.platform == "win32",
                         "requires actual Windows NT security descriptors")
    def test_native_temp_only_acl_and_exclusive_create_without_promoting_custody(self):
        # A source-only Linux mock cannot establish an NT security descriptor.
        # This deliberately exercises only an ephemeral harmless marker, not
        # the production private-output writer or a real evaluation payload.
        result = windows_private_output_probe.run_probe()
        self.assertEqual(result["status"], "TEMP_PROBE_PASSED_NOT_CUSTODY_QUALIFIED")
        self.assertEqual(result["native_handle_relative_file_create"], "SUCCESS")
        self.assertEqual(result["exclusive_create_repeated"], "REFUSED")
        self.assertIs(result["child_dacl_protected"], True)
        self.assertEqual(result["child_dacl_explicit_aces"],
                         "OWNER_RIGHTS_AND_LOCAL_SYSTEM_ONLY")
        self.assertEqual(result["same_handle_marker_readback"], "PASS")
        self.assertEqual(result["foreign_user_access_check"], "NOT_RUN")
        self.assertEqual(result["trusted_host_parent_authority"], "NOT_ESTABLISHED")
        self.assertEqual(result["production_writer"], "STILL_FAIL_CLOSED")

    @unittest.skipIf(os.name == "nt" and sys.platform == "win32", "Linux-only refusal check")
    def test_non_windows_probe_refuses_before_any_temporary_write(self):
        with mock.patch.object(windows_private_output_probe.tempfile, "TemporaryDirectory",
                               side_effect=AssertionError("test must not touch filesystem")):
            with self.assertRaisesRegex(RuntimeError, "requires Windows"):
                windows_private_output_probe.run_probe()

    @unittest.skipIf(os.name == "nt" and sys.platform == "win32", "Linux-only error envelope")
    def test_non_windows_cli_reports_no_qualification(self):
        output = StringIO()
        errors = StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = windows_private_output_probe.main()
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        report = json.loads(errors.getvalue())
        self.assertEqual(report["status"], "TEMP_PROBE_FAILED")
        self.assertEqual(report["production_writer"], "STILL_FAIL_CLOSED")

    def test_production_windows_writer_remains_fail_closed(self):
        with self.assertRaisesRegex(LoopbackRejected, "Windows private evaluation output HOLD"):
            qualification_workflow._windows_create_in_parent(
                qualification_workflow.ROOT.parent, "never-created-by-probe.json"
            )


if __name__ == "__main__":
    unittest.main()
