"""Source-only local durable Rezon method-use linkage, not trusted runtime."""
from dataclasses import replace
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from rezon.cascade import CascadeEngine, LayerSpec, LayerResult, ReasoningRequest
from rezon.method_observation import (
    MethodExecutionEnvelope, MethodInvocationObserver, measured_function_bytecode_sha256,
)
from rezon.method_evaluation_join import MethodSelectionCommitment, DeclaredEvaluatorOutcome
from rezon.method_consumer_observation import MethodConsumerObserver, DeclaredConsumerRoute
from rezon.method_use_ledger import (
    join_local_use, LocalMethodUseLedger, MethodUseHold, link_local_later_use
)

HEAD = "16a2828dfa7fb7e6c0e19004f014bc68fc47badf"

def selected_method(request):
    return LayerResult(answer="answer:"+request.prompt, unresolved=(), confidence=.75)

def selected_consumer(result):
    return "consumer:" + str(result.answer)

def failing_consumer(result):
    raise RuntimeError("failure before result")

class LocalMethodUseTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="mono81-ledger-")
        self.addCleanup(self.work.cleanup)
        self.db = Path(self.work.name)/"method-uses.sqlite"

    def actual(self, task="caseA", execution="consumer-run-A", consumer=selected_consumer):
        envelope = MethodExecutionEnvelope(
            method_id="m-rezon", revision_id="revision-1", task_id=task,
            selected_source_head=HEAD, execution_cut_id="local-cut", budget_id="one-call",
            expected_bytecode_sha256=measured_function_bytecode_sha256(selected_method))
        selection = MethodSelectionCommitment.before_invocation(
            envelope, ReasoningRequest(task), prediction_commitment_sha256="a"*64)
        observer=MethodInvocationObserver(envelope)
        outcome=CascadeEngine((observer.bind_layer(LayerSpec("m", selected_method)),)).resolve(task)
        invocation=observer.invocations[0]
        eval_claim=DeclaredEvaluatorOutcome(
            task_id=task, execution_cut_id="local-cut", invocation_number=1,
            request_sha256=invocation.request_sha256,
            result_sha256=invocation.result_sha256, evaluator_id="claimed-evaluator",
            outcome_digest="b"*64, verdict="UNKNOWN")
        route=DeclaredConsumerRoute("host-consumer", execution,
                   measured_function_bytecode_sha256(consumer))
        consumer_observer=MethodConsumerObserver(selection,invocation,eval_claim,route)
        material=LayerResult(outcome.answer,(),outcome.confidence)
        return selection, invocation, eval_claim, consumer_observer, material

    def test_actual_method_and_consumer_persist_then_reopen(self):
        s,i,e,o,r=self.actual()
        self.assertEqual(o.consume(r, selected_consumer),"consumer:answer:caseA")
        joined=join_local_use("event-A",s,i,e,o.observations[0])
        self.assertEqual(joined.declared_verdict,"UNKNOWN")
        self.assertFalse(joined.qualified_runtime_consumption_verified)
        ledger=LocalMethodUseLedger(self.db)
        chain=ledger.append(joined)
        self.assertEqual(len(chain),64)
        self.assertEqual(LocalMethodUseLedger(self.db).all(),(joined,))

    def test_cold_readback_then_second_actual_distinct_task(self):
        ledger=LocalMethodUseLedger(self.db)
        all_receipts=[]
        for label in ("A","B"):
            s,i,e,o,r=self.actual("case"+label,"consumer-run-"+label)
            o.consume(r,selected_consumer)
            x=join_local_use("event-"+label,s,i,e,o.observations[0])
            ledger.append(x)
            all_receipts.append(x)
        loaded=LocalMethodUseLedger(self.db).all()
        self.assertEqual(loaded,tuple(all_receipts))
        later=LocalMethodUseLedger(self.db).later_use("event-A","event-B")
        self.assertEqual(later.status,"LOCAL_CROSS_TASK_REUSE_ONLY")
        with self.assertRaisesRegex(MethodUseHold,"not present"):
            LocalMethodUseLedger(self.db).later_use("event-A","not-created")
        self.assertFalse(later.later_runtime_consumption_verified)
        self.assertFalse(later.causal_improvement_verified)

    def test_wrong_consumer_result_identity_cannot_join(self):
        s,i,e,o,r=self.actual()
        o.consume(r,selected_consumer)
        with self.assertRaisesRegex(MethodUseHold,"consumer not bound"):
            join_local_use("e",s,i,e,replace(o.observations[0],method_result_sha256="c"*64))

    def test_declared_evaluation_cannot_change_result(self):
        s,i,e,o,r=self.actual()
        o.consume(r,selected_consumer)
        with self.assertRaisesRegex(ValueError,"no matching returned"):
            join_local_use("e",s,i,replace(e,result_sha256="c"*64),o.observations[0])

    def test_raised_consumer_cannot_count_as_returned_use(self):
        s,i,e,o,r=self.actual(consumer=failing_consumer)
        with self.assertRaises(RuntimeError):o.consume(r,failing_consumer)
        with self.assertRaisesRegex(MethodUseHold,"no actual returned"):
            join_local_use("e",s,i,e,o.observations[0])

    def test_fake_independence_flag_rejected(self):
        s,i,e,o,r=self.actual()
        o.consume(r,selected_consumer)
        with self.assertRaisesRegex(MethodUseHold,"unqualified proof"):
            join_local_use("e",s,i,e,replace(o.observations[0],evaluator_custody_verified=True))

    def test_duplicate_append_fails_and_does_not_mutate_chain(self):
        s,i,e,o,r=self.actual();o.consume(r,selected_consumer)
        x=join_local_use("same",s,i,e,o.observations[0])
        ledger=LocalMethodUseLedger(self.db)
        ledger.append(x)
        with self.assertRaises(sqlite3.IntegrityError):ledger.append(x)
        self.assertEqual(ledger.all(),(x,))

    def test_mutation_detected_on_readback(self):
        s,i,e,o,r=self.actual();o.consume(r,selected_consumer)
        x=join_local_use("tamper",s,i,e,o.observations[0])
        ledger=LocalMethodUseLedger(self.db);ledger.append(x)
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE method_uses SET body_json='{}' WHERE sequence=1")
        with self.assertRaisesRegex(MethodUseHold,"digest changed"):
            LocalMethodUseLedger(self.db).all()

    def test_later_link_rejects_substituted_revision_or_same_task(self):
        s,i,e,o,r=self.actual();o.consume(r,selected_consumer)
        x=join_local_use("A",s,i,e,o.observations[0])
        with self.assertRaisesRegex(MethodUseHold,"distinct"):
            link_local_later_use(x,replace(x,event_id="B"))
        with self.assertRaisesRegex(MethodUseHold,"different selected"):
            link_local_later_use(x,replace(x,event_id="B",task_id="other",
                                           revision_id="r2",consumer_execution_id="run2"))

    def test_forged_elevated_receipt_rejected(self):
        s,i,e,o,r=self.actual();o.consume(r,selected_consumer)
        x=join_local_use("A",s,i,e,o.observations[0])
        with self.assertRaisesRegex(MethodUseHold,"promote"):
            LocalMethodUseLedger(self.db).append(replace(x,qualified_runtime_consumption_verified=True))

if __name__=="__main__":
    unittest.main()
