"""Verify that the created single-file artifact really starts offline."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_single_file_zipapp_runs_help(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mini-vera-dist-test-") as temp:
            output = Path(temp) / "mini-vera.pyz"
            subprocess.run(
                [sys.executable, str(ROOT / "tools" / "build_zipapp.py"),
                 "--output", str(output)],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertTrue(output.is_file())
            result = subprocess.run(
                [sys.executable, str(output), "--help"],
                cwd=temp,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("mini-vera", (result.stdout + result.stderr).lower())


if __name__ == "__main__":
    unittest.main()
