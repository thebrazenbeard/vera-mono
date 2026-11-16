"""Host-embedded exact-ID output through the real local-session entrypoint.

These are disposable synthetic PUBLIC ledger records and test-host grants,
NOT user memory, production host identity or neural model qualification.
"""
from __future__ import annotations

from dataclasses import replace
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock

ROOT = Path(__file__).resolve().parents[1]
for package in ("vera_memory", "portfolio_runtime"):
    sys.path.insert(0, str(ROOT / "packages" / package / "src"))

from tests.test_mini_vera_source_bindings import KEY, ledger_fixture
from tools.mini_vera import conversation_console, local_session, loopback, ollama_preflight
from tools.mini_vera.host_memory_broker import PublicMemoryGrant, bind_host_public_memory


class HostExactSessionTests(TestCase):
    ARGS = [
        "--endpoint", "http://127.0.0.1:11434/v1",
        "--structured-output", "--prompt", "work-1",
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger, head = ledger_fixture(Path(self.tmp.name))
        self.grant = PublicMemoryGrant(
            project_id="vera-mono", identity_id="vera",
            ledger_head=head, revision=13, record_ids=("work-1",),
            record_digests=(("work-1", self.ledger.read("work-1").record_digest),),
            approval_epoch=1, authority_revision=10, expires_at_unix=1_000_600)
        self.auth_revision = 10
        self.floor = -1

    def provider(self):
        def advance(value):
            self.floor = max(self.floor, value)
            return self.floor
        return bind_host_public_memory(
            self.ledger, integrity_key=KEY,
            current_grant=lambda: self.grant,
            current_authority_revision=lambda: self.auth_revision,
            atomic_host_revision_floor=advance,
            approve_record=lambda record, grant: (
                record.record_id in grant.record_ids
                and record.privacy_ref == "PUBLIC"
                and record.authority_ref == "synthetic-approved"),
            now_seconds=lambda: 1_000_000)

    def invoke(self, argv=None, *, provider=None, record_id="work-1"):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(loopback, "execute", side_effect=AssertionError(
                "neural HTTP prohibited in source-only session")):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = local_session.main(
                    argv if argv is not None else self.ARGS,
                    live_public_provider=provider,
                    host_exact_record_id=record_id)
        return code, out.getvalue(), err.getvalue()

    def invoke_console(self, argv=None, *, provider=None, record_id="work-1"):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(ollama_preflight, "probe", side_effect=AssertionError(
                "source-only console must not preflight or cold-load neural model")):
            with mock.patch.object(loopback, "execute", side_effect=AssertionError(
                    "source-only console must not call neural HTTP")):
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = conversation_console.main(
                        argv if argv is not None else ["--prompt", record_id],
                        live_public_provider=provider,
                        host_exact_record_id=record_id)
        return code, out.getvalue(), err.getvalue()

    def test_host_entrypoint_types_resolve_for_host_integrators(self):
        from typing import get_type_hints
        for entrypoint in (conversation_console.main, local_session.main):
            annotations = get_type_hints(entrypoint)
            self.assertIn("live_public_provider", annotations)
            self.assertIn("host_exact_record_id", annotations)
    def test_normal_console_wrapper_returns_approved_source_without_model_preflight(self):
        code, out, err = self.invoke_console(provider=self.provider())
        self.assertEqual(0, code, err)
        record = json.loads(out)
        self.assertEqual("SOURCE_READ", record["status"])
        self.assertEqual("work-1", record["source"]["record_id"])
        self.assertEqual(0, record["model_http_calls"])
        self.assertFalse(record["host_issuer_qualified"])

    def test_console_wrapper_unknown_without_discovery(self):
        code, out, err = self.invoke_console(provider=self.provider(), record_id="unknown-id")
        self.assertEqual(0, code, err)
        record = json.loads(out)
        self.assertEqual("UNKNOWN", record["answer"])
        self.assertIsNone(record["source"])
        self.assertNotIn("work-1", out)

    def test_console_wrapper_refuses_revocation_between_reads(self):
        provider = self.provider()
        reads = [0]
        def revoked():
            state = provider()
            reads[0] += 1
            if reads[0] == 1:
                self.grant = None
            return state
        code, out, err = self.invoke_console(provider=revoked)
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("withheld", err.lower())

    def test_console_wrapper_rejects_privileged_cli_options(self):
        for extra in (
                ["--check"], ["--confirm-host-idle"], ["--allow-cold-load"],
                ["--compact-dialogue"], ["--candidate-4b"],
                ["--expected-tag-digest", "b"*64],
                ["--model", "another-model"]):
            with self.subTest(extra=extra):
                with self.assertRaises(SystemExit) as caught:
                    self.invoke_console(
                        ["--prompt", "work-1", *extra],
                        provider=self.provider())
                self.assertEqual(2, caught.exception.code)

    def test_approved_exact_id_returns_source_answer_without_any_model_dependency(self):
        code, out, err = self.invoke(provider=self.provider())
        self.assertEqual(0, code, err)
        record = json.loads(out)
        self.assertEqual("MINI_VERA_HOST_PUBLIC_EXACT_READ_V1", record["schema"])
        self.assertEqual("SOURCE_READ", record["status"])
        self.assertEqual("work-1", record["source"]["record_id"])
        self.assertEqual(
            "Synthetic public project milestone; not present-day truth.",
            record["answer"])
        self.assertEqual("HOST_SUPPLIED_APPROVED_PUBLIC_SOURCE_NOT_NEURAL",
                         record["origin"])
        self.assertEqual(0, record["model_http_calls"])
        self.assertEqual(0, record["writes"])
        self.assertFalse(record["host_issuer_qualified"])

    def test_unapproved_exact_id_returns_unknown_with_no_record_enumeration(self):
        argv = self.ARGS[:-1] + ["other-record"]
        code, out, err = self.invoke(argv, provider=self.provider(), record_id="other-record")
        self.assertEqual(0, code, err)
        result = json.loads(out)
        self.assertEqual("UNKNOWN", result["answer"])
        self.assertIsNone(result["source"])
        self.assertNotIn("work-1", out)
        self.assertNotIn("Synthetic public", out)

    def test_revocation_after_first_projection_refuses_without_output(self):
        provider = self.provider()
        reads = [0]
        def revoke():
            state = provider()
            reads[0] += 1
            if reads[0] == 1:
                self.grant = None
                self.auth_revision += 1
            return state
        code, out, err = self.invoke(provider=revoke)
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertEqual(1, reads[0])
        self.assertIn("withheld", err.lower())
        self.assertNotIn("Synthetic public", err)

    def test_grant_epoch_rotation_refuses_without_output(self):
        provider = self.provider()
        reads = [0]
        def rotate():
            state = provider()
            reads[0] += 1
            if reads[0] == 1:
                self.grant = replace(self.grant, approval_epoch=2)
            return state
        code, out, err = self.invoke(provider=rotate)
        self.assertEqual(2, code)
        self.assertEqual("", out)
        self.assertIn("withheld", err.lower())

    def test_absent_provider_and_question_mismatch_fail_before_neural_or_source(self):
        for argv, provider, rid in (
                (self.ARGS, None, "work-1"),
                (self.ARGS[:-1] + ["tell me everything"], self.provider(), "work-1"),
                (self.ARGS, self.provider(), "private/record"),
            ):
            with self.subTest(argv=argv, record_id=rid):
                with self.assertRaises(SystemExit) as caught:
                    self.invoke(argv, provider=provider, record_id=rid)
                self.assertEqual(2, caught.exception.code)

    def test_mixed_execute_import_and_model_settings_are_refused(self):
        variants = (
            ["--execute", "--host-idle-confirmed"],
            ["--model", "qwen3.5:0.8b", "--model-digest", "b"*64],
            ["--public-state", "C:\\no\\such\\file.json"],
            ["--synthetic-source-only"],
            ["--compact-dialogue"],
            ["--host-read-probe"],
            ["--ollama-disable-thinking"],
        )
        for flags in variants:
            with self.subTest(flags=flags):
                with self.assertRaises(SystemExit) as caught:
                    self.invoke(self.ARGS + flags, provider=self.provider())
                self.assertEqual(2, caught.exception.code)