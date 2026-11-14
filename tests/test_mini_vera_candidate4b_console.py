"""Opt-in candidate 4B local console: explicit tag binding and host RAM guard."""
import contextlib
import io
import unittest
from unittest import mock

from tools.mini_vera import conversation_console as console
from tools.mini_vera import ollama_preflight as preflight

MODEL = "mini-vera-hauhau-q4:source-probe-20261114"
DIGEST = "b" * 64
SIZE = 2_707_513_696

def inventory(*, resident=False, foreign=False, digest=DIGEST, size=SIZE):
    tags = {"models": [{"name": MODEL, "digest": digest, "size": size}]}
    ps = {"models": [{"name": MODEL, "digest": digest}] if resident else []}
    if foreign:
        ps["models"].append({"name": "foreign:latest", "digest": "a" * 64})
    return tags, ps

def getter_for(tags, ps):
    calls = []
    def read(_host, _port, path):
        calls.append(path)
        return tags if path == "/api/tags" else ps
    return read, calls

class Candidate4BPreflightTests(unittest.TestCase):
    def test_original_08b_guard_remains_default(self):
        tags, ps = inventory()
        read, calls = getter_for(tags, ps)
        with self.assertRaisesRegex(preflight.PreflightRefused, "over 0.8B"):
            preflight.probe(model=MODEL, expected_tag_digest=DIGEST,
                            memory_probe=lambda: 20 * preflight.GIB,
                            get_json=read, allow_cold_load=True)
        self.assertEqual(["/api/tags", "/api/ps"], calls)

    def test_explicit_candidate_requires_pin_before_network(self):
        tags, ps = inventory()
        read, calls = getter_for(tags, ps)
        with self.assertRaisesRegex(preflight.PreflightRefused, "explicit.*digest"):
            preflight.probe(model=MODEL, allow_4b_candidate=True,
                            memory_probe=lambda: 20 * preflight.GIB,
                            get_json=read, allow_cold_load=True)
        self.assertEqual([], calls)

    def test_explicit_candidate_passes_only_with_large_headroom(self):
        tags, ps = inventory()
        read, calls = getter_for(tags, ps)
        result = preflight.probe(model=MODEL, expected_tag_digest=DIGEST,
                                 allow_4b_candidate=True,
                                 memory_probe=lambda: 9 * preflight.GIB,
                                 get_json=read, allow_cold_load=True)
        self.assertEqual("RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE", result["status"])
        self.assertEqual("MINI_VERA_CANDIDATE4B_PREFLIGHT_V1", result["schema"])
        self.assertEqual("CANDIDATE_4B_UNQUALIFIED", result["model_class"])
        self.assertGreaterEqual(result["required_physical_ram_bytes"],
                                SIZE + 5 * preflight.GIB)
        self.assertEqual(["/api/tags", "/api/ps"], calls)
        self.assertFalse(result["exclusive_host_lease"])
        self.assertEqual(0, result["model_inference_calls"])

    def test_low_ram_or_mid_probe_drop_refuses(self):
        tags, ps = inventory()
        read, _ = getter_for(tags, ps)
        for readings in ((7 * preflight.GIB, 7 * preflight.GIB),
                         (9 * preflight.GIB, 6 * preflight.GIB)):
            with self.subTest(readings=readings):
                samples = iter(readings)
                with self.assertRaisesRegex(preflight.PreflightRefused, "insufficient"):
                    preflight.probe(model=MODEL, expected_tag_digest=DIGEST,
                                    allow_4b_candidate=True,
                                    memory_probe=lambda: next(samples),
                                    get_json=read, allow_cold_load=True)

    def test_oversize_foreign_resident_and_wrong_pin_refuse(self):
        for case in ("oversized", "foreign", "wrong_digest"):
            with self.subTest(case=case):
                tags, ps = inventory(
                    resident=case == "foreign",
                    foreign=case == "foreign",
                    size=4 * preflight.GIB if case == "oversized" else SIZE)
                read, _ = getter_for(tags, ps)
                with self.assertRaises(preflight.PreflightRefused):
                    preflight.probe(
                        model=MODEL, expected_tag_digest=("c" * 64 if case == "wrong_digest" else DIGEST),
                        allow_4b_candidate=True, allow_cold_load=True,
                        memory_probe=lambda: 20 * preflight.GIB, get_json=read)

    def test_warm_candidate_also_needs_free_ram(self):
        tags, ps = inventory(resident=True)
        read, _ = getter_for(tags, ps)
        with self.assertRaisesRegex(preflight.PreflightRefused, "insufficient"):
            preflight.probe(model=MODEL, expected_tag_digest=DIGEST,
                            allow_4b_candidate=True, memory_probe=lambda: 1 * preflight.GIB,
                            get_json=read)

class Candidate4BConsoleTests(unittest.TestCase):
    def invoke(self, args, reports):
        with mock.patch.object(console.ollama_preflight, "probe",
                               side_effect=reports) as check, \
             mock.patch.object(console.local_session, "main", return_value=0) as launch, \
             contextlib.redirect_stderr(io.StringIO()):
            result = console.main(args)
        return result, check, launch

    def test_candidate_requires_explicit_digest_and_host_consent(self):
        with mock.patch.object(console.ollama_preflight, "probe") as check, \
             mock.patch.object(console.local_session, "main") as launch, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, console.main(["--candidate-4b", "--check", "--model", MODEL]))
            self.assertEqual(2, console.main(["--candidate-4b", "--model", MODEL,
                                             "--expected-tag-digest", DIGEST]))
        check.assert_not_called()
        launch.assert_not_called()

    def test_candidate_rechecks_inventory_before_handoff(self):
        good = {"schema": "MINI_VERA_CANDIDATE4B_PREFLIGHT_V1",
                "status": "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE",
                "model_class": "CANDIDATE_4B_UNQUALIFIED",
                "model": MODEL, "ollama_tag_digest": DIGEST,
                "model_size_bytes": SIZE}
        args = ["--candidate-4b", "--model", MODEL, "--expected-tag-digest", DIGEST,
                "--confirm-host-idle", "--allow-cold-load", "--compact-dialogue",
                "--max-output-tokens", "128", "--prompt", "Hello"]
        code, check, launch = self.invoke(args, [good, dict(good)])
        self.assertEqual(0, code)
        self.assertEqual(2, check.call_count)
        self.assertTrue(all(c.kwargs["allow_4b_candidate"] for c in check.call_args_list))
        self.assertIn("--compact-dialogue", launch.call_args.args[0])

    def test_recheck_digest_change_denies_model_launch(self):
        good = {"schema": "MINI_VERA_CANDIDATE4B_PREFLIGHT_V1",
                "status": "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE",
                "model_class": "CANDIDATE_4B_UNQUALIFIED",
                "model": MODEL, "ollama_tag_digest": DIGEST,
                "model_size_bytes": SIZE}
        changed = dict(good, ollama_tag_digest="c" * 64)
        args = ["--candidate-4b", "--model", MODEL, "--expected-tag-digest", DIGEST,
                "--confirm-host-idle", "--allow-cold-load", "--max-output-tokens", "128"]
        code, _, launch = self.invoke(args, [good, changed])
        self.assertEqual(2, code)
        launch.assert_not_called()

    def test_08b_preflight_receipt_cannot_authorize_candidate_mode(self):
        tiny = {"schema": "MINI_VERA_08B_PREFLIGHT_V1",
                "status": "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE",
                "model": MODEL, "ollama_tag_digest": DIGEST, "model_size_bytes": SIZE}
        args = ["--candidate-4b", "--model", MODEL, "--expected-tag-digest", DIGEST,
                "--confirm-host-idle", "--allow-cold-load", "--max-output-tokens", "128"]
        code, _, launch = self.invoke(args, [tiny])
        self.assertEqual(2, code)
        launch.assert_not_called()

    def test_256_output_tokens_refused_before_network(self):
        with mock.patch.object(console.ollama_preflight, "probe") as check, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, console.main(["--candidate-4b", "--model", MODEL,
                "--expected-tag-digest", DIGEST, "--confirm-host-idle",
                "--max-output-tokens", "256"]))
        check.assert_not_called()

if __name__ == "__main__":
    unittest.main()
