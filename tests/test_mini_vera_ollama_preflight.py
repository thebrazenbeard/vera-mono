"""0.8B preflight: real read-only HTTP, synthetic inventories and no model load."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import ctypes
import hashlib
import json
from pathlib import Path
import tempfile
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.mini_vera import ollama_preflight as preflight


MODEL = "qwen3.5:0.8b"
DIGEST = "9" * 64
MODEL_SIZE = 1_322_000_000


def inventory(*, resident: bool = False, foreign: bool = False,
              digest: str = DIGEST, model_size: int = MODEL_SIZE):
    tags = {"models": [{"name": MODEL, "digest": digest, "size": model_size}]}
    ps = {"models": ([{"name": MODEL, "digest": digest}] if resident else [])}
    if foreign:
        ps["models"].append({"name": "important-work:latest", "digest": "a" * 64})
    return tags, ps


def fake_getter(tags: dict, ps: dict):
    paths: list[str] = []

    def getter(_host: str, _port: int, path: str):
        paths.append(path)
        return tags if path == "/api/tags" else ps

    return getter, paths


class FakeOllama:
    def __init__(self, tags, ps):
        self.tags, self.ps = tags, ps
        self.paths: list[tuple[str, str]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.paths.append(("GET", self.path))
                body = json.dumps(outer.tags if self.path == "/api/tags" else outer.ps).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                outer.paths.append(("POST", self.path))
                self.send_response(500)
                self.end_headers()

            def log_message(self, _format, *_args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, _type, _value, _traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class PreflightTests(unittest.TestCase):
    def test_receipt_exclusive_open_forces_binary_bytes_on_windows(self):
        # Linux has no O_BINARY. Inject its value and strip that synthetic bit
        # only when calling the real Linux os.open; on Windows the *real* flag
        # reaches the CRT and prevents LF -> CRLF rewriting.
        native_binary = getattr(preflight.os, "O_BINARY", 0)
        binary_flag = native_binary or (1 << 27)
        actual_open = preflight.os.open
        created_flags: list[int] = []

        def inspecting_open(path, flags, mode=0o777):
            if str(path).endswith(".incomplete"):
                created_flags.append(flags)
            passed_flags = flags if native_binary else flags & ~binary_flag
            return actual_open(path, passed_flags, mode)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "receipt.json"
            _, parent_identity = preflight._receipt_target(target)
            receipt = {"schema": "SYNTHETIC", "status": "PUBLICATION_UNQUALIFIED"}
            with patch.object(preflight.os, "O_BINARY", binary_flag, create=True), \
                    patch.object(preflight.os, "open", side_effect=inspecting_open):
                preflight._commit_receipt_atomically(target, receipt, parent_identity)
            self.assertEqual(1, len(created_flags))
            self.assertTrue(created_flags[0] & binary_flag)
            self.assertEqual(preflight._receipt_bytes(receipt), target.read_bytes())
            self.assertEqual(b"\n", target.read_bytes()[-1:])
            self.assertNotEqual(b"\r\n", target.read_bytes()[-2:])

    def test_slow_trickle_response_has_absolute_two_second_deadline(self):
        # A per-socket-read timeout would accept this valid 13-byte JSON
        # after >4 seconds; the absolute deadline must refuse it near 2s.
        class SlowHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"models":[]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                for ch in body:
                    try:
                        self.wfile.write(bytes([ch]))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    time.sleep(.36)

            def log_message(self, _format, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            start = time.monotonic()
            with self.assertRaisesRegex(preflight.PreflightRefused, "unavailable"):
                preflight._read_ollama_json("127.0.0.1", server.server_port, "/api/tags")
            elapsed = time.monotonic() - start
            self.assertLess(elapsed, 3.0, f"read-only probe exceeded hard deadline: {elapsed:.2f}s")
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)

    def test_resident_model_ready_and_only_read_only_gets(self):
        tags, ps = inventory(resident=True)
        with FakeOllama(tags, ps) as server:
            report = preflight.probe(endpoint=server.endpoint, memory_probe=lambda: 2 * preflight.GIB)
        self.assertEqual("RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE", report["status"])
        self.assertEqual(DIGEST, report["ollama_tag_digest"])
        self.assertFalse(report["exclusive_host_lease"])
        self.assertEqual(0, report["model_inference_calls"])
        self.assertEqual([("GET", "/api/tags"), ("GET", "/api/ps")], server.paths)

    def test_cold_model_without_explicit_load_permission_reports_no_load(self):
        tags, ps = inventory()
        with FakeOllama(tags, ps) as server:
            report = preflight.probe(endpoint=server.endpoint, memory_probe=lambda: 5 * preflight.GIB)
        self.assertEqual("COLD_MODEL_NOT_AUTHORIZED_TO_LOAD", report["status"])
        self.assertFalse(report["model_resident"])
        self.assertEqual(0, report["model_inference_calls"])
        self.assertEqual([("GET", "/api/tags"), ("GET", "/api/ps")], server.paths)

    def test_cold_load_explicitly_allowed_with_strong_headroom(self):
        tags, ps = inventory()
        getter, paths = fake_getter(tags, ps)
        report = preflight.probe(memory_probe=lambda: 5 * preflight.GIB,
                                 get_json=getter, allow_cold_load=True)
        self.assertEqual("RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE", report["status"])
        self.assertEqual(["/api/tags", "/api/ps"], paths)
        self.assertGreater(report["required_physical_ram_bytes"], 3 * preflight.GIB)

    def test_busy_host_fails_closed_without_model_launch(self):
        tags, ps = inventory()
        getter, paths = fake_getter(tags, ps)
        with self.assertRaisesRegex(preflight.PreflightRefused, "insufficient free"):
            preflight.probe(memory_probe=lambda: 700 * 1024 ** 2, get_json=getter,
                            allow_cold_load=True)
        self.assertEqual(["/api/tags", "/api/ps"], paths)

    def test_ram_drop_during_read_only_inventory_fails_closed(self):
        # /api/tags and /api/ps can each consume the bounded HTTP deadline;
        # the initial memory sample alone is stale by the decision point.
        tags, ps = inventory()
        getter, paths = fake_getter(tags, ps)
        samples = iter((5 * preflight.GIB, 500 * 1024 ** 2))
        with self.assertRaisesRegex(preflight.PreflightRefused, "insufficient free"):
            preflight.probe(memory_probe=lambda: next(samples), get_json=getter,
                            allow_cold_load=True)
        self.assertEqual(["/api/tags", "/api/ps"], paths)

    def test_foreign_resident_model_refuses_even_if_ram_abundant(self):
        tags, ps = inventory(resident=True, foreign=True)
        getter, _ = fake_getter(tags, ps)
        with self.assertRaisesRegex(preflight.PreflightRefused, "foreign Ollama"):
            preflight.probe(memory_probe=lambda: 20 * preflight.GIB, get_json=getter)

    def test_selected_tag_digest_pinning_and_resident_mismatch(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        with self.assertRaisesRegex(preflight.PreflightRefused, "tag digest changed"):
            preflight.probe(memory_probe=lambda: 2 * preflight.GIB, get_json=getter,
                            expected_tag_digest="a" * 64)
        ps["models"][0]["digest"] = "b" * 64
        with self.assertRaisesRegex(preflight.PreflightRefused, "resident model tag"):
            preflight.probe(memory_probe=lambda: 2 * preflight.GIB, get_json=getter)

    def test_unknown_oversized_duplicate_and_malformed_models_rejected(self):
        tags, ps = inventory()
        getter, _ = fake_getter(tags, ps)
        with self.assertRaisesRegex(preflight.PreflightRefused, "not installed"):
            preflight.probe(model="unknown:0.8b", memory_probe=lambda: 8 * preflight.GIB,
                            get_json=getter)
        tags["models"][0]["size"] = 5 * preflight.GIB
        with self.assertRaisesRegex(preflight.PreflightRefused, "over 0.8B"):
            preflight.probe(memory_probe=lambda: 8 * preflight.GIB, get_json=getter)
        tags["models"][0]["size"] = MODEL_SIZE
        tags["models"].append(dict(tags["models"][0]))
        with self.assertRaisesRegex(preflight.PreflightRefused, "duplicate"):
            preflight.probe(memory_probe=lambda: 8 * preflight.GIB, get_json=getter)
        tags["models"] = {}
        with self.assertRaisesRegex(preflight.PreflightRefused, "invalid Ollama"):
            preflight.probe(memory_probe=lambda: 8 * preflight.GIB, get_json=getter)

    def test_non_loopback_and_no_windows_probe_refused_before_http(self):
        tags, ps = inventory()
        getter, paths = fake_getter(tags, ps)
        with self.assertRaises(ValueError):
            preflight.probe(endpoint="http://example.com:11434/v1",
                            memory_probe=lambda: 8 * preflight.GIB, get_json=getter)
        self.assertEqual([], paths)
        with patch.object(preflight.sys, "platform", "linux"):
            with self.assertRaisesRegex(preflight.PreflightRefused, "Windows"):
                preflight.windows_free_physical_bytes()

    def test_main_no_execute_never_calls_local_session(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        out = io.StringIO()
        with patch.object(preflight.local_session, "main", side_effect=AssertionError("model launched")), \
                redirect_stdout(out):
            code = preflight.main([], memory_probe=lambda: 2 * preflight.GIB,
                                  get_json=getter)
        self.assertEqual(0, code)
        self.assertEqual("RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE",
                         json.loads(out.getvalue())["status"])

    def test_prompt_without_execute_is_rejected_before_network(self):
        tags, ps = inventory()
        getter, paths = fake_getter(tags, ps)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            preflight.main(["--prompt", "Never send this"],
                           memory_probe=lambda: 5 * preflight.GIB, get_json=getter)
        self.assertEqual(2, error.exception.code)
        self.assertEqual([], paths)

    def test_main_warm_explicit_execution_passes_tag_digest_as_declaration(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        out = io.StringIO()
        with patch.object(preflight.local_session, "main", return_value=0) as session, \
                redirect_stdout(out):
            code = preflight.main(["--execute", "--host-idle-confirmed", "--prompt", "Hello"],
                                  memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
        self.assertEqual(0, code)
        self.assertEqual(1, session.call_count)
        self.assertIn(DIGEST, session.call_args.args[0])
        self.assertIn("--execute", session.call_args.args[0])
        self.assertIn("--ollama-disable-thinking", session.call_args.args[0])

    def test_main_refuses_cold_load_without_special_permission(self):
        tags, ps = inventory()
        getter, _ = fake_getter(tags, ps)
        with patch.object(preflight.local_session, "main", side_effect=AssertionError("model launched")), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            code = preflight.main(["--execute", "--host-idle-confirmed", "--prompt", "Hello"],
                                  memory_probe=lambda: 5 * preflight.GIB, get_json=getter)
        self.assertEqual(2, code)

    def test_main_busy_host_refuses_without_session_call(self):
        tags, ps = inventory()
        getter, _ = fake_getter(tags, ps)
        error = io.StringIO()
        with patch.object(preflight.local_session, "main", side_effect=AssertionError("model launched")), \
                redirect_stderr(error):
            code = preflight.main(["--execute", "--host-idle-confirmed", "--prompt", "Hello",
                                   "--allow-cold-load"],
                                  memory_probe=lambda: 700 * 1024 ** 2, get_json=getter)
        self.assertEqual(2, code)
        self.assertIn("insufficient free", error.getvalue())

    def test_main_refuses_when_selected_model_digest_drifts_before_handoff(self):
        # A passing inventory observation is not a durable lease; a second
        # read can expose tag replacement immediately before local inference.
        tags, ps = inventory(resident=True)
        bad_tags, _ = inventory(resident=True, digest="b" * 64)
        reads = []

        def changing_getter(_host, _port, path):
            reads.append(path)
            if path == "/api/tags":
                return tags if reads.count(path) == 1 else bad_tags
            return ps

        with patch.object(preflight.local_session, "main", side_effect=AssertionError("model launched")), \
                redirect_stderr(io.StringIO()) as error, redirect_stdout(io.StringIO()):
            code = preflight.main(["--execute", "--host-idle-confirmed", "--prompt", "Hello"],
                                  memory_probe=lambda: 2 * preflight.GIB,
                                  get_json=changing_getter)
        self.assertEqual(2, code)
        self.assertEqual(2, reads.count("/api/tags"))
        self.assertIn("digest changed", error.getvalue())

    def test_main_refuses_when_ram_drops_between_preflight_and_handoff(self):
        tags, ps = inventory()
        getter, paths = fake_getter(tags, ps)
        readings = iter((5 * preflight.GIB, 5 * preflight.GIB,
                         5 * preflight.GIB, 500 * 1024 ** 2))
        with patch.object(preflight.local_session, "main", side_effect=AssertionError("model launched")), \
                redirect_stderr(io.StringIO()) as error, redirect_stdout(io.StringIO()):
            code = preflight.main(["--execute", "--host-idle-confirmed",
                                   "--allow-cold-load", "--prompt", "Hello"],
                                  memory_probe=lambda: next(readings), get_json=getter)
        self.assertEqual(2, code)
        self.assertEqual(["/api/tags", "/api/ps", "/api/tags", "/api/ps"], paths)
        self.assertIn("insufficient free", error.getvalue())

    def test_hash_only_trial_receipt_atomic_success_without_prompt_or_reply_text(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"
            stdout = io.StringIO()

            def fake_session(_args):
                print("Vera> I cannot attest to my weights.")
                return 0

            with patch.object(preflight.local_session, "main", side_effect=fake_session), \
                    redirect_stdout(stdout):
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "SECRET_IN_TEST",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(0, code)
            self.assertTrue(output.is_file())
            receipt = json.loads(output.read_text())
            self.assertEqual("CLIENT_OBSERVED_LOCAL_SESSION_OUTPUT_PUBLICATION_UNQUALIFIED",
                             receipt["status"])
            self.assertEqual("UNQUALIFIED_NOT_A_DURABLE_COMMIT_RECORD",
                             receipt["publication_custody"])
            self.assertEqual("NONCONFIDENTIAL_DICTIONARY_GUESSABLE_DO_NOT_USE_FOR_SECRETS",
                             receipt["content_sha256_privacy"])
            self.assertEqual(DIGEST, receipt["server_declared_tag_digest"])
            self.assertFalse(receipt["model_weights_verified"])
            self.assertFalse(receipt["exclusive_host_lease"])
            self.assertTrue(receipt["receipt_file_fsynced"])
            self.assertFalse(receipt["receipt_directory_metadata_fsynced"])
            self.assertTrue(receipt["reply_complete"])
            self.assertEqual(hashlib.sha256(b"SECRET_IN_TEST").hexdigest(),
                             receipt["input_prompt_sha256"])
            # Explicitly prove why a raw digest of a guessable prompt is not
            # private. This is synthetic test data, never a live credential.
            guesses = ["HELLO", "SECRET_IN_TEST", "GOODBYE"]
            self.assertIn(receipt["input_prompt_sha256"],
                          [hashlib.sha256(guess.encode()).hexdigest() for guess in guesses])
            self.assertEqual(hashlib.sha256(b"I cannot attest to my weights.").hexdigest(),
                             receipt["displayed_reply_sha256"])
            self.assertNotIn("SECRET_IN_TEST", output.read_text())
            self.assertNotIn("I cannot attest", output.read_text())
            self.assertIn("Vera> I cannot attest to my weights.", stdout.getvalue())
            publication_line = stdout.getvalue().splitlines()[-1]
            publication = json.loads(publication_line)
            self.assertEqual("PUBLISHED_HASH_ONLY_CUSTODY_UNQUALIFIED",
                             publication["receipt_status"])
            # Hash the *exact persisted bytes*, including terminal newline.
            self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(),
                             publication["receipt_sha256"])
            self.assertEqual(1, len(list(Path(directory).glob("*.incomplete"))))

    def test_partial_receipt_write_never_exposes_final_filename(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"

            def local_reply(_args):
                print("Vera> plausible model output")
                return 0

            with patch.object(preflight.local_session, "main", side_effect=local_reply), \
                    patch.object(preflight.os, "write", side_effect=OSError("disk full")), \
                    redirect_stderr(io.StringIO()) as stderr, \
                    redirect_stdout(io.StringIO()):
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "Hi",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(2, code)
            self.assertFalse(output.exists())
            self.assertIn("model call already attempted", stderr.getvalue())
            self.assertEqual(1, len(list(Path(directory).glob("*.incomplete"))))

    @unittest.skipIf(preflight.os.name == "nt", "Windows has no directory fsync via os.open")
    def test_postlink_directory_fsync_failure_leaves_only_unqualified_observation(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        original_fsync = preflight.os.fsync
        syncs = 0

        def fail_parent_sync(fd):
            nonlocal syncs
            syncs += 1
            if syncs == 2:
                raise OSError("synthetic directory fsync error")
            return original_fsync(fd)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"

            def local_reply(_args):
                print("Vera> result exists only if metadata sync succeeds")
                return 0

            with patch.object(preflight.local_session, "main", side_effect=local_reply), \
                    patch.object(preflight.os, "fsync", side_effect=fail_parent_sync), \
                    redirect_stderr(io.StringIO()) as stderr, \
                    redirect_stdout(io.StringIO()):
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "Hi",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(2, code)
            self.assertEqual(2, syncs)
            self.assertTrue(output.exists(), "postlink failure can leave visible bytes")
            unqualified = json.loads(output.read_text())
            self.assertIn("PUBLICATION_UNQUALIFIED", unqualified["status"])
            self.assertFalse(unqualified["receipt_directory_metadata_fsynced"])
            self.assertIn("model call already attempted", stderr.getvalue())

    @unittest.skipIf(preflight.os.name == "nt", "Windows has no directory fsync via os.open")
    def test_postlink_fsync_race_does_not_unlink_foreign_replacement(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        original_fsync = preflight.os.fsync
        syncs = 0
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"

            def swap_then_fail(fd):
                nonlocal syncs
                syncs += 1
                if syncs == 2:
                    foreign = Path(directory) / "foreign-ready.txt"
                    foreign.write_text("FOREIGN_RECEIPT_AFTER_LINK")
                    preflight.os.replace(foreign, output)
                    raise OSError("synthetic hostile dir fsync error")
                return original_fsync(fd)

            def local_reply(_args):
                print("Vera> synthetic result")
                return 0

            with patch.object(preflight.local_session, "main", side_effect=local_reply), \
                    patch.object(preflight.os, "fsync", side_effect=swap_then_fail), \
                    patch.object(Path, "unlink", side_effect=AssertionError("unsafe unlink")), \
                    redirect_stderr(io.StringIO()) as stderr, \
                    redirect_stdout(io.StringIO()):
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "Hi",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(2, code)
            self.assertEqual("FOREIGN_RECEIPT_AFTER_LINK", output.read_text())
            self.assertIn("model call already attempted", stderr.getvalue())

    @unittest.skipIf(preflight.os.name == "nt", "Windows has no directory fsync via os.open")
    def test_postlink_fsync_success_cannot_hide_foreign_final_replacement(self):
        """The post-link sync itself is an adversarial race boundary.

        Even if fsync returns successfully, an untrusted peer can replace the
        final name while it runs. The caller must not print a successful
        publication SHA for bytes no longer reachable at the final name.
        """
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        native_fsync = preflight.os.fsync
        syncs = 0
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"

            def swap_during_successful_parent_sync(fd):
                nonlocal syncs
                syncs += 1
                if syncs == 2:
                    foreign = Path(directory) / "foreign.txt"
                    foreign.write_text("FOREIGN_REPLACEMENT_AFTER_LINK")
                    preflight.os.replace(foreign, output)
                return native_fsync(fd)

            def local_reply(_args):
                print("Vera> synthetic result")
                return 0

            with patch.object(preflight.local_session, "main", side_effect=local_reply), \
                    patch.object(preflight.os, "fsync",
                                 side_effect=swap_during_successful_parent_sync), \
                    redirect_stderr(io.StringIO()) as stderr, \
                    redirect_stdout(io.StringIO()) as stdout:
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "Hi",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(2, syncs)
            self.assertEqual(2, code)
            self.assertEqual("FOREIGN_REPLACEMENT_AFTER_LINK", output.read_text())
            self.assertNotIn("PUBLISHED_HASH_ONLY", stdout.getvalue())
            self.assertIn("model call already attempted", stderr.getvalue())

    @unittest.skipIf(preflight.os.name == "nt", "Windows has no directory fsync via os.open")
    def test_postlink_fsync_success_cannot_hide_same_inode_content_corruption(self):
        """An inode identity check alone would miss in-place corruption."""
        native_fsync = preflight.os.fsync
        syncs = 0
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"
            _, parent_identity = preflight._receipt_target(output)
            receipt = {"schema": "SYNTHETIC", "status": "PUBLICATION_UNQUALIFIED"}

            def mutate_during_parent_sync(fd):
                nonlocal syncs
                syncs += 1
                if syncs == 2:
                    # Same byte length, same inode, different content. A
                    # follow-up stat-only check would falsely accept this.
                    altered = preflight._receipt_bytes(receipt).replace(
                        b"SYNTHETIC", b"CORRUPTED")
                    self.assertEqual(len(altered), len(preflight._receipt_bytes(receipt)))
                    output.write_bytes(altered)
                return native_fsync(fd)

            with patch.object(preflight.os, "fsync", side_effect=mutate_during_parent_sync):
                with self.assertRaisesRegex(preflight.PreflightRefused, "atomic receipt"):
                    preflight._commit_receipt_atomically(output, receipt, parent_identity)
            self.assertEqual(2, syncs)
            self.assertIn(b"CORRUPTED", output.read_bytes())

    def test_truncated_reply_receipt_explicitly_not_complete(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"

            def truncated(_args):
                print("Vera [incomplete reply]> unfinished thought")
                return 0

            with patch.object(preflight.local_session, "main", side_effect=truncated), \
                    redirect_stdout(io.StringIO()):
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "Hi",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(0, code)
            receipt = json.loads(output.read_text())
            self.assertFalse(receipt["reply_complete"])
            self.assertIn("TRUNCATED", receipt["status"])

    def test_existing_receipt_refuses_before_inference_without_overwrite(self):
        tags, ps = inventory(resident=True)
        getter, paths = fake_getter(tags, ps)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"
            output.write_text("FOREIGN_RECEIPT")
            with patch.object(preflight.local_session, "main",
                              side_effect=AssertionError("model launched")), \
                    redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "Hi",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(2, code)
            self.assertEqual("FOREIGN_RECEIPT", output.read_text())
            self.assertEqual([], paths)

    def test_failed_or_ambiguous_session_cannot_publish_success_receipt(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"

            def failed(_args):
                print("UNRELATED_INCOMPLETE_OUTPUT")
                return 2

            with patch.object(preflight.local_session, "main", side_effect=failed), \
                    redirect_stderr(io.StringIO()) as stderr, \
                    redirect_stdout(io.StringIO()):
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "Hi",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(2, code)
            self.assertFalse(output.exists())
            self.assertIn("call count unknown", stderr.getvalue())

    def test_foreign_final_race_preserves_foreign_bytes_and_refuses(self):
        tags, ps = inventory(resident=True)
        getter, _ = fake_getter(tags, ps)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trial.json"

            def raced_link(source, target, **_kwargs):
                Path(target).write_text("FOREIGN_RACE_WINNER")
                raise FileExistsError("receipt contested")

            def local_reply(_args):
                print("Vera> synthetic result")
                return 0

            with patch.object(preflight.local_session, "main", side_effect=local_reply), \
                    patch.object(preflight.os, "link", side_effect=raced_link), \
                    redirect_stderr(io.StringIO()) as stderr, \
                    redirect_stdout(io.StringIO()):
                code = preflight.main([
                    "--execute", "--host-idle-confirmed", "--prompt", "Hi",
                    "--receipt-output", str(output)],
                    memory_probe=lambda: 2 * preflight.GIB, get_json=getter)
            self.assertEqual(2, code)
            self.assertEqual("FOREIGN_RACE_WINNER", output.read_text())
            self.assertIn("model call already attempted", stderr.getvalue())
            self.assertEqual(1, len(list(Path(directory).glob("*.incomplete"))))

    def test_receipt_path_requires_absolute_non_symlink_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(preflight.PreflightRefused, "absolute"):
                preflight._receipt_target(Path("relative.json"))
            with self.assertRaisesRegex(preflight.PreflightRefused, "parent aliases"):
                preflight._receipt_target(Path(directory) / ".." / "trial.json")
            alias = Path(directory) / "alias"
            try:
                alias.symlink_to(Path(directory), target_is_directory=True)
            except OSError:
                self.skipTest("host cannot create directory symlinks")
            with self.assertRaisesRegex(preflight.PreflightRefused, "symlink or reparse"):
                preflight._receipt_target(alias / "trial.json")

    def test_parent_lexical_resolution_text_never_controls_custody(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "trial.json"
            # A valid Windows 8.3 alias resolves to a different textual
            # spelling; Path.resolve must not be a custody decision at all.
            with patch.object(Path, "resolve", side_effect=AssertionError("lexical check")):
                parent, identity = preflight._receipt_target(target)
            self.assertEqual(target.parent, parent)
            self.assertEqual(2, len(identity))

    @unittest.skipUnless(sys.platform == "win32", "requires real Windows short paths")
    def test_windows_8dot3_short_parent_is_accepted_when_not_reparse(self):
        with tempfile.TemporaryDirectory(prefix="mini-vera-receipt-shortalias-") as directory:
            buffer = ctypes.create_unicode_buffer(32768)
            count = ctypes.windll.kernel32.GetShortPathNameW(
                str(directory), buffer, len(buffer))
            if not count or count >= len(buffer):
                self.skipTest("Windows short-path alias unavailable")
            short_parent = Path(buffer.value)
            if str(short_parent).casefold() == str(directory).casefold():
                self.skipTest("8.3 naming disabled on this test volume")
            parent, identity = preflight._receipt_target(short_parent / "trial.json")
            self.assertEqual(short_parent, parent)
            self.assertEqual(2, len(identity))

    def test_symlinked_ancestor_is_rejected_even_when_parent_is_real_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            nested = real / "nested"
            nested.mkdir(parents=True)
            alias = Path(directory) / "alias"
            try:
                alias.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("host cannot create directory symlinks")
            self.assertFalse((alias / "nested").is_symlink())
            with self.assertRaisesRegex(preflight.PreflightRefused, "symlink or reparse"):
                preflight._receipt_target(alias / "nested" / "trial.json")

    def test_windows_reparse_flag_on_nonfinal_ancestor_is_rejected(self):
        # Model Windows junction/reparse metadata on every platform, including
        # Linux CI where st_file_attributes is normally absent. A reparse
        # ancestor must be rejected even if its final child is a plain dir.
        with tempfile.TemporaryDirectory() as directory:
            marked = Path(directory) / "junction-like"
            ordinary_child = marked / "ordinary-child"
            ordinary_child.mkdir(parents=True)
            target = ordinary_child / "trial.json"
            real_lstat = preflight.os.lstat
            visited = []

            def synthetic_reparse_ancestor(path):
                visited.append(Path(path))
                observed = real_lstat(path)
                if Path(path) == marked:
                    return SimpleNamespace(st_mode=observed.st_mode,
                                           st_file_attributes=0x400)
                return observed

            with patch.object(preflight.os, "lstat", side_effect=synthetic_reparse_ancestor):
                with self.assertRaisesRegex(preflight.PreflightRefused, "symlink or reparse"):
                    preflight._receipt_target(target)
            self.assertIn(ordinary_child, visited)
            self.assertIn(marked, visited)


if __name__ == "__main__":
    unittest.main()
