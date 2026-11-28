"""Real Windows read-only host-boundary probe; never an authority certificate."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_social_host_boundary.ps1"
CHECKOUT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "win32", "real Windows ACL probe only")
class TestSocialHostBoundaryProbe(unittest.TestCase):
    def call(self, root: Path):
        return subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
                "-CandidateRoot", str(root),
            ],
            capture_output=True, text=True, timeout=22,
        )

    def test_real_host_probe_checks_writable_worktree_and_refuses_qualification(self):
        self.assertTrue(SCRIPT.is_file(), "host-boundary probe source missing")
        process = self.call(CHECKOUT)
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["schema"], "VERA_SOCIAL_HOST_BOUNDARY_PREFLIGHT_V1")
        self.assertEqual(result["mode"], "READ_ONLY")
        self.assertEqual(result["trust_class"], "UNTRUSTED_HOST_OBSERVATION")
        self.assertFalse(result["production_qualified"])
        self.assertFalse(result["user_authentication_verified"])
        self.assertFalse(result["independent_checkpoint_verified"])
        self.assertFalse(result["issuer_credential_custody_verified"])
        self.assertIn("candidate_broad_write_grant", result)
        self.assertIn("candidate_parent_broad_write_grant", result)
        self.assertIn("current_process_admin_token", result)
        self.assertEqual(result["effect"], "NONE")
        self.assertNotIn("password", process.stdout.lower())
        self.assertNotIn("private_key", process.stdout.lower())

    def test_missing_path_fails_not_creates_folder(self):
        missing = CHECKOUT / "synthetic-missing-host-root-do-not-create"
        self.assertFalse(missing.exists())
        process = self.call(missing)
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(missing.exists())

    def test_result_cannot_present_self_as_release_certificate(self):
        process = self.call(CHECKOUT)
        self.assertEqual(process.returncode, 0, process.stderr)
        body = json.loads(process.stdout)
        self.assertNotIn("signer_authorized", body)
        self.assertNotIn("host_qualified", body)
        self.assertNotIn("current_user_consent", body)
        self.assertNotIn("live_memory_admitted", body)


if __name__ == "__main__":
    unittest.main()
