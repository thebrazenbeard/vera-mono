"""QVR #82 networkless transport binding: no direct model socket selected."""
from __future__ import annotations
import hashlib
import importlib.util
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from research.goal1_acceptance_bridge import networkless_qvr_transport as mod

# PR #82 is delegated and intentionally not merged into our base PR.
# Test on physical hosts against frozen exact #82 source; on GitHub main the
# private optional owner branch is absent and cannot be presumed installed.
try:
    _HAS_QVR82 = importlib.util.find_spec("vera_core.local_cognition") is not None
except ModuleNotFoundError:
    _HAS_QVR82 = False


@unittest.skipUnless(_HAS_QVR82, "PR82 optional cognition source not in canonical main")
class QVRNetworklessTransportTests(unittest.TestCase):
    def setUp(self):
        from vera_core.local_cognition import InferencePermit, LocalTextReceipt
        self.Permit = InferencePermit
        self.Receipt = LocalTextReceipt
        self.permit = InferencePermit(
            model="qwen3:4b-instruct",digest="a"*64,
            scope="SYNTHETIC_LOCAL_INFERENCE_TEST")
        self.image="sha256:" + "b"*64
        self.calls=[]

    def callback(self, prompt, *, permit, max_tokens):
        self.calls.append((prompt,permit,max_tokens))
        return self.Receipt(
            text="synthetic QVR only", model=permit.model,
            reported_model_digest=permit.digest,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            response_sha256=hashlib.sha256(b"synthetic QVR only").hexdigest())

    def successful_sandbox(self, **kwargs):
        self.assertEqual(kwargs["prompt"],"qvr prompt")
        kwargs["gateway_callback"](kwargs["prompt"])
        return SimpleNamespace(
            isolation_observed=True,
            host_gateway_callback_called=True,
            gateway_effect_independently_verified=False,
            actual_selected_qvr_route_verified=False,
            learning_qualified=False,
            gateway_callback_result=self.calls and self.Receipt(
                text="synthetic QVR only",model=self.permit.model,
                reported_model_digest=self.permit.digest,
                prompt_sha256=hashlib.sha256(b"qvr prompt").hexdigest(),
                response_sha256=hashlib.sha256(b"synthetic QVR only").hexdigest()))

    def test_selected_interface_consumes_broker_receipt_without_local_provider(self):
        t=mod.NetworklessQVRTransport(
            image_id=self.image,model=self.permit.model,digest=self.permit.digest,
            host_gateway_callback=self.callback)
        with patch.object(mod,"run_networkless_learner_step",self.successful_sandbox):
            actual=t.generate("qvr prompt",permit=self.permit,max_tokens=6)
        self.assertIs(type(actual),self.Receipt)
        self.assertEqual(len(self.calls),1)
        self.assertFalse(actual.runtime_consumption_verified)
        self.assertFalse(actual.model_byte_identity_verified)

    def test_no_callback_before_bad_permit(self):
        t=mod.NetworklessQVRTransport(
            image_id=self.image,model=self.permit.model,digest=self.permit.digest,
            host_gateway_callback=self.callback)
        with patch.object(mod,"run_networkless_learner_step",
                          side_effect=AssertionError("sandbox must not run")):
            with self.assertRaises(mod.QVRCellBoundaryError):
                t.generate("qvr prompt",permit="not-permit",max_tokens=6)
        self.assertEqual(self.calls,[])

    def test_bad_gateway_response_is_not_qvr_receipt(self):
        t=mod.NetworklessQVRTransport(
            image_id=self.image,model=self.permit.model,digest=self.permit.digest,
            host_gateway_callback=self.callback)
        def wrong(**kwargs):
            return SimpleNamespace(
                isolation_observed=True,host_gateway_callback_called=True,
                gateway_effect_independently_verified=False,
                actual_selected_qvr_route_verified=False,
                learning_qualified=False,
                gateway_callback_result={"unverified":"text"})
        with patch.object(mod,"run_networkless_learner_step",wrong):
            with self.assertRaises(mod.QVRCellBoundaryError):
                t.generate("qvr prompt",permit=self.permit,max_tokens=6)
        self.assertEqual(self.calls,[])

    def test_claimed_independent_result_is_rejected_not_promoted(self):
        t=mod.NetworklessQVRTransport(
            image_id=self.image,model=self.permit.model,digest=self.permit.digest,
            host_gateway_callback=self.callback)
        def forged(**kwargs):
            kwargs["gateway_callback"](kwargs["prompt"])
            return SimpleNamespace(
                isolation_observed=True,host_gateway_callback_called=True,
                gateway_effect_independently_verified=True,
                actual_selected_qvr_route_verified=True,
                learning_qualified=True,
                gateway_callback_result=self.callback(
                    "qvr prompt",permit=self.permit,max_tokens=6))
        with patch.object(mod,"run_networkless_learner_step",forged):
            with self.assertRaises(mod.QVRCellBoundaryError):
                t.generate("qvr prompt",permit=self.permit,max_tokens=6)

    def test_wrong_response_digest_rejected_before_qvr_journal(self):
        t=mod.NetworklessQVRTransport(
            image_id=self.image,model=self.permit.model,digest=self.permit.digest,
            host_gateway_callback=self.callback)
        def wrong(**kwargs):
            kwargs["gateway_callback"](kwargs["prompt"])
            return SimpleNamespace(
                isolation_observed=True,host_gateway_callback_called=True,
                gateway_effect_independently_verified=False,
                actual_selected_qvr_route_verified=False,
                learning_qualified=False,
                gateway_callback_result=self.Receipt(
                    text="x",model=self.permit.model,
                    reported_model_digest=self.permit.digest,
                    prompt_sha256=hashlib.sha256(b"qvr prompt").hexdigest(),
                    response_sha256="0"*64))
        with patch.object(mod,"run_networkless_learner_step",wrong):
            with self.assertRaises(mod.QVRCellBoundaryError):
                t.generate("qvr prompt",permit=self.permit,max_tokens=6)


if __name__ == "__main__":
    unittest.main()
