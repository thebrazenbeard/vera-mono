"""Bounded real-loopback tests; the HTTP peer is synthetic, not model proof."""

from __future__ import annotations

from contextlib import contextmanager
import gc
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
import unittest

from vera_assurance import EffectFenceError
from vera_core import (
    HmacProviderAuthority,
    LocalOllamaProviderTransport,
    OutboundAuthorityError,
    QualifiedVeraRuntime,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


MODEL = "test-model:latest"
DIGEST = "a" * 64
PROVIDER = "local-ollama"


@contextmanager
def loopback_peer():
    observed = []
    config = {"model": MODEL, "digest": DIGEST, "response": "candidate only",
              "raw_json": None, "rotate_digest_on_post": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            observed.append(("GET", self.path, None))
            payload = {"models": [{"name": config["model"], "digest": config["digest"]}]}
            self._send(payload)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(("POST", self.path, body))
            if config["rotate_digest_on_post"]:
                config["digest"] = "b" * 64
            self._send({"model": config["model"], "response": config["response"], "done": True})

        def _send(self, data):
            raw = (config["raw_json"].encode() if config["raw_json"] is not None
                   else json.dumps(data).encode())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, observed, config
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def accepted_state(base: Path):
    state = VeraStateDirectory(base / "state", project_id="vera-mono", identity_id="vera")
    lifecycle = state.open()
    request = AdmissionRequest(
        record_id="m-local",
        text="synthetic local transport bootstrap",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test", authority_ref="authority:test", privacy_ref="privacy:test",
        provenance_refs=("source:test",), operation_id="op-local",
        project_id="vera-mono", governed_identity_id="vera",
    )
    admitted = lifecycle.memory.admit(request, expected_head=lifecycle.memory.current_head)
    lifecycle.checkpoint(
        checkpoint_id="cp-local", runtime_id="runtime-local",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


class LocalOllamaProviderTransportTests(unittest.TestCase):
    def _state_directory(self) -> Path:
        # unittest cleanups run after test locals (runtime/store references) leave
        # scope. On Windows, sqlite files cannot be unlinked while a connection
        # awaiting collection still owns an OS file handle.
        temporary = tempfile.TemporaryDirectory()

        def cleanup() -> None:
            gc.collect()
            temporary.cleanup()

        self.addCleanup(cleanup)
        return Path(temporary.name)

    def test_no_host_authority_verifier_denies_transport_at_composition(self):
        with loopback_peer() as (port, observed, _):
            state = accepted_state(self._state_directory())
            transport = LocalOllamaProviderTransport(model=MODEL, registry_digest=DIGEST, port=port)
            with self.assertRaisesRegex(ValueError, "trusted provider authority verifier"):
                QualifiedVeraRuntime.from_state_directory(
                    state, provider_execution_transports={PROVIDER: transport},
                )
            self.assertEqual(observed, [])

    def test_malformed_generation_output_rejects_candidate(self):
        with loopback_peer() as (port, observed, config):
            transport = LocalOllamaProviderTransport(model=MODEL, registry_digest=DIGEST, port=port)
            config["response"] = ""
            with self.assertRaises(RuntimeError):
                transport.execute("GENERATE_CANDIDATE", {
                    "prompt": "hello", "model": MODEL,
                    "registry_digest": DIGEST, "port": port, "max_tokens": 8,
                })
            self.assertEqual([m for m, _, _ in observed], ["GET", "POST"])

    def test_returned_text_and_digest_are_the_same_canonical_bytes(self):
        with loopback_peer() as (port, _, config):
            transport = LocalOllamaProviderTransport(model=MODEL, registry_digest=DIGEST, port=port)
            config["response"] = "  candidate only  "
            result = transport.execute("GENERATE_CANDIDATE", {
                "prompt": "hello", "model": MODEL, "registry_digest": DIGEST,
                "port": port, "max_tokens": 8,
            })
            self.assertEqual(result["text"], "candidate only")
            self.assertEqual(result["response_sha256"], sha256(result["text"].encode()).hexdigest())

    def test_invalid_host_selection_rejected_before_network(self):
        for config in (
            {"model": "-bad", "registry_digest": DIGEST},
            {"model": MODEL, "registry_digest": "fake"},
            {"model": MODEL, "registry_digest": DIGEST, "port": True},
            {"model": MODEL, "registry_digest": DIGEST, "provider_id": "arbitrary"},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                LocalOllamaProviderTransport(**config)

    def test_invalid_request_or_model_selection_prevents_post(self):
        with loopback_peer() as (port, observed, config):
            transport = LocalOllamaProviderTransport(model=MODEL, registry_digest=DIGEST, port=port)
            with self.assertRaises(ValueError):
                transport.execute("GENERATE_CANDIDATE", {"prompt": "hello", "max_tokens": 8})
            self.assertEqual(observed, [])
            with self.assertRaises(ValueError):
                transport.execute("GENERATE_CANDIDATE", {
                    "prompt": "hello", "model": MODEL, "registry_digest": DIGEST,
                    "port": port + 1, "max_tokens": 8,
                })
            self.assertEqual(observed, [])
            config["digest"] = "b" * 64
            with self.assertRaises(RuntimeError):
                transport.execute("GENERATE_CANDIDATE", {
                    "prompt": "hello", "model": MODEL, "registry_digest": DIGEST,
                    "port": port, "max_tokens": 8,
                })
            self.assertEqual([m for m, _, _ in observed], ["GET"])

    def test_registry_identity_change_during_generation_denies_candidate(self):
        with loopback_peer() as (port, observed, config):
            transport = LocalOllamaProviderTransport(model=MODEL, registry_digest=DIGEST, port=port)
            config["rotate_digest_on_post"] = True
            with self.assertRaisesRegex(RuntimeError, "selected model registry identity changed"):
                transport.execute("GENERATE_CANDIDATE", {
                    "prompt": "hello", "model": MODEL, "registry_digest": DIGEST,
                    "port": port, "max_tokens": 8,
                })
            self.assertEqual([m for m, _, _ in observed], ["GET", "POST", "GET"])

    def test_qualified_runtime_marks_post_generation_drift_unknown_and_denies_replay(self):
        with loopback_peer() as (port, observed, config):
            state = accepted_state(self._state_directory())
            verifier = HmacProviderAuthority("test-issuer", PROVIDER, b"p" * 32)
            state.outbound_trust_registry().register(
                authority_id=verifier.authority_id, role="PROVIDER", provider_id=PROVIDER,
                key_id=verifier.key_id, key_digest=verifier.key_digest,
                expected_registry_generation=0,
            )
            transport = LocalOllamaProviderTransport(model=MODEL, registry_digest=DIGEST, port=port)
            runtime = QualifiedVeraRuntime.from_state_directory(
                state, provider_authority_verifiers={PROVIDER: verifier},
                provider_execution_transports={PROVIDER: transport},
            )
            prepared = runtime.prepare_provider_effect(
                effect_id="candidate-drift", provider_id=PROVIDER,
                operation="GENERATE_CANDIDATE",
                request_payload={"prompt": "hello", "model": MODEL,
                                 "registry_digest": DIGEST, "port": port, "max_tokens": 8},
            )
            authority = verifier.issue(
                effect_id=prepared.effect_id, operation=prepared.operation,
                request_digest=prepared.request_digest,
                lifecycle_permit_digest=prepared.permit.permit_digest,
            )
            config["rotate_digest_on_post"] = True
            with self.assertRaisesRegex(RuntimeError, "selected model registry identity changed"):
                runtime.execute_provider_effect(prepared, authority=authority)
            self.assertEqual([m for m, _, _ in observed], ["GET", "POST", "GET"])

            reopened = QualifiedVeraRuntime.from_state_directory(
                state, provider_authority_verifiers={PROVIDER: verifier},
                provider_execution_transports={PROVIDER: transport},
            )
            assessment = reopened.assess_provider_effect("candidate-drift")
            self.assertEqual(assessment.fence_state, "ATTEMPTED_UNKNOWN")
            self.assertTrue(assessment.recovery_required)
            self.assertFalse(assessment.dispatch_candidate_allowed)
            with self.assertRaises(EffectFenceError):
                reopened.execute_provider_effect(prepared, authority=authority)
            self.assertEqual([m for m, _, _ in observed], ["GET", "POST", "GET"])

    def test_ambiguous_or_nonfinite_registry_json_prevents_generation(self):
        valid = '{"models":[{"name":"test-model:latest","digest":"' + DIGEST + '"}]}'
        malformed = (
            valid[:-1] + ',"models":[]}',
            valid[:-1] + ',"unexpected":NaN}',
            valid[:-1] + ',"unexpected":Infinity}',
            valid[:-1] + ',"unexpected":1e9999}',
        )
        for raw in malformed:
            with self.subTest(raw=raw), loopback_peer() as (port, observed, config):
                config["raw_json"] = raw
                transport = LocalOllamaProviderTransport(model=MODEL, registry_digest=DIGEST, port=port)
                with self.assertRaises(RuntimeError):
                    transport.execute("GENERATE_CANDIDATE", {
                        "prompt": "hello", "model": MODEL,
                        "registry_digest": DIGEST, "port": port, "max_tokens": 8,
                    })
                self.assertEqual([m for m, _, _ in observed], ["GET"])

    def test_authorized_qualified_runtime_candidate_is_unverified_and_one_use(self):
        with loopback_peer() as (port, observed, _):
            state = accepted_state(self._state_directory())
            verifier = HmacProviderAuthority("test-issuer", PROVIDER, b"p" * 32)
            state.outbound_trust_registry().register(
                authority_id=verifier.authority_id, role="PROVIDER", provider_id=PROVIDER,
                key_id=verifier.key_id, key_digest=verifier.key_digest,
                expected_registry_generation=0,
            )
            transport = LocalOllamaProviderTransport(model=MODEL, registry_digest=DIGEST, port=port)
            runtime = QualifiedVeraRuntime.from_state_directory(
                state, provider_authority_verifiers={PROVIDER: verifier},
                provider_execution_transports={PROVIDER: transport},
            )
            request = {"prompt": "Only a candidate", "model": MODEL,
                       "registry_digest": DIGEST, "port": port, "max_tokens": 8}
            prepared = runtime.prepare_provider_effect(
                effect_id="candidate-one", provider_id=PROVIDER,
                operation="GENERATE_CANDIDATE", request_payload=request,
            )
            authority = verifier.issue(
                effect_id=prepared.effect_id, operation=prepared.operation,
                request_digest=prepared.request_digest,
                lifecycle_permit_digest=prepared.permit.permit_digest,
            )
            output = runtime.execute_provider_effect(prepared, authority=authority).value
            self.assertEqual(output["text"], "candidate only")
            self.assertEqual(output["kind"], "UNVERIFIED_LOCAL_MODEL_CANDIDATE")
            self.assertEqual(output["model_identity_level"], "REGISTRY_SELF_REPORTED")
            self.assertFalse(output["qualified"])
            self.assertEqual([m for m, _, _ in observed], ["GET", "POST", "GET"])

            reopened = QualifiedVeraRuntime.from_state_directory(
                state, provider_authority_verifiers={PROVIDER: verifier},
                provider_execution_transports={PROVIDER: transport},
            )
            self.assertTrue(reopened.assess_provider_effect("candidate-one").terminal)
            with self.assertRaisesRegex(OutboundAuthorityError, "exact request and lifecycle permit"):
                reopened.execute_provider_effect(prepared, authority=authority)
            self.assertEqual([m for m, _, _ in observed], ["GET", "POST", "GET"])


if __name__ == "__main__":
    unittest.main()
