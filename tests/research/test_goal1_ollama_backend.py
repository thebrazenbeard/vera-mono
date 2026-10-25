"""Source-only gateway model adapter contract tests. No network or secrets."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from research.goal1_gateway.ollama_backend import OllamaMeasuredBackend
from research.goal1_gateway.sole_route import GatewayAttemptStore, GatewayDispatch, GatewayHold, verify_terminal
from tests.research.test_goal1_sole_route import Endpoint, Signer, fixture_reservation, helper

MODEL = "qwen3:4b-instruct"
DIGEST = "a" * 64

class Response:
    status = 200
    def __init__(self, obj):
        self.data = json.dumps(obj).encode()
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def read(self, n): return self.data[:n]

class FakeOpener:
    def __init__(self):
        self.calls = []
        self.registry = DIGEST
        self.registry_after_generate = None
        self.did_generate = False
        self.reply = {
            "model": MODEL, "done": True, "response": "OK",
            "prompt_eval_count": 3, "eval_count": 2,
            "total_duration": 17000000
        }
    def open(self, request, timeout):
        self.calls.append((request.get_method(), request.full_url))
        if request.get_method() == "GET":
            digest = (self.registry_after_generate if self.did_generate and
                      self.registry_after_generate is not None else self.registry)
            return Response({"models": [{"name":MODEL, "digest":digest}]})
        self.did_generate = True
        return Response(self.reply)

class MeasuredBackendTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOpener()
        self.backend = OllamaMeasuredBackend(model=MODEL, registry_digest=DIGEST,
                                             opener=self.fake)
    def test_measured_positive(self):
        observed = self.backend.generate("inert", model=MODEL, max_tokens=2)
        self.assertEqual((observed.text, observed.prompt_tokens, observed.output_tokens,
                          observed.backend_wall_ms), ("OK",3,2,17))
        self.assertEqual([method for method,_ in self.fake.calls],["GET","POST","GET"])
        self.assertTrue(all(url.startswith("http://127.0.0.1:11434/") for _,url in self.fake.calls))
    def test_model_mismatch_prevents_any_network(self):
        with self.assertRaises(GatewayHold):
            self.backend.generate("inert",model="other",max_tokens=2)
        self.assertEqual(self.fake.calls,[])
    def test_registry_mismatch_stops_before_post(self):
        self.fake.registry="b"*64
        with self.assertRaises(GatewayHold):
            self.backend.generate("inert",model=MODEL,max_tokens=2)
        self.assertEqual([x[0] for x in self.fake.calls],["GET"])
    def test_registry_drift_after_generation_fails_closed(self):
        self.fake.registry_after_generate = "b" * 64
        with self.assertRaisesRegex(GatewayHold, "registry digest mismatch"):
            self.backend.generate("inert", model=MODEL, max_tokens=2)
        self.assertEqual([method for method,_ in self.fake.calls], ["GET", "POST", "GET"])
    def test_gateway_cannot_sign_completion_after_registry_drift(self):
        self.fake.registry_after_generate = "b" * 64
        with tempfile.TemporaryDirectory(prefix="goal1-registry-drift-") as directory:
            store = GatewayAttemptStore(Path(directory) / "gateway.sqlite")
            signer = Signer()
            gateway = GatewayDispatch(store=store, gateway_id="gateway1",
                                      endpoint_client=Endpoint(), claim_authorization=helper,
                                      backend=self.backend, signer=signer)
            reservation = fixture_reservation(prompt="test prompt")
            with self.assertRaisesRegex(GatewayHold, "registry digest mismatch"):
                gateway.execute(reservation=reservation, invocation_id="inv1",
                                prompt="test prompt", max_tokens=2)
            terminal = store.signed_terminal("inv1")
            payload = json.loads(terminal.payload_bytes)
            self.assertEqual(terminal.status, "OUTCOME_UNKNOWN")
            self.assertIsNone(payload["response_sha256"])
            self.assertTrue(verify_terminal(payload, terminal.signature,
                            pinned_public_key=signer.public(), expected_key_id=signer.key_id))
            with self.assertRaises(GatewayHold):
                gateway.execute(reservation=reservation, invocation_id="inv2",
                                prompt="test prompt", max_tokens=2)
            self.assertEqual([method for method,_ in self.fake.calls], ["GET", "POST", "GET"])
    def test_usage_unavailable_is_not_signed_completion(self):
        del self.fake.reply["eval_count"]
        with self.assertRaises(GatewayHold):
            self.backend.generate("inert",model=MODEL,max_tokens=2)
    def test_overbudget_provider_response_rejected(self):
        self.fake.reply["eval_count"]=3
        with self.assertRaises(GatewayHold):
            self.backend.generate("inert",model=MODEL,max_tokens=2)
    def test_redirects_never_allowed(self):
        from research.goal1_gateway.ollama_backend import _NoRedirect
        with self.assertRaises(GatewayHold):
            _NoRedirect().redirect_request(None,None,302,"",{}, "http://evil/")
if __name__=="__main__":unittest.main()
