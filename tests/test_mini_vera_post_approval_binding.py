"""A self-hashed synthetic record alone cannot authorize a positive client fact."""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import io
import json
from pathlib import Path
import tempfile
import unittest

from tests.test_mini_vera_loopback import FakeLocal, response
from tools.mini_vera import compose, local_session, public_fact_guard as gate
from tools.mini_vera import varied_public_canary as varied
from tools.mini_vera.live_ledger import approved_ledger_provider


class PostApprovalBindingTests(unittest.TestCase):
    def source(self, variant="directory"):
        folder = tempfile.TemporaryDirectory(prefix="mini-vera-varied-")
        self.addCleanup(folder.cleanup)
        fixture = varied._fixture(Path(folder.name), variant)
        ledger = varied.MemoryLedger(
            fixture["ledger_path"], project_id="vera-mono", identity_id="vera")
        provider = approved_ledger_provider(
            ledger, record_ids=["varied-public"], expected_head=fixture["head"],
            expected_revision=8, integrity_key=varied.KEY,
            host_public_project_approval=lambda rec, head: varied._approval(
                rec, head, variant, fixture["public_sha256"]))
        state, key, rev = provider()
        identity, iraw = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, braw = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        request = local_session.compose_local_turn(
            text=fixture["question"], turn_id="synthetic-recheck",
            history=[], identity=identity, identity_raw=iraw,
            behavior=behavior, behavior_raw=braw, state=state, key=key,
            revision=rev, model="vera:local", model_digest="b"*64)
        result = {
            "schema": "MINI_VERA_LOCAL_OUTPUT_V1",
            "request_sha256": request["request_sha256"],
            "model": {
                "text": fixture["expected"],
                "status": "UNVERIFIED_LOCAL_MODEL_OUTPUT",
                "trust": "UNVERIFIED_GENERATIVE_TEXT",
            },
            "client": {"tool_actions_executed": 0, "tool_receipts": []},
        }
        return fixture, request, result, (state, key, rev), provider

    def test_direct_self_hash_cannot_authorize_positive_synthetic_fact(self):
        for variant in ("directory", "revision"):
            with self.subTest(variant=variant):
                fixture, req, out, binding, _ = self.source(variant)
                result = gate.apply(req, out)
                fg = result["client"]["fact_gate"]
                self.assertEqual("WITHHELD_NO_LIVE_SOURCE_BINDING", fg["status"])
                self.assertEqual("UNKNOWN", fg["client_answer"])
                self.assertFalse(fg["model_exact_source_match"])
                self.assertIsNone(result["model"]["text"])
                self.assertFalse(fg["host_issuer_qualified"])

    def test_exact_post_approval_state_binding_permits_source_consistent_fact(self):
        for variant in ("directory", "revision"):
            with self.subTest(variant=variant):
                fixture, req, out, binding, _ = self.source(variant)
                result = gate.apply(req, out, approved_state_binding=binding)
                fg = result["client"]["fact_gate"]
                self.assertEqual("SOURCE_MATCHED_SYNTHETIC_RECORD_NOT_HOST_ATTESTATION",
                                 fg["status"])
                self.assertEqual(fixture["expected"], fg["client_answer"])
                self.assertTrue(fg["model_exact_source_match"])
                self.assertEqual("POST_APPROVAL_STATE_CONSISTENT_NOT_HOST_ATTESTED",
                                 fg["source_binding"])
                self.assertFalse(fg["host_issuer_qualified"])

    def test_replaced_current_source_or_revision_with_fresh_mac_refuses(self):
        _, req, out, binding, _ = self.source()
        state, key, rev = binding
        for mutation in ("revision", "source", "key", "drop", "shape"):
            with self.subTest(mutation=mutation):
                altered = json.loads(json.dumps(state))
                bound_key = key
                new_rev = rev
                if mutation == "revision":
                    altered["revision"] += 1
                    new_rev += 1
                elif mutation == "source":
                    altered["records"][0]["text"] += " EXTRA"
                    altered["records"][0]["source_sha256"] = hashlib.sha256(
                        altered["records"][0]["text"].encode()).hexdigest()
                elif mutation == "key":
                    bound_key = b"d"*32
                elif mutation == "drop":
                    altered["records"] = []
                elif mutation == "shape":
                    altered["extra"] = True
                if mutation != "shape":
                    altered["hmac_sha256"] = hmac.new(
                        bound_key,
                        compose.canonical({k:v for k,v in altered.items()
                                           if k != "hmac_sha256"}),
                        hashlib.sha256).hexdigest()
                with self.assertRaises(gate.GuardRefused):
                    gate.apply(req, out, approved_state_binding=(
                        altered, bound_key, new_rev))

    def test_no_source_remains_safely_unknown_without_binding(self):
        _, req, _, _, _ = self.source()
        user = json.loads(req["inference"]["messages"][-1]["content"])
        user["project_context_untrusted"] = []
        # Build a valid no-memory request through its actual local session,
        # rather than editing the signed source envelope in place.
        empty, key = local_session.empty_public_state()
        identity, iraw = compose.read_object(compose.IDENTITY_PATH, 16384)
        behavior, braw = compose.read_object(compose.BEHAVIOR_PATH, 16384)
        request = local_session.compose_local_turn(
            text=user["local_user_turn"], turn_id="synthetic-empty",
            history=[], identity=identity, identity_raw=iraw,
            behavior=behavior, behavior_raw=braw,
            state=empty, key=key, revision=0,
            model="vera:local", model_digest="b"*64)
        fake = {
            "schema": "MINI_VERA_LOCAL_OUTPUT_V1",
            "request_sha256": request["request_sha256"],
            "model": {"text": "G-FAKE9999",
                      "status": "UNVERIFIED_LOCAL_MODEL_OUTPUT",
                      "trust": "UNVERIFIED_GENERATIVE_TEXT"},
            "client": {"tool_actions_executed": 0, "tool_receipts": []},
        }
        result = gate.apply(request, fake)
        self.assertEqual("WITHHELD_NO_APPROVED_REFERENCE",
                         result["client"]["fact_gate"]["status"])
        self.assertFalse(result["client"]["fact_gate"]["model_generated_abstention"])
        self.assertEqual("UNKNOWN", result["client"]["fact_gate"]["client_answer"])

    def test_live_provider_rechecked_after_http_allows_positive_only_while_stable(self):
        fixture, _, _, _, provider = self.source()
        for variant, expected in (("stable", 0), ("revoked", 2)):
            with self.subTest(variant=variant), FakeLocal(
                answer=response(model="vera:local", text=fixture["expected"])) as server:
                calls = 0
                def callback():
                    nonlocal calls
                    calls += 1
                    state, key, rev = provider()
                    if variant == "revoked" and calls > 1:
                        # Real host approval revoked after inference.
                        raise ValueError("approval revoked")
                    return state, key, rev
                output = io.StringIO()
                error = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    code = local_session.main([
                        "--endpoint", server.url, "--model", "vera:local",
                        "--model-digest", "b"*64, "--execute", "--host-idle-confirmed",
                        "--structured-output", "--synthetic-fact-evidence-gate",
                        "--prompt", fixture["question"]],live_public_provider=callback)
                self.assertEqual(expected, code)
                self.assertEqual(2, calls)
                self.assertEqual(1, len(server.requests))
                if variant == "stable":
                    result = json.loads(output.getvalue())
                    self.assertEqual(fixture["expected"],
                        result["client"]["fact_gate"]["client_answer"])
                else:
                    self.assertEqual("", output.getvalue())
                    self.assertIn("withheld", error.getvalue())
