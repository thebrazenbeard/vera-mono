import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ingest.cli import main


class CliTests(unittest.TestCase):
    def test_text_default_is_machine_json_and_duplicate_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                first = main(["--store", str(Path(tmp) / ".ingest"), "text", "hello", "--locator", "urn:cli"])
            payload = json.loads(output.getvalue())
            self.assertEqual(first, 0)
            self.assertEqual(payload["status"], "ACCEPTED")

            output = io.StringIO()
            with redirect_stdout(output):
                second = main(["--store", str(Path(tmp) / ".ingest"), "text", "hello", "--locator", "urn:cli"])
            self.assertEqual(second, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "DUPLICATE")

    def test_human_mode_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--store", str(Path(tmp) / ".ingest"), "--human", "text", "hello"])
            self.assertEqual(code, 0)
            self.assertTrue(output.getvalue().startswith("ACCEPTED "))
            self.assertNotIn('"schema"', output.getvalue())

    def test_inspect_missing_returns_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--store", str(Path(tmp) / ".ingest"), "inspect", "f" * 64])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["status"], "NOT_FOUND")

    def test_file_root_cli_accepts_relative_operator_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            try:
                os.chdir(tmp)
                Path("allowed").mkdir()
                Path("allowed/data.txt").write_text("hello", encoding="utf-8")
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main([
                        "--store", str(Path(tmp) / ".ingest"),
                        "file", "allowed/data.txt",
                        "--root", ".",
                    ])
            finally:
                os.chdir(previous)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "ACCEPTED")

    def test_malformed_message_json_is_machine_readable_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"broken":', encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([
                    "--store", str(Path(tmp) / ".ingest"),
                    "message", str(path), "--id", "m1",
                ])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(payload["status"], "REJECTED")
            self.assertIn("valid JSON", payload["error"])

    def test_non_object_message_json_is_machine_readable_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "array.json"
            path.write_text("[1,2,3]", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = main([
                    "--store", str(Path(tmp) / ".ingest"),
                    "message", str(path), "--id", "m1",
                ])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(payload["status"], "REJECTED")
            self.assertIn("object", payload["error"])

    def test_stdin_json_read_is_bounded_by_max_bytes(self):
        class GuardedStdin(io.StringIO):
            def __init__(self, value):
                super().__init__(value)
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                if size < 0:
                    raise AssertionError("stdin was read without a byte bound")
                return super().read(size)

        with tempfile.TemporaryDirectory() as tmp:
            stdin = GuardedStdin("abcdef")
            output = io.StringIO()
            with patch("sys.stdin", stdin), redirect_stdout(output):
                code = main([
                    "--store", str(Path(tmp) / ".ingest"),
                    "--max-bytes", "5",
                    "json", "-",
                ])
            payload = json.loads(output.getvalue())
            self.assertEqual(code, 2)
            self.assertEqual(payload["status"], "REJECTED")
            self.assertTrue(stdin.read_sizes)
            self.assertTrue(all(size >= 0 for size in stdin.read_sizes))


if __name__ == "__main__":
    unittest.main()
