import hashlib
from dataclasses import replace
import unittest

from rezon.cascade import CascadeEngine, LayerResult, LayerSpec, ReasoningRequest
from rezon.method_observation import (
    MethodExecutionEnvelope, MethodInvocationObserver,
    measured_function_bytecode_sha256,
)
from rezon.method_evaluation_join import (
    DeclaredEvaluatorOutcome, MethodSelectionCommitment,
    join_method_evaluation,
)

SOURCE_HEAD = "16a2828dfa7fb7e6c0e19004f014bc68fc47badf"


def answer(request):
    return LayerResult("answer:" + request.prompt, (), .92, ("fixture:observed",))


def fails(request):
    raise RuntimeError("intentional test exception")


def make_envelope(fn, task_id="case-1"):
    return MethodExecutionEnvelope(
        method_id="reasoning.verify", revision_id="r1", task_id=task_id,
        selected_source_head=SOURCE_HEAD,
        expected_bytecode_sha256=measured_function_bytecode_sha256(fn),
        execution_cut_id="cut-a", budget_id="bounded-zero-tools",
    )


class MethodJoinTests(unittest.TestCase):
    def execute(self, fn=answer, task_id="case-1"):
        envelope = make_envelope(fn, task_id)
        request = ReasoningRequest(prompt="question")
        # Commitment is constructed BEFORE the callable is invoked.
        selection = MethodSelectionCommitment.before_invocation(
            envelope, request, prediction_commitment_sha256="a" * 64)
        observer = MethodInvocationObserver(envelope)
        layer = observer.bind_layer(LayerSpec("untrusted label", fn))
        CascadeEngine((layer,)).resolve(request.prompt)
        invocation = observer.invocations[0]
        evaluation = DeclaredEvaluatorOutcome(
            task_id=task_id, execution_cut_id="cut-a",
            invocation_number=1, request_sha256=invocation.request_sha256,
            result_sha256=invocation.result_sha256,
            evaluator_id="declared-judge", outcome_digest="b" * 64,
            verdict="CORRECT")
        return selection, invocation, evaluation

    def test_selection_invocation_evaluation_structurally_match(self):
        selected, observed, scored = self.execute()
        record = join_method_evaluation(selected, observed, scored)
        self.assertEqual(record.status, "STRUCTURAL_MATCH_ONLY")
        self.assertEqual(record.declared_verdict, "CORRECT")
        self.assertFalse(record.precommit_timing_verified)
        self.assertFalse(record.independent_execution_witness)
        self.assertFalse(record.evaluator_label_custody_verified)
        self.assertFalse(record.causal_improvement_verified)
        self.assertEqual(record.authorization_effect, "NONE")

    def test_selected_method_without_execution_has_no_join(self):
        envelope = make_envelope(answer)
        request = ReasoningRequest("question")
        selection = MethodSelectionCommitment.before_invocation(
            envelope, request, prediction_commitment_sha256="a" * 64)
        observer = MethodInvocationObserver(envelope)
        observer.bind_layer(LayerSpec("selected but not called", answer))
        self.assertEqual(observer.invocations, [])
        with self.assertRaises(TypeError):
            join_method_evaluation(selection, None, None)

    def test_evaluator_cannot_score_a_different_result(self):
        x, y, z = self.execute()
        with self.assertRaisesRegex(ValueError, "returned method result"):
            join_method_evaluation(x, y, replace(z, result_sha256="f" * 64))

    def test_evaluator_cannot_relabel_the_method_task_or_invocation(self):
        x, y, z = self.execute()
        with self.assertRaisesRegex(ValueError, "does not match selection"):
            join_method_evaluation(x, replace(y, method_id="other"), z)
        with self.assertRaisesRegex(ValueError, "does not address"):
            join_method_evaluation(x, y, replace(z, invocation_number=2))

    def test_forged_source_call_digest_or_committed_selection_held(self):
        x, y, z = self.execute()
        with self.assertRaisesRegex(ValueError, "selection commitment changed"):
            join_method_evaluation(replace(x, selection_sha256="f"*64), y, z)
        with self.assertRaisesRegex(ValueError, "request digest mismatch"):
            join_method_evaluation(x, replace(y, request_sha256="c"*64), z)

    def test_method_raised_is_not_a_scored_success(self):
        envelope = make_envelope(fails)
        request = ReasoningRequest("question")
        selection = MethodSelectionCommitment.before_invocation(
            envelope, request, prediction_commitment_sha256="a" * 64)
        observer = MethodInvocationObserver(envelope)
        with self.assertRaises(RuntimeError):
            CascadeEngine((observer.bind_layer(LayerSpec("thrower", fails)),)).resolve("question")
        attempt = observer.invocations[0]
        self.assertEqual(attempt.outcome, "RAISED")
        report = DeclaredEvaluatorOutcome(
            task_id="case-1", execution_cut_id="cut-a", invocation_number=1,
            request_sha256=attempt.request_sha256, result_sha256="d" * 64,
            evaluator_id="declared-judge", outcome_digest="e"*64,
            verdict="INCORRECT")
        with self.assertRaisesRegex(ValueError, "no matching returned"):
            join_method_evaluation(selection, attempt, report)

    def test_changed_mutable_state_and_fake_independence_never_qualify(self):
        state = {"value": "A"}
        def closure(request):
            return LayerResult(state["value"], (), .92)
        envelope = make_envelope(closure)
        selector = MethodSelectionCommitment.before_invocation(
            envelope, ReasoningRequest("question"),
            prediction_commitment_sha256="a"*64)
        observer = MethodInvocationObserver(envelope)
        wrapped = observer.bind_layer(LayerSpec("same-method", closure))
        CascadeEngine((wrapped,)).resolve("question")
        state["value"] = "B"
        CascadeEngine((wrapped,)).resolve("question")
        self.assertEqual(observer.invocations[0].code_before_sha256,
                         observer.invocations[1].code_before_sha256)
        self.assertNotEqual(observer.invocations[0].result_sha256,
                            observer.invocations[1].result_sha256)
        for index, observation in enumerate(observer.invocations, 1):
            report = DeclaredEvaluatorOutcome(
                task_id="case-1", execution_cut_id="cut-a",
                invocation_number=index,
                request_sha256=observation.request_sha256,
                result_sha256=observation.result_sha256,
                evaluator_id="same-untrusted-evaluator",
                outcome_digest="b"*64, verdict="CORRECT")
            joined = join_method_evaluation(selector, observation, report)
            self.assertFalse(joined.mutable_state_measured)
            self.assertFalse(joined.evaluator_label_custody_verified)
            with self.assertRaisesRegex(ValueError, "unqualified observer"):
                join_method_evaluation(selector, replace(observation,
                    independent_execution_witness=True), report)


if __name__ == "__main__":
    unittest.main()
