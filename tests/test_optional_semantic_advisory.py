"""Standard-library checks for explicit, untrusted advisory CLI boundaries."""

import contextlib
from dataclasses import dataclass
from enum import Enum
import io
import json
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from vera_core import cli


class OptionalAdvisoryTests(unittest.TestCase):
    def invoke(self, command, document=None, *, raw=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, "stdin", io.StringIO(json.dumps(document) if raw is None else raw)), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                code = cli.main([command])
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), errors.getvalue()

    def test_missing_optional_package_has_bounded_diagnostic(self):
        document = {"claim": {"claim_id": "c", "subject_ref": "head", "proposition": "p",
                              "required_classes": ["TEST"]}, "receipts": []}
        with patch.dict(sys.modules, {"humility": None, "humility.runtime": None}):
            code, output, errors = self.invoke("claim-assess", document)
        self.assertEqual(code, 2)
        self.assertEqual(output, "")
        self.assertEqual(errors, "vera-mono: OPTIONAL_ADVISORY_UNAVAILABLE: humility.runtime\n")

    def test_missing_planner_has_bounded_diagnostic(self):
        with patch.dict(sys.modules, {"freerowcochkar": None, "freerowcochkar.opportunities": None}):
            code, output, errors = self.invoke("opportunities", self.opportunity())
        self.assertEqual((code, output, errors),
            (2, "", "vera-mono: OPTIONAL_ADVISORY_UNAVAILABLE: freerowcochkar.opportunities\n"))

    def test_utf8_ceiling_is_bytes_not_characters(self):
        with patch("importlib.import_module") as loader:
            code, output, errors = self.invoke("claim-assess", raw="é" * 32769)
        self.assertEqual((code, output, errors),
            (2, "", "vera-mono: INVALID_ADVISORY_INPUT: bounded strict JSON required\n"))
        loader.assert_not_called()

    @staticmethod
    def claim():
        return {"claim": {"claim_id": "c", "subject_ref": "head", "proposition": "private p",
                          "required_classes": ["TEST"]}, "receipts": []}

    @staticmethod
    def opportunity():
        return {"goal": "ready", "initial_capabilities": [], "allowed_effects": ["read"],
                "cost_ceiling": 0, "actions": [{"id": "inspect", "requires": [],
                "provides": ["ready"], "effects": ["read"], "required_approvals": ["review"]}]}

    def assert_labels(self, payload):
        self.assertIs(payload.get("executed"), False)
        self.assertFalse(payload["verified"])
        self.assertEqual(payload["authority"], "NONE")
        self.assertEqual(payload["evidence_origin"], "CALLER_SUPPLIED_UNVERIFIED")
        self.assertTrue(payload["source_advisory"])

    def test_claim_preserves_component_disposition_without_promoting_evidence(self):
        @dataclass
        class Claim:
            claim_id: str
            subject_ref: str
            proposition: str
            required_classes: tuple

        class Kind(str, Enum):
            TEST = "TEST"

        result = types.SimpleNamespace(claim_id="c", subject_ref="head", claim_digest="a" * 64,
            disposition=types.SimpleNamespace(value="SUPPORTED"), admitted_receipt_ids=(),
            contradicting_receipt_ids=(), reason_codes=("REQUIRED_CLASSES_PRESENT",))
        module = types.SimpleNamespace(Claim=Claim, EvidenceClass=Kind,
            claim_fingerprint=lambda claim: "a" * 64, assess_claim=Mock(return_value=result))
        with patch("importlib.import_module", return_value=module) as loader:
            code, output, errors = self.invoke("claim-assess", self.claim())
        self.assertEqual((code, errors), (0, ""))
        loader.assert_called_once_with("humility.runtime")
        payload = json.loads(output)
        self.assert_labels(payload)
        self.assert_labels(payload["result"])
        self.assertEqual(payload["result"]["disposition"], "SUPPORTED")
        self.assertNotIn("private p", output)
        self.assertEqual(module.assess_claim.call_args.args[0].required_classes, (Kind.TEST,))

    def test_receipt_digest_is_forwarded_not_rebound(self):
        module = types.SimpleNamespace(
            Claim=lambda **values: values, EvidenceClass=lambda value: value,
            claim_fingerprint=lambda claim: "b" * 64,
            EvidenceOutcome=lambda value: value, EvidenceReceipt=lambda **values: values,
            assess_claim=Mock(return_value=types.SimpleNamespace(claim_id="c", subject_ref="head",
                claim_digest="b" * 64, disposition=types.SimpleNamespace(value="UNVERIFIED"),
                admitted_receipt_ids=(), contradicting_receipt_ids=(),
                reason_codes=("SCOPE_MISMATCH_IGNORED", "REQUIRED_CLASSES_UNVERIFIED"))))
        document = self.claim()
        document["receipts"] = [{"receipt_id": "r", "claim_id": "other", "subject_ref": "other",
            "source_group": "caller", "kind": "TEST", "outcome": "PASS", "claim_digest": "a" * 64}]
        with patch("importlib.import_module", return_value=module):
            code, output, errors = self.invoke("claim-assess", document)
        self.assertEqual((code, errors), (0, ""))
        self.assertEqual(module.assess_claim.call_args.args[1][0]["claim_digest"], "a" * 64)
        self.assertEqual(json.loads(output)["result"]["disposition"], "UNVERIFIED")

    def test_opportunity_preserves_approval_and_incomplete_statuses(self):
        for status in ("NEEDS_APPROVAL", "INCOMPLETE_UNKNOWN"):
            with self.subTest(status=status):
                module = types.SimpleNamespace(Action=lambda **values: values,
                    OpportunityRequest=lambda **values: values,
                    plan_opportunity=Mock(return_value=types.SimpleNamespace(to_dict=lambda: {
                        "status": status, "action_ids": ["inspect"], "total_cost": 0,
                        "missing_approvals": ["review"], "blockers": ["BOUNDED_SEARCH_LIMIT"],
                        "explored_states": 1, "executed": False, "verified": False,
                        "evidence_class": "CALLER_SUPPLIED_UNVERIFIED",
                        "provenance": {"inspect": "caller_supplied_unverified"}})))
                with patch("importlib.import_module", return_value=module) as loader:
                    code, output, errors = self.invoke("opportunities", self.opportunity())
                self.assertEqual((code, errors), (0, ""))
                loader.assert_called_once_with("freerowcochkar.opportunities")
                payload = json.loads(output)
                self.assert_labels(payload)
                self.assertEqual(payload["result"]["status"], status)
                self.assertEqual(payload["result"]["missing_approvals"], ["review"])

    def test_invalid_json_rejected_before_import_without_echo(self):
        raws = ["{secret-canary", '{"claim":{},"claim":{}}', '{"claim":NaN}',
                " " * (65536 + 1), '[' * 1000 + ']' * 1000,
                '{"claim":"\\ud800"}']
        for raw in raws:
            with self.subTest(raw_length=len(raw)), patch("importlib.import_module") as loader:
                code, output, errors = self.invoke("claim-assess", raw=raw)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertEqual(errors, "vera-mono: INVALID_ADVISORY_INPUT: bounded strict JSON required\n")
                loader.assert_not_called()

    def test_strict_claim_schema_and_collection_bounds(self):
        invalid = []
        for change in ({"extra": "secret"}, {"receipts": [False]}, {"receipts": [] * 0, "claim": False}):
            invalid.append(self.claim() | change)
        for value in (["BOGUS"], ["TEST", "TEST"], [], [True]):
            document = self.claim()
            document["claim"]["required_classes"] = value
            invalid.append(document)
        document = self.claim()
        document["claim"]["proposition"] = "x" * 4097
        invalid.append(document)
        document = self.claim()
        document["receipts"] = [{}] * 65
        invalid.append(document)
        self.reject_documents("claim-assess", invalid)

    def reject_documents(self, command, documents):
        for document in documents:
            with self.subTest(document=document), patch("importlib.import_module") as loader:
                code, output, errors = self.invoke(command, document)
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertEqual(errors, "vera-mono: INVALID_ADVISORY_INPUT: bounded strict JSON required\n")
                loader.assert_not_called()

    def test_planner_rejects_cost_type_unknown_fields_and_overbounds_before_import(self):
        documents = []
        for change in ({"cost_ceiling": 1}, {"cost_ceiling": False}, {"max_steps": 0},
                       {"max_steps": 33}, {"granted_approvals": "review"}, {"extra": 1},
                       {"actions": [{}] * 65}, {"goal": "x" * 129}):
            documents.append(self.opportunity() | change)
        for change in ({"cost": 1}, {"cost": True}, {"disabled": "false"}, {"effects": [False]},
                       {"requires": ["x"] * 65}, {"provides": []}, {"provenance": "x" * 513}):
            document = self.opportunity()
            document["actions"][0].update(change)
            documents.append(document)
        duplicate = self.opportunity()
        duplicate["actions"] *= 2
        documents.append(duplicate)
        self.reject_documents("opportunities", documents)

    def test_component_failure_is_bounded(self):
        module = types.SimpleNamespace(Claim=Mock(side_effect=RuntimeError("secret-canary")))
        with patch("importlib.import_module", return_value=module):
            code, output, errors = self.invoke("claim-assess", self.claim())
        self.assertEqual((code, output, errors), (2, "", "vera-mono: OPTIONAL_ADVISORY_FAILED: no assessment completed\n"))

    def test_normal_cli_does_not_read_stdin_or_load_optional_adapter(self):
        with patch.object(sys, "stdin", Mock(read=Mock(side_effect=AssertionError("unexpected read")))), \
                patch("importlib.import_module") as loader, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["shell", "help"]), 0)
        loader.assert_not_called()

    def test_oversized_component_output_is_not_emitted(self):
        module = types.SimpleNamespace(Claim=lambda **values: values,
            EvidenceClass=lambda value: value, claim_fingerprint=lambda claim: "b" * 64,
            assess_claim=Mock(return_value=types.SimpleNamespace(claim_id="secret" * 20000,
                subject_ref="head", claim_digest="b" * 64,
                disposition=types.SimpleNamespace(value="SUPPORTED"),
                admitted_receipt_ids=(), contradicting_receipt_ids=(), reason_codes=())))
        with patch("importlib.import_module", return_value=module):
            code, output, errors = self.invoke("claim-assess", self.claim())
        self.assertEqual((code, output, errors), (2, "", "vera-mono: OPTIONAL_ADVISORY_FAILED: no assessment completed\n"))


class OptionalProviderBoundaryTests(unittest.TestCase):
    invoke = OptionalAdvisoryTests.invoke
    claim = staticmethod(OptionalAdvisoryTests.claim)
    opportunity = staticmethod(OptionalAdvisoryTests.opportunity)

    @staticmethod
    def claim_module(**changes):
        fields = dict(claim_id="c", subject_ref="head", claim_digest="a" * 64,
                      disposition=types.SimpleNamespace(value="UNVERIFIED"),
                      admitted_receipt_ids=(), contradicting_receipt_ids=(),
                      reason_codes=("REQUIRED_CLASSES_UNVERIFIED",)) | changes
        return types.SimpleNamespace(Claim=lambda **values: values,
            EvidenceClass=lambda value: value, claim_fingerprint=lambda claim: "a" * 64,
            assess_claim=Mock(return_value=types.SimpleNamespace(**fields)))

    @staticmethod
    def plan_module(**changes):
        fields = dict(status="NEEDS_APPROVAL", action_ids=["inspect"], total_cost=0,
            missing_approvals=["review"], blockers=[], explored_states=1, executed=False,
            verified=False, evidence_class="CALLER_SUPPLIED_UNVERIFIED",
            provenance={"inspect": "caller_supplied_unverified"}) | changes
        return types.SimpleNamespace(Action=lambda **values: values,
            OpportunityRequest=lambda **values: values,
            plan_opportunity=Mock(return_value=types.SimpleNamespace(to_dict=lambda: fields)))

    def assert_failed(self, observed):
        self.assertEqual(observed, (2, "", "vera-mono: OPTIONAL_ADVISORY_FAILED: no assessment completed\n"))

    def test_import_and_call_python_output_is_not_forwarded(self):
        for stage in ("import", "call"):
            with self.subTest(stage=stage):
                module = self.claim_module()
                def noisy(*args):
                    print("raw-private-canary")
                    print("raw-private-canary", file=sys.stderr)
                    return module if stage == "import" else module.assess_claim.return_value
                if stage == "call":
                    module.assess_claim.side_effect = noisy
                with patch("importlib.import_module", side_effect=noisy if stage == "import" else None,
                           return_value=module):
                    code, output, errors = self.invoke("claim-assess", self.claim())
                self.assertEqual(code, 0)
                self.assertEqual(errors, "")
                self.assertEqual(json.loads(output)["result"]["disposition"], "UNVERIFIED")
                self.assertNotIn("canary", output)

    def test_oversized_optional_print_is_bounded(self):
        def noisy_import(*args):
            print("raw-canary" * 10000)
            return self.claim_module()
        with patch("importlib.import_module", side_effect=noisy_import):
            self.assert_failed(self.invoke("claim-assess", self.claim()))

    def test_optional_system_exit_and_interrupt_are_sanitized(self):
        for stage in ("import", "call"):
            for exception in (SystemExit("raw-canary"), KeyboardInterrupt("raw-canary")):
                with self.subTest(stage=stage, exception=type(exception).__name__):
                    module = self.claim_module()
                    if stage == "call":
                        module.assess_claim.side_effect = exception
                    with patch("importlib.import_module", side_effect=exception if stage == "import" else None,
                               return_value=module):
                        try:
                            observed = self.invoke("claim-assess", self.claim())
                        except KeyboardInterrupt:
                            observed = ("escaped KeyboardInterrupt", "", "")
                    if isinstance(exception, KeyboardInterrupt):
                        self.assertEqual(observed, (130, "", "vera-mono: OPTIONAL_ADVISORY_INTERRUPTED: no assessment completed\n"))
                    else:
                        self.assert_failed(observed)

    def test_malformed_claim_output_is_rejected(self):
        for changes in ({"claim_id": {"authority": "ADMIN"}}, {"claim_id": "other"},
                        {"subject_ref": "other"}, {"claim_digest": 42}, {"claim_digest": "x"},
                        {"claim_digest": "b" * 64},
                        {"admitted_receipt_ids": {"authority": "ADMIN"}},
                        {"admitted_receipt_ids": ("undeclared",)},
                        {"contradicting_receipt_ids": "r"},
                        {"reason_codes": ("authority=ADMIN",)}, {"reason_codes": ("x",) * 65}):
            with self.subTest(fields=tuple(changes)), patch("importlib.import_module",
                    return_value=self.claim_module(**changes)):
                self.assert_failed(self.invoke("claim-assess", self.claim()))

    def test_malformed_planner_output_is_rejected(self):
        for changes in ({"action_ids": {"authority": "ADMIN"}}, {"action_ids": ["undeclared"]},
                        {"total_cost": 100}, {"total_cost": False}, {"explored_states": -1},
                        {"explored_states": True}, {"explored_states": 8193},
                        {"missing_approvals": ["undeclared"]}, {"blockers": ["authority=ADMIN"]},
                        {"provenance": {"authority": "ADMIN"}},
                        {"provenance": {"inspect": {"authority": "ADMIN"}}},
                        {"provenance": {"inspect": "authority=ADMIN"}},
                        {"executed": True}, {"verified": True}, {"authority": "ADMIN"},
                        {"evidence_class": "AUTHENTICATED"}):
            with self.subTest(fields=tuple(changes)), patch("importlib.import_module",
                    return_value=self.plan_module(**changes)):
                self.assert_failed(self.invoke("opportunities", self.opportunity()))

    def test_planner_status_and_route_approval_coherence(self):
        for changes in ({"status": "AVAILABLE"}, {"missing_approvals": []},
                        {"status": "NO_ROUTE"},
                        {"action_ids": [], "provenance": {}, "missing_approvals": []}):
            with self.subTest(fields=tuple(changes)), patch("importlib.import_module",
                    return_value=self.plan_module(**changes)):
                self.assert_failed(self.invoke("opportunities", self.opportunity()))


@unittest.skipUnless(os.environ.get("VERA_ADVISORY_SOURCE_FIXTURES") == "1",
                     "explicit reviewed-source fixture opt-in required")
class ReviewedSourceFixtureTests(unittest.TestCase):
    """Run via source-only PYTHONPATH; not installation or runtime qualification."""

    invoke = OptionalAdvisoryTests.invoke
    assert_labels = OptionalAdvisoryTests.assert_labels
    claim = staticmethod(OptionalAdvisoryTests.claim)
    opportunity = staticmethod(OptionalAdvisoryTests.opportunity)

    def test_real_claim_fingerprint_mismatch_is_not_supported(self):
        from humility.runtime import Claim, EvidenceClass, claim_fingerprint
        document = self.claim()
        claim = document["claim"]
        fingerprint = claim_fingerprint(Claim(claim["claim_id"], claim["subject_ref"],
            claim["proposition"], (EvidenceClass.TEST,)))
        receipt = {"receipt_id": "r", "claim_id": "c", "subject_ref": "head", "source_group": "s",
                   "kind": "TEST", "outcome": "PASS", "claim_digest": fingerprint}
        for digest, expected in ((fingerprint, "SUPPORTED"), ("0" * 64, "UNVERIFIED")):
            document["receipts"] = [receipt | {"claim_digest": digest}]
            code, output, errors = self.invoke("claim-assess", document)
            self.assertEqual((code, errors), (0, ""))
            result = json.loads(output)
            self.assert_labels(result)
            self.assertEqual(result["result"]["disposition"], expected)

    def test_real_planner_retains_missing_approval(self):
        code, output, errors = self.invoke("opportunities", self.opportunity())
        self.assertEqual((code, errors), (0, ""))
        result = json.loads(output)
        self.assert_labels(result)
        self.assertEqual(result["result"]["status"], "NEEDS_APPROVAL")
        self.assertEqual(result["result"]["missing_approvals"], ["review"])

    def test_real_planner_step_bound_remains_incomplete(self):
        document = self.opportunity()
        document["max_steps"] = 1
        document["actions"][0]["provides"] = ["middle"]
        document["actions"].append({"id": "finish", "requires": ["middle"],
            "provides": ["ready"], "effects": ["read"]})
        code, output, errors = self.invoke("opportunities", document)
        self.assertEqual((code, errors), (0, ""))
        result = json.loads(output)
        self.assert_labels(result)
        self.assertEqual(result["result"]["status"], "INCOMPLETE_UNKNOWN")
        self.assertIn("BOUNDED_SEARCH_LIMIT", result["result"]["blockers"])


if __name__ == "__main__":
    unittest.main()
