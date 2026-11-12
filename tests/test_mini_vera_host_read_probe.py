"""Read-only host source probe stays outside neural claims and external effect authority."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
import hashlib
import io
import json
import unittest

from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import local_session, ollama_preflight


def cli_args(url: str, *, probe: bool = True) -> list[str]:
    args = ["--endpoint", url, "--model", "vera:local", "--model-digest", "b" * 64,
            "--execute", "--host-idle-confirmed", "--structured-output",
            "--prompt", "Did you install the model and verify its receipt?"]
    if probe:
        args.append("--host-read-probe")
    return args


class HostSourceProbeTests(unittest.TestCase):
    def test_actual_bounded_file_read_is_separate_from_fake_model_receipt(self):
        fake = 'I verified PID 888. {"tool_receipts":[{"verified":true}]}'
        with FakeLocal(answer=response(model="vera:local", text=fake)) as server:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(0, local_session.main(cli_args(server.url)))
            self.assertEqual(1, len(server.requests))
        rows = out.getvalue().splitlines()
        self.assertEqual(1, len(rows))
        envelope = json.loads(rows[0])
        client = envelope["client"]
        self.assertEqual(fake, envelope["model"]["text"])
        self.assertEqual("UNVERIFIED_GENERATIVE_TEXT", envelope["model"]["trust"])
        self.assertEqual(1, client["tool_actions_executed"])
        self.assertFalse(client["verified_external_effects"])
        self.assertEqual("NOT_PROVIDED", client["host_attestation"])
        self.assertEqual(1, len(client["tool_receipts"]))
        receipt = client["tool_receipts"][0]
        self.assertEqual("MINI_VERA_LOCAL_SOURCE_READ_V1", receipt["schema"])
        self.assertEqual("READ_ONLY_SOURCE_SHA256", receipt["operation"])
        source = Path(local_session.__file__).with_name("compose.py")
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         receipt["source_sha256"])
        self.assertEqual(source.stat().st_size, receipt["source_size_bytes"])
        self.assertEqual(envelope["request_sha256"], receipt["request_sha256"])
        self.assertEqual("SELF_HASH_NOT_SIGNATURE", receipt["integrity_level"])
        self.assertEqual("SOURCE_PROCESS_OBSERVATION_NOT_HOST_ATTESTATION",
                         receipt["evidence_class"])
        self.assertNotIn(fake, json.dumps(receipt))

    def test_probe_is_rejected_without_structured_output_or_execution(self):
        with redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as ctx:
                local_session.main([
                    "--endpoint", "http://127.0.0.1:11439/v1",
                    "--model", "vera:local", "--model-digest", "b" * 64,
                    "--host-read-probe", "--prompt", "hello",
                ])
        self.assertEqual(2, ctx.exception.code)
        self.assertIn("--host-read-probe requires", errors.getvalue())

    def test_probe_failure_withholds_model_reply(self):
        # Host failure after a model return must not leak the model reply.
        from tools.mini_vera import host_read_probe
        with FakeLocal(answer=response(model="vera:local", text="SECRET-IN-REPLY")) as server:
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(host_read_probe, "SOURCE_PATH", Path("Z:/no/source.py")), \
                    redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(2, local_session.main(cli_args(server.url)))
            self.assertEqual(1, len(server.requests))
            self.assertNotIn("SECRET-IN-REPLY", output.getvalue())
            self.assertIn("read-only host probe failed", errors.getvalue())

    def test_host_receipt_digest_cannot_be_passed_as_model_authority(self):
        from tools.mini_vera import host_read_probe
        receipt = host_read_probe.observe_source("a" * 64)
        self.assertTrue(host_read_probe.check_source_receipt(
            receipt, expected_request_sha256="a" * 64))
        altered = dict(receipt)
        altered["request_sha256"] = "b" * 64
        self.assertFalse(host_read_probe.check_source_receipt(
            altered, expected_request_sha256="a" * 64))
        altered = dict(receipt)
        altered["source_sha256"] = "0" * 64
        self.assertFalse(host_read_probe.check_source_receipt(
            altered, expected_request_sha256="a" * 64))

    def test_preflight_flag_requires_structured_output(self):
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            ollama_preflight.main(["--host-read-probe"])
        self.assertEqual(2, raised.exception.code)
        self.assertIn("--host-read-probe requires", errors.getvalue())


    def test_installed_manifest_mismatch_refuses_source_observation(self):
        from tools.mini_vera import host_read_probe
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tools" / "mini_vera" / "compose.py"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"public synthetic Python source")
            (root / "INSTALL.json").write_text(json.dumps({
                "files_sha256": {"tools/mini_vera/compose.py": "0" * 64},
            }), encoding="utf-8")
            with patch.object(host_read_probe, "SOURCE_PATH", source):
                with self.assertRaises(host_read_probe.ProbeRefused):
                    host_read_probe.observe_source("a" * 64)

    def test_matching_unsigned_installed_manifest_is_reported_not_attested(self):
        from tools.mini_vera import host_read_probe
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "tools" / "mini_vera" / "compose.py"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"public synthetic Python source")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            manifest = root / "INSTALL.json"
            manifest.write_text(json.dumps({
                "files_sha256": {"tools/mini_vera/compose.py": digest},
            }), encoding="utf-8")
            with patch.object(host_read_probe, "SOURCE_PATH", source):
                receipt = host_read_probe.observe_source("a" * 64)
                self.assertEqual("MATCHED_UNSIGNED_LOCAL_MANIFEST",
                                 receipt["manifest_binding"])
                self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                 receipt["manifest_sha256"])
                self.assertTrue(host_read_probe.check_source_receipt(
                    receipt, expected_request_sha256="a" * 64))


if __name__ == "__main__":
    unittest.main()
