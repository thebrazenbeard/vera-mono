"""The public CLI must never echo operating-system paths from private sources."""

from __future__ import annotations

import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from tools.local_training.__main__ import main


class LocalTrainingCLIRedactionTests(unittest.TestCase):
    _SECRET = "/private/SENTINEL-OWNER-CONVERSATIONS/manifest.json"

    def assert_private_os_error_redacted(self, argv: list[str], called: str, expected_prefix: str):
        stderr = StringIO()
        stdout = StringIO()
        error = OSError(13, "Permission denied", self._SECRET)
        with patch(f"tools.local_training.__main__.{called}", side_effect=error):
            with redirect_stderr(stderr), redirect_stdout(stdout):
                result = main(argv)
        self.assertEqual(result, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertTrue(stderr.getvalue().startswith(f"{expected_prefix}: "))
        self.assertNotIn(self._SECRET, stderr.getvalue())
        self.assertNotIn("SENTINEL-OWNER-CONVERSATIONS", stderr.getvalue())
        self.assertNotIn("Permission denied", stderr.getvalue())

    def test_corpus_plan_redacts_private_os_errors(self):
        self.assert_private_os_error_redacted(
            ["plan", "/private/synthetic-manifest.json"], "build_plan", "PREPARATION_HOLD"
        )

    def test_training_plan_redacts_private_os_errors(self):
        self.assert_private_os_error_redacted(
            ["train-plan", "/private/synthetic-manifest.json", "/private/output",
             "--model-dir", "/private/model"], "plan_local_training", "TRAINING_HOLD"
        )


if __name__ == "__main__":
    unittest.main()
