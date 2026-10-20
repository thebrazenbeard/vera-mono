import hashlib
import marshal
import unittest

from rezon.cascade import CascadeEngine, LayerResult, LayerSpec
from rezon.method_observation import (
    MethodExecutionEnvelope, MethodInvocationObserver,
    measured_function_bytecode_sha256,
)

HEAD = "16a2828dfa7fb7e6c0e19004f014bc68fc47badf"


def alpha(request):
    return LayerResult("alpha:" + request.prompt, (), .94, ("observed:test",))


def beta(request):
    return LayerResult("beta:" + request.prompt, (), .94, ("observed:test",))


def raises(request):
    raise RuntimeError("deliberate")


def envelope(fn):
    return MethodExecutionEnvelope(
        method_id="m", revision_id="v1", task_id="t", selected_source_head=HEAD,
        expected_bytecode_sha256=measured_function_bytecode_sha256(fn),
        execution_cut_id="synthetic-owner-test", budget_id="zero-tool-budget",
    )


class TestMethodObservation(unittest.TestCase):
    def test_invocation_is_observed_with_exact_input_output_not_merely_label(self):
        observer = MethodInvocationObserver(envelope(alpha))
        outcome = CascadeEngine((observer.bind_layer(LayerSpec("same-label", alpha)),)).resolve("p")
        self.assertEqual(outcome.answer, "alpha:p")
        self.assertEqual(len(observer.invocations), 1)
        receipt = observer.invocations[0]
        self.assertEqual(receipt.outcome, "RETURNED")
        self.assertEqual(receipt.method_id, "m")
        self.assertEqual(receipt.invocation_number, 1)
        self.assertEqual(receipt.code_before_sha256, measured_function_bytecode_sha256(alpha))
        self.assertIsNotNone(receipt.result_sha256)
        self.assertFalse(receipt.independent_execution_witness)
        self.assertFalse(receipt.dependency_closure_measured)
        self.assertEqual(receipt.authorization_effect, "NONE")

    def test_same_label_cannot_substitute_other_function(self):
        observer = MethodInvocationObserver(envelope(alpha))
        with self.assertRaisesRegex(ValueError, "expected bytecode"):
            observer.bind_layer(LayerSpec("same-label", beta))
        self.assertEqual(observer.invocations, [])

    def test_same_code_with_changed_closure_is_explicitly_unattested(self):
        state = {"answer": "A"}
        def choose(request):
            return LayerResult(state["answer"], (), .9)
        observer = MethodInvocationObserver(envelope(choose))
        wrapped = observer.bind_layer(LayerSpec("same-label", choose))
        self.assertEqual(CascadeEngine((wrapped,)).resolve("x").answer, "A")
        state["answer"] = "B"
        self.assertEqual(CascadeEngine((wrapped,)).resolve("x").answer, "B")
        self.assertEqual(observer.invocations[0].code_before_sha256,
                         observer.invocations[1].code_before_sha256)
        self.assertNotEqual(observer.invocations[0].result_sha256,
                            observer.invocations[1].result_sha256)
        self.assertFalse(observer.invocations[-1].mutable_state_measured)

    def test_exception_is_an_actual_attempt_not_success(self):
        observer = MethodInvocationObserver(envelope(raises))
        wrapped = observer.bind_layer(LayerSpec("fail", raises))
        with self.assertRaises(RuntimeError):
            CascadeEngine((wrapped,)).resolve("x")
        self.assertEqual(observer.invocations[0].outcome, "RAISED")
        self.assertEqual(observer.invocations[0].exception_type, "RuntimeError")
        self.assertIsNone(observer.invocations[0].result_sha256)

    def test_no_invocation_observation_without_execution(self):
        observer = MethodInvocationObserver(envelope(alpha))
        observer.bind_layer(LayerSpec("selected-but-never-called", alpha))
        self.assertEqual(observer.invocations, [])


if __name__ == "__main__":
    unittest.main()
