"""Source-only consumer boundary; no independent custody or causal-use claim."""
from dataclasses import replace
import unittest

from rezon.cascade import CascadeEngine, LayerResult, LayerSpec, ReasoningRequest
from rezon.method_observation import (
    MethodExecutionEnvelope, MethodInvocationObserver, measured_function_bytecode_sha256,
)
from rezon.method_evaluation_join import MethodSelectionCommitment, DeclaredEvaluatorOutcome
from rezon.method_consumer_observation import (
    MethodConsumerObserver, DeclaredConsumerRoute,
)

HEAD = "16a2828dfa7fb7e6c0e19004f014bc68fc47badf"


def layer(request):
    return LayerResult(answer="grounded:" + request.prompt, unresolved=(), confidence=.8)


def consumer(result):
    return "used:" + str(result.answer)


def other_consumer(result):
    return "other:" + str(result.answer)


def crashing_consumer(result):
    raise RuntimeError("consumer failed")


class HostConsumerBoundary(unittest.TestCase):
    def run_method(self):
        envelope = MethodExecutionEnvelope(
            method_id="m", revision_id="r1", task_id="task-1",
            selected_source_head=HEAD,
            expected_bytecode_sha256=measured_function_bytecode_sha256(layer),
            execution_cut_id="cut", budget_id="bounded",
        )
        selection = MethodSelectionCommitment.before_invocation(
            envelope, ReasoningRequest("Q"), prediction_commitment_sha256="a"*64)
        observed = MethodInvocationObserver(envelope)
        # Real CascadeEngine executes wrapper, not merely declaring a method name.
        outcome = CascadeEngine((observed.bind_layer(LayerSpec("m", layer)),)).resolve("Q")
        invocation = observed.invocations[0]
        evaluator = DeclaredEvaluatorOutcome(
            task_id="task-1", execution_cut_id="cut", invocation_number=1,
            request_sha256=invocation.request_sha256,
            result_sha256=invocation.result_sha256,
            evaluator_id="claimed-judge", outcome_digest="b"*64, verdict="CORRECT")
        route = DeclaredConsumerRoute("host-caller", "local-process-attempt",
                                       measured_function_bytecode_sha256(consumer))
        return MethodConsumerObserver(selection, invocation, evaluator, route), LayerResult(
            outcome.answer, (), outcome.confidence)

    def test_real_consumption_call_and_conservative_qualifiers(self):
        observer, result = self.run_method()
        self.assertEqual(observer.observations, [])
        self.assertEqual(observer.consume(result, consumer), "used:grounded:Q")
        o = observer.observations[0]
        self.assertEqual((o.status, o.outcome), ("LOCAL_CONSUMER_CALL_ONLY", "RETURNED"))
        self.assertTrue(o.local_consumer_call_observed)
        for name in ("consumer_route_independently_verified", "consumer_semantic_use_verified",
                     "transitive_dependency_closure_measured", "mutable_closure_state_measured",
                     "evaluator_custody_verified", "precommit_timing_verified",
                     "qualified_runtime_consumption_verified", "cold_restart_reuse_verified"):
            self.assertFalse(getattr(o, name), name)
        self.assertEqual(o.authorization_effect, "NONE")

    def test_different_result_never_reaches_consumer(self):
        observer, result = self.run_method()
        with self.assertRaisesRegex(ValueError, "method result bytes"):
            observer.consume(replace(result, answer="spoofed"), consumer)
        self.assertEqual(observer.observations, [])

    def test_callable_substitution_fails_before_consumer(self):
        observer, result = self.run_method()
        with self.assertRaisesRegex(ValueError, "consumer callable code"):
            observer.consume(result, other_consumer)
        self.assertEqual(observer.observations, [])

    def test_consumer_failure_records_an_attempt_not_use(self):
        observer, result = self.run_method()
        observer.route = DeclaredConsumerRoute("host", "attempt-2",
            measured_function_bytecode_sha256(crashing_consumer))
        with self.assertRaisesRegex(RuntimeError, "consumer failed"):
            observer.consume(result, crashing_consumer)
        o = observer.observations[0]
        self.assertEqual(o.outcome, "RAISED")
        self.assertIsNone(o.consumer_result_sha256)
        self.assertFalse(o.consumer_semantic_use_verified)

    def test_closure_mutation_remains_unmeasured(self):
        observer, result = self.run_method()
        mutable = {"prefix":"A"}
        def dynamic(value):
            return mutable["prefix"] + str(value.answer)
        observer.route = DeclaredConsumerRoute("host", "attempt-3",
            measured_function_bytecode_sha256(dynamic))
        self.assertEqual(observer.consume(result, dynamic), "Agrounded:Q")
        mutable["prefix"] = "B"
        self.assertEqual(observer.consume(result, dynamic), "Bgrounded:Q")
        self.assertEqual(observer.observations[0].consumer_code_before_sha256,
                         observer.observations[1].consumer_code_before_sha256)
        self.assertNotEqual(observer.observations[0].consumer_result_sha256,
                            observer.observations[1].consumer_result_sha256)
        self.assertFalse(observer.observations[1].mutable_closure_state_measured)

    def test_mismatched_evaluator_is_rejected_by_prior_join(self):
        observer, result = self.run_method()
        self.assertEqual(observer.link.status, "STRUCTURAL_MATCH_ONLY")
        self.assertFalse(observer.link.evaluator_label_custody_verified)

if __name__ == "__main__":
    unittest.main()
