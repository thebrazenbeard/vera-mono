"""0.8B preflight: real read-only HTTP, synthetic inventories and no model load."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import threading
import time
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


if __name__ == "__main__":
    unittest.main()
