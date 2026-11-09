"""Synthetic human-rating fixtures; no genuine withheld cases or model loads."""

from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.test_mini_vera_loopback import FakeLocal, candidate
from tests.test_mini_vera_withheld_dialogue import synthetic_scenario
from tools.mini_vera import loopback, qualification_workflow as workflow, withheld_dialogue


def write_json(path: Path, value: dict) -> None:
    path.write_bytes(loopback.canonical(value) + b"\n")


def make_setup(folder: Path, n: int = 5, *, aborted: bool = True, unattempted: bool = True):
    scenarios = []
    for i in range(n + int(aborted) + int(unattempted)):
        scenario = synthetic_scenario()
        scenario["case_id"] = f"synthetic-case-{i:02d}"
        path = folder / f"case-{i:02d}.json"
        write_json(path, scenario)
        scenarios.append((scenario, path))
    case_list = {"schema": "MINI_VERA_EXTERNAL_CASE_LIST_V1",
                 "cases": [{"case_id": scenario["case_id"], "scenario_path": str(path)}
                           for scenario, path in scenarios]}
    schedule = workflow.prepare_schedule(case_list, secret_seed=b"S" * 32)
    rows = []
    with FakeLocal() as fake:
        for i, (scenario, _) in enumerate(scenarios):
            if i == n + int(aborted):
                rows.append({"case_id": scenario["case_id"], "status": "NOT_ATTEMPTED"})
                continue
            if i == n:
                receipt = {"schema": "MINI_VERA_ABORTED_DIALOGUE_V1",
                           "status": "INCOMPLETE_NOT_BEHAVIORALLY_QUALIFIED",
                           "case_id": scenario["case_id"],
                           "case_sha256": loopback.sha256(loopback.canonical(scenario)),
                           "calls_attempted_observed": 1}
                receipt_path = folder / f"aborted-{i}.json"
                write_json(receipt_path, receipt)
                rows.append({"case_id": scenario["case_id"], "status": "ABORTED",
                             "private_receipt_path": str(receipt_path)})
                continue
            sheet, key = withheld_dialogue.compare(candidate(), scenario, endpoint=fake.url)
            sheet_path, key_path = folder / f"sheet-{i}.json", folder / f"key-{i}.json"
            write_json(sheet_path, sheet)
            write_json(key_path, key)
            scores = {label: {d: {"bare_natural": 1, "minimal_natural": 2,
                                    "governed_natural": 3}[arm]
                              for d in workflow.DIMENSIONS}
                      for label, arm in key["arm_by_label"].items()}
            rating = {"schema": "MINI_VERA_EXTERNAL_HUMAN_RATING_V1",
                      "case_id": scenario["case_id"], "trial_id": key["trial_id"],
                      "rater_id": "synthetic-test-rater",
                      "attestation": {
                          "human_authored": "OPERATOR_ASSERTED_NOT_ATTESTED",
                          "mapping_unseen_until_scoring_finished": "OPERATOR_ASSERTED_NOT_ATTESTED",
                          "training_use": "PROHIBITED"},
                      "scores_by_label": scores}
            rating_path = folder / f"rating-{i}.json"
            write_json(rating_path, rating)
            rows.append({"case_id": scenario["case_id"], "status": "COMPLETED",
                         "private_key_path": str(key_path),
                         "private_key_sha256": loopback.sha256(loopback.canonical(key)),
                         "rater_sheet_path": str(sheet_path),
                         "ratings": [{"path": str(rating_path),
                                      "sha256": loopback.sha256(loopback.canonical(rating))}]})
    ledger = {"schema": "MINI_VERA_EXTERNAL_RESULT_LEDGER_V1",
              "schedule_sha256": loopback.sha256(loopback.canonical(schedule)),
              "cases": rows}
    return case_list, schedule, ledger


class MiniVeraQualificationWorkflowTests(unittest.TestCase):
    def test_private_schedule_deterministic_shuffled_and_no_case_text(self):
        with tempfile.TemporaryDirectory() as temp:
            case_list, schedule, _ = make_setup(Path(temp), n=1, aborted=False, unattempted=False)
            again = workflow.prepare_schedule(case_list, secret_seed=b"S" * 32)
            self.assertEqual(schedule, again)
            self.assertEqual(len(schedule["cases_in_randomized_order"]), 1)
            self.assertNotIn("What can you verify?", json.dumps(schedule))
            self.assertNotIn("scenario_path", json.dumps(schedule))
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.prepare_schedule(case_list, secret_seed=b"short")

    def test_human_only_paired_aggregation_keeps_aborted_in_denominator(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp))
            summary = workflow.aggregate(schedule, ledger)
            self.assertEqual(summary["denominator"], {
                "scheduled": 7, "attempted": 6, "completed": 5,
                "aborted": 1, "not_attempted": 1, "fully_human_rated": 5})
            self.assertEqual(summary["completion_rate_among_attempted"], 0.8333)
            self.assertEqual(summary["pairwise"]["governed_minus_bare"]["mean_case_delta_0_to_4"], 2.0)
            self.assertEqual(summary["pairwise"]["governed_minus_bare"]["case_bootstrap_95_percentile_ci"],
                             [2.0, 2.0])
            self.assertEqual(summary["pairwise"]["governed_minus_minimal"]["mean_case_delta_0_to_4"], 1.0)
            self.assertIn("DESCRIPTIVE", summary["status"])
            self.assertEqual(summary["model_alias_operator_declared"], "qwen3.5-mini-local")

    def test_completed_case_with_missing_model_output_cannot_be_rated_success(self):
        # A rehashed blank/whitespace-only model reply must not inflate the
        # rated denominator. Nonblank whitespace is preserved for human review.
        for answer, accepted in (("", False), ("  \t\n", False),
                                 ("\x00", False), ("\u200b", False),
                                 ("\u200d\u2060", False), ("\x1b", False),
                                 ("  meaningful answer\n", True),
                                 ("東京", True), ("!", True), ("🪐", True),
                                 ("bonjour\u200b", True)):
            with self.subTest(answer=repr(answer)), tempfile.TemporaryDirectory() as temp:
                _, schedule, ledger = make_setup(Path(temp), n=1, aborted=False,
                                                 unattempted=False)
                row = ledger["cases"][0]
                sheet_path = Path(row["rater_sheet_path"])
                key_path = Path(row["private_key_path"])
                sheet = json.loads(sheet_path.read_text())
                key = json.loads(key_path.read_text())
                turn = sheet["transcripts_by_masked_label"]["A"][0]
                turn["answer"] = answer
                turn["answer_sha256"] = loopback.sha256(answer.encode("utf-8"))
                write_json(sheet_path, sheet)
                key["rater_sheet_sha256"] = loopback.sha256(loopback.canonical(sheet))
                write_json(key_path, key)
                row["private_key_sha256"] = loopback.sha256(loopback.canonical(key))
                if accepted:
                    summary = workflow.aggregate(schedule, ledger)
                    self.assertEqual(summary["denominator"]["completed"], 1)
                else:
                    with self.assertRaisesRegex(loopback.LoopbackRejected,
                                                "invalid.*transcript"):
                        workflow.aggregate(schedule, ledger)
        # Directly probe the transcript validator before outer receipt
        # serialization, which cannot represent lone surrogate code points.
        with tempfile.TemporaryDirectory() as temp:
            _, _, ledger = make_setup(Path(temp), n=1, aborted=False,
                                      unattempted=False)
            row = ledger["cases"][0]
            sheet = json.loads(Path(row["rater_sheet_path"]).read_text())
            key = json.loads(Path(row["private_key_path"]).read_text())
            sheet["transcripts_by_masked_label"]["A"][0]["answer"] = chr(0xD800)
            with self.assertRaisesRegex(loopback.LoopbackRejected,
                                        "invalid.*transcript"):
                workflow._check_complete_transcript(sheet, key)

    def test_fewer_than_five_cases_has_no_overconfident_interval(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp), n=1, aborted=False, unattempted=False)
            summary = workflow.aggregate(schedule, ledger)
            self.assertIsNone(summary["pairwise"]["governed_minus_bare"]["case_bootstrap_95_percentile_ci"])
            self.assertEqual(summary["denominator"]["completed"], 1)

    def test_reject_omitted_case_drift_and_invalid_human_ratings(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp), n=1, aborted=False, unattempted=False)
            omitted = deepcopy(ledger)
            omitted["cases"] = []
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, omitted)
            wrong_sha = deepcopy(ledger)
            wrong_sha["cases"][0]["ratings"][0]["sha256"] = "a" * 64
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, wrong_sha)
            wrong_binding = deepcopy(ledger)
            wrong_binding["schedule_sha256"] = "b" * 64
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, wrong_binding)
            row = ledger["cases"][0]
            rating_path = Path(row["ratings"][0]["path"])
            rating = json.loads(rating_path.read_text())
            rating["scores_by_label"]["A"]["overall"] = True
            write_json(rating_path, rating)
            row["ratings"][0]["sha256"] = loopback.sha256(loopback.canonical(rating))
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, ledger)

    def test_post_rating_private_mapping_swap_must_not_reverse_verdict(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp), n=5, aborted=False, unattempted=False)
            original = workflow.aggregate(schedule, ledger)
            self.assertEqual(original["pairwise"]["governed_minus_bare"]["mean_case_delta_0_to_4"], 2.0)
            for row in ledger["cases"]:
                key_path = Path(row["private_key_path"])
                key = json.loads(key_path.read_text())
                mapping = key["arm_by_label"]
                for label, arm in mapping.items():
                    if arm == "bare_natural":
                        mapping[label] = "governed_natural"
                    elif arm == "governed_natural":
                        mapping[label] = "bare_natural"
                write_json(key_path, key)
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, ledger)

    def test_same_alias_but_different_declared_model_digest_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp), n=2, aborted=False, unattempted=False)
            row = ledger["cases"][1]
            key_path = Path(row["private_key_path"])
            key = json.loads(key_path.read_text())
            key["model_registry_digest_operator_declared"] = "d" * 64
            write_json(key_path, key)
            row["private_key_sha256"] = loopback.sha256(loopback.canonical(key))
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, ledger)

    def test_independently_pinned_pre_rating_keys_block_joint_key_ledger_rewrite(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp), n=5, aborted=False, unattempted=False)
            commitment = {
                "schema": "MINI_VERA_EXTERNAL_PRE_RATING_KEY_COMMITMENTS_V1",
                "schedule_sha256": loopback.sha256(loopback.canonical(schedule)),
                "key_sha256_by_case": {
                    row["case_id"]: row["private_key_sha256"] for row in ledger["cases"]
                },
            }
            trusted_digest = loopback.sha256(loopback.canonical(commitment))
            initial = workflow.aggregate(
                schedule, ledger, pre_rating_key_commitments=commitment,
                expected_pre_rating_key_commitment_sha256=trusted_digest,
            )
            self.assertEqual(initial["pairwise"]["governed_minus_bare"]["mean_case_delta_0_to_4"], 2.0)

            # The old local-ledger-only path cannot distinguish a joint rewrite:
            # all rater sheets, rating files and schedules remain byte-identical.
            for row in ledger["cases"]:
                key_path = Path(row["private_key_path"])
                key = json.loads(key_path.read_text())
                for label, arm in key["arm_by_label"].items():
                    if arm == "bare_natural":
                        key["arm_by_label"][label] = "governed_natural"
                    elif arm == "governed_natural":
                        key["arm_by_label"][label] = "bare_natural"
                write_json(key_path, key)
                row["private_key_sha256"] = loopback.sha256(loopback.canonical(key))
            self.assertEqual(workflow.aggregate(schedule, ledger)["pairwise"]
                             ["governed_minus_bare"]["mean_case_delta_0_to_4"], -2.0)

            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger, pre_rating_key_commitments=commitment,
                    expected_pre_rating_key_commitment_sha256=trusted_digest,
                )

            # Rewriting the purported external commitment does not help if its
            # digest was pinned independently before the ratings were seen.
            forged = deepcopy(commitment)
            forged["key_sha256_by_case"] = {
                row["case_id"]: row["private_key_sha256"] for row in ledger["cases"]
            }
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger, pre_rating_key_commitments=forged,
                    expected_pre_rating_key_commitment_sha256=trusted_digest,
                )

    def test_external_key_commitment_fail_closed_and_cli_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            _, schedule, ledger = make_setup(folder, n=1, aborted=False, unattempted=False)
            row = ledger["cases"][0]
            commitment = {
                "schema": "MINI_VERA_EXTERNAL_PRE_RATING_KEY_COMMITMENTS_V1",
                "schedule_sha256": loopback.sha256(loopback.canonical(schedule)),
                "key_sha256_by_case": {row["case_id"]: row["private_key_sha256"]},
            }
            digest = loopback.sha256(loopback.canonical(commitment))
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, ledger, pre_rating_key_commitments=commitment)
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, ledger,
                                   expected_pre_rating_key_commitment_sha256=digest)
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, ledger, pre_rating_key_commitments=commitment,
                                   expected_pre_rating_key_commitment_sha256="0" * 64)
            missing_case = deepcopy(commitment)
            missing_case["key_sha256_by_case"] = {}
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger, pre_rating_key_commitments=missing_case,
                    expected_pre_rating_key_commitment_sha256=loopback.sha256(
                        loopback.canonical(missing_case)),
                )
            foreign_case = deepcopy(commitment)
            foreign_case["key_sha256_by_case"] = {"foreign-case": row["private_key_sha256"]}
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger, pre_rating_key_commitments=foreign_case,
                    expected_pre_rating_key_commitment_sha256=loopback.sha256(
                        loopback.canonical(foreign_case)),
                )
            schedule_path, ledger_path = folder / "schedule.json", folder / "ledger.json"
            commitment_path, output_path = folder / "commitments.json", folder / "summary.json"
            for path, value in ((schedule_path, schedule), (ledger_path, ledger),
                                (commitment_path, commitment)):
                write_json(path, value)
            if os.name == "nt":
                # Source-only Windows output remains intentionally held until
                # a restrictive child DACL/host-owned directory is proven.
                with self.assertRaisesRegex(loopback.LoopbackRejected,
                                            "Windows private evaluation output HOLD"):
                    workflow.main([
                        "aggregate", "--schedule", str(schedule_path),
                        "--result-ledger", str(ledger_path),
                        "--pre-rating-key-commitments", str(commitment_path),
                        "--expected-pre-rating-key-commitment-sha256", digest,
                        "--output", str(output_path),
                    ])
                self.assertFalse(output_path.exists())
                return
            with redirect_stdout(StringIO()):
                status = workflow.main([
                    "aggregate", "--schedule", str(schedule_path),
                    "--result-ledger", str(ledger_path),
                    "--pre-rating-key-commitments", str(commitment_path),
                    "--expected-pre-rating-key-commitment-sha256", digest,
                    "--output", str(output_path),
                ])
            self.assertEqual(status, 0)
            output = json.loads(output_path.read_text())
            self.assertEqual(output["external_pre_rating_key_custody"], {
                "mode": "EXACT_SHA_PINNED_EXTERNALLY_OPERATOR_SUPPLIED",
                "commitment_sha256": digest,
                "timestamp_and_immutability": "NOT_ATTESTED_BY_THIS_TOOL",
            })
            self.assertEqual(output["external_joint_custody_scope"], "KEYS_ONLY_RATINGS_MUTABLE")
            receipt_manifest = {
                "schema": "MINI_VERA_EXTERNAL_POST_RATING_RECEIPT_COMMITMENTS_V1",
                "schedule_sha256": loopback.sha256(loopback.canonical(schedule)),
                "rating_sha256_by_case": {
                    row["case_id"]: [receipt["sha256"] for receipt in row["ratings"]]
                },
            }
            receipt_digest = loopback.sha256(loopback.canonical(receipt_manifest))
            receipt_path, dual_output_path = folder / "receipts.json", folder / "dual-summary.json"
            write_json(receipt_path, receipt_manifest)
            with redirect_stdout(StringIO()):
                dual_status = workflow.main([
                    "aggregate", "--schedule", str(schedule_path),
                    "--result-ledger", str(ledger_path),
                    "--pre-rating-key-commitments", str(commitment_path),
                    "--expected-pre-rating-key-commitment-sha256", digest,
                    "--post-rating-receipt-commitments", str(receipt_path),
                    "--expected-post-rating-receipt-commitment-sha256", receipt_digest,
                    "--output", str(dual_output_path),
                ])
            self.assertEqual(dual_status, 0)
            dual = json.loads(dual_output_path.read_text())
            self.assertEqual(dual["external_joint_custody_scope"],
                             "KEYS_AND_RATINGS_CALLER_SHA_PINNED_BUT_NOT_AUTHENTICATED")
            self.assertEqual(dual["external_post_rating_receipt_custody"]
                             ["commitment_sha256"], receipt_digest)

    def test_pinned_key_alone_does_not_protect_mutable_human_rating_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp), n=5, aborted=False, unattempted=False)
            schedule_digest = loopback.sha256(loopback.canonical(schedule))
            keys = {
                "schema": "MINI_VERA_EXTERNAL_PRE_RATING_KEY_COMMITMENTS_V1",
                "schedule_sha256": schedule_digest,
                "key_sha256_by_case": {
                    row["case_id"]: row["private_key_sha256"] for row in ledger["cases"]
                },
            }
            key_digest = loopback.sha256(loopback.canonical(keys))
            receipt_anchor = {
                "schema": "MINI_VERA_EXTERNAL_POST_RATING_RECEIPT_COMMITMENTS_V1",
                "schedule_sha256": schedule_digest,
                "rating_sha256_by_case": {
                    row["case_id"]: [receipt["sha256"] for receipt in row["ratings"]]
                    for row in ledger["cases"]
                },
            }
            receipt_digest = loopback.sha256(loopback.canonical(receipt_anchor))
            original = workflow.aggregate(
                schedule, ledger, pre_rating_key_commitments=keys,
                expected_pre_rating_key_commitment_sha256=key_digest,
                post_rating_receipt_commitments=receipt_anchor,
                expected_post_rating_receipt_commitment_sha256=receipt_digest,
            )
            self.assertEqual(original["pairwise"]["governed_minus_bare"]["mean_case_delta_0_to_4"], 2.0)
            self.assertEqual(original["external_joint_custody_scope"],
                             "KEYS_AND_RATINGS_CALLER_SHA_PINNED_BUT_NOT_AUTHENTICATED")
            downgraded = deepcopy(ledger)
            downgraded["cases"][0] = {
                "case_id": downgraded["cases"][0]["case_id"], "status": "NOT_ATTEMPTED"
            }
            # A previously rated case cannot vanish into the unattempted or
            # aborted denominator after a rating-manifest digest was pinned.
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, downgraded, pre_rating_key_commitments=keys,
                    expected_pre_rating_key_commitment_sha256=key_digest,
                    post_rating_receipt_commitments=receipt_anchor,
                    expected_post_rating_receipt_commitment_sha256=receipt_digest,
                )
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger, post_rating_receipt_commitments=receipt_anchor,
                )
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger,
                    expected_post_rating_receipt_commitment_sha256=receipt_digest,
                )
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger, post_rating_receipt_commitments=receipt_anchor,
                    expected_post_rating_receipt_commitment_sha256="e" * 64,
                )
            for row in ledger["cases"]:
                key = json.loads(Path(row["private_key_path"]).read_text())
                mapping = key["arm_by_label"]
                bare = next(label for label, arm in mapping.items() if arm == "bare_natural")
                governed = next(label for label, arm in mapping.items() if arm == "governed_natural")
                rating_path = Path(row["ratings"][0]["path"])
                rating = json.loads(rating_path.read_text())
                rating["scores_by_label"][bare], rating["scores_by_label"][governed] = (
                    rating["scores_by_label"][governed], rating["scores_by_label"][bare]
                )
                write_json(rating_path, rating)
                row["ratings"][0]["sha256"] = loopback.sha256(loopback.canonical(rating))
            # Key-only precommit is insufficient: a mutable rating plus its
            # equally mutable ledger hash can reverse a real score summary.
            unanchored = workflow.aggregate(
                schedule, ledger, pre_rating_key_commitments=keys,
                expected_pre_rating_key_commitment_sha256=key_digest,
            )
            self.assertEqual(unanchored["pairwise"]["governed_minus_bare"]["mean_case_delta_0_to_4"], -2.0)
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger, pre_rating_key_commitments=keys,
                    expected_pre_rating_key_commitment_sha256=key_digest,
                    post_rating_receipt_commitments=receipt_anchor,
                    expected_post_rating_receipt_commitment_sha256=receipt_digest,
                )

    def test_pinned_completed_trial_key_cannot_become_unattempted_without_rating_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp), n=5, aborted=False, unattempted=False)
            schedule_digest = loopback.sha256(loopback.canonical(schedule))
            key_manifest = {
                "schema": "MINI_VERA_EXTERNAL_PRE_RATING_KEY_COMMITMENTS_V1",
                "schedule_sha256": schedule_digest,
                "key_sha256_by_case": {
                    row["case_id"]: row["private_key_sha256"] for row in ledger["cases"]
                },
            }
            key_digest = loopback.sha256(loopback.canonical(key_manifest))
            retained = ledger["cases"][:4]
            rating_manifest = {
                "schema": "MINI_VERA_EXTERNAL_POST_RATING_RECEIPT_COMMITMENTS_V1",
                "schedule_sha256": schedule_digest,
                "rating_sha256_by_case": {
                    row["case_id"]: [r["sha256"] for r in row["ratings"]]
                    for row in retained
                },
            }
            rating_digest = loopback.sha256(loopback.canonical(rating_manifest))
            downgraded = deepcopy(ledger)
            downgraded["cases"][4] = {
                "case_id": downgraded["cases"][4]["case_id"],
                "status": "NOT_ATTEMPTED",
            }
            # Four rating receipts pin four COMPLETED cases, but the fifth
            # completed trial key is ALSO externally pinned. Downgrading it to
            # NOT_ATTEMPTED used to silently falsify completion denominator.
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, downgraded,
                    pre_rating_key_commitments=key_manifest,
                    expected_pre_rating_key_commitment_sha256=key_digest,
                    post_rating_receipt_commitments=rating_manifest,
                    expected_post_rating_receipt_commitment_sha256=rating_digest,
                )

    def test_pinned_aborted_receipt_cannot_be_hidden_as_not_attempted(self):
        with tempfile.TemporaryDirectory() as temp:
            _, schedule, ledger = make_setup(Path(temp), n=1, aborted=True, unattempted=True)
            aborted = next(row for row in ledger["cases"] if row["status"] == "ABORTED")
            receipt = json.loads(Path(aborted["private_receipt_path"]).read_text())
            external = {
                "schema": "MINI_VERA_EXTERNAL_ABORTED_RECEIPT_COMMITMENTS_V1",
                "schedule_sha256": loopback.sha256(loopback.canonical(schedule)),
                "aborted_receipt_sha256_by_case": {
                    aborted["case_id"]: loopback.sha256(loopback.canonical(receipt)),
                },
            }
            digest = loopback.sha256(loopback.canonical(external))
            kwargs = {
                "aborted_receipt_commitments": external,
                "expected_aborted_receipt_commitment_sha256": digest,
            }
            original = workflow.aggregate(schedule, ledger, **kwargs)
            self.assertEqual(original["denominator"]["aborted"], 1)
            self.assertEqual(original["denominator"]["attempted"], 2)
            self.assertEqual(original["external_aborted_attempt_custody"]["commitment_sha256"], digest)

            downgraded = deepcopy(ledger)
            downgraded["cases"] = [
                {"case_id": row["case_id"], "status": "NOT_ATTEMPTED"}
                if row["case_id"] == aborted["case_id"] else row
                for row in downgraded["cases"]
            ]
            # Without this independently held digest, a legitimate attempted
            # trial silently vanishes from the attempted denominator.
            self.assertEqual(workflow.aggregate(schedule, downgraded)
                             ["denominator"]["attempted"], 1)
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, downgraded, **kwargs)

            tampered = deepcopy(ledger)
            path = Path(aborted["private_receipt_path"])
            receipt["calls_attempted_observed"] = 2
            write_json(path, receipt)
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, tampered, **kwargs)

            # The manifest is an exact case-set pin, not a loosely advisory
            # hash. Omitting it, changing the schedule or inventing a case
            # must never be interpreted as independent external custody.
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(schedule, ledger, aborted_receipt_commitments=external)
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger,
                    expected_aborted_receipt_commitment_sha256=digest,
                )
            forged = deepcopy(external)
            forged["aborted_receipt_sha256_by_case"] = {
                "foreign-case": loopback.sha256(loopback.canonical(receipt))}
            with self.assertRaises(loopback.LoopbackRejected):
                workflow.aggregate(
                    schedule, ledger,
                    aborted_receipt_commitments=forged,
                    expected_aborted_receipt_commitment_sha256=loopback.sha256(
                        loopback.canonical(forged)),
                )

            # Exercise the actual CLI import and exclusive output seam as
            # well as the in-process aggregate call.
            restored = dict(receipt, calls_attempted_observed=1)
            write_json(path, restored)
            folder = Path(temp)
            sources = ((folder / "sched.json", schedule),
                       (folder / "ledger.json", ledger),
                       (folder / "aborted-pins.json", external))
            for file, contents in sources:
                write_json(file, contents)
            output = folder / "aborted-result.json"
            if os.name == "nt":
                with self.assertRaisesRegex(loopback.LoopbackRejected,
                                            "Windows private evaluation output HOLD"):
                    workflow.main([
                        "aggregate", "--schedule", str(sources[0][0]),
                        "--result-ledger", str(sources[1][0]),
                        "--aborted-receipt-commitments", str(sources[2][0]),
                        "--expected-aborted-receipt-commitment-sha256", digest,
                        "--output", str(output),
                    ])
                self.assertFalse(output.exists())
                return
            with redirect_stdout(StringIO()):
                self.assertEqual(workflow.main([
                    "aggregate", "--schedule", str(sources[0][0]),
                    "--result-ledger", str(sources[1][0]),
                    "--aborted-receipt-commitments", str(sources[2][0]),
                    "--expected-aborted-receipt-commitment-sha256", digest,
                    "--output", str(output),
                ]), 0)
            self.assertEqual(json.loads(output.read_text())
                             ["external_aborted_attempt_custody"]["commitment_sha256"], digest)

    def test_external_path_checked_then_swapped_to_repository_symlink_is_rejected(self):
        # Reproduces the real _external -> _read TOCTOU gap: a previously
        # approved external path is no longer safe at open time. The file
        # descriptor must bind the read to the eventual actual target, and
        # the source-repository exclusion must apply to that target too.
        with tempfile.TemporaryDirectory() as temp:
            candidate_path = Path(temp) / "external-data.json"
            write_json(candidate_path, {"schema": "EXTERNAL_FIXTURE"})
            checked_path = workflow._external(candidate_path)
            self.assertEqual(workflow._read(checked_path, workflow.MAX_MANIFEST_BYTES)
                             ["schema"], "EXTERNAL_FIXTURE")
            candidate_path.unlink()
            try:
                candidate_path.symlink_to(workflow.ROOT / "architecture" /
                                          "VERA_MONO_MANIFEST_V1.json")
            except (OSError, NotImplementedError) as exc:
                if getattr(exc, "winerror", None) in (5, 1314):
                    self.skipTest("Windows symlink privilege unavailable")
                raise
            # An operator-supplied external path cannot be trusted after
            # a check even when the replacement is syntactically valid JSON.
            with self.assertRaises(loopback.LoopbackRejected):
                workflow._read(checked_path, workflow.MAX_MANIFEST_BYTES)

    def test_scenario_uses_descriptor_witness_not_path_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            scenario = synthetic_scenario()
            source_path = folder / "human-case.json"
            write_json(source_path, scenario)
            manifest = {"schema": "MINI_VERA_EXTERNAL_CASE_LIST_V1", "cases": [
                {"case_id": scenario["case_id"], "scenario_path": str(source_path)}]}
            # Before the fix, this path-only reader was the very mechanism
            # permitting a swap after _external. The hardened scheduler must
            # validate the dict obtained from its pinned descriptor.
            with patch.object(withheld_dialogue, "load_scenario",
                              side_effect=AssertionError("unsafe pathname reopen")):
                schedule = workflow.prepare_schedule(manifest, secret_seed=b"K" * 32)
            self.assertEqual(len(schedule["cases_in_randomized_order"]), 1)

    def test_seed_and_output_use_descriptors_not_path_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            scenario = synthetic_scenario()
            source_path = folder / "external-case.json"
            write_json(source_path, scenario)
            manifest_path = folder / "manifest.json"
            write_json(manifest_path, {"schema": "MINI_VERA_EXTERNAL_CASE_LIST_V1",
                                       "cases": [{"case_id": scenario["case_id"],
                                                  "scenario_path": str(source_path)}]})
            seed_path = folder / "seed.bin"
            seed_path.write_bytes(b"S" * 32)
            output = folder / "private-schedule.json"
            original_read_bytes = Path.read_bytes

            def reject_unpinned_reads(path):
                if path in (seed_path, output):
                    raise AssertionError("unsafe pathname reread")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", reject_unpinned_reads):
                if os.name == "nt":
                    with self.assertRaisesRegex(loopback.LoopbackRejected,
                                                "Windows private evaluation output HOLD"):
                        workflow.main([
                            "schedule", "--case-list", str(manifest_path),
                            "--secret-seed-file", str(seed_path),
                            "--output", str(output),
                        ])
                    self.assertFalse(output.exists())
                    return
                with redirect_stdout(StringIO()):
                    self.assertEqual(workflow.main([
                        "schedule", "--case-list", str(manifest_path),
                        "--secret-seed-file", str(seed_path),
                        "--output", str(output),
                    ]), 0)
            self.assertEqual(json.loads(output.read_text())
                             ["schema"], "MINI_VERA_PRIVATE_CASE_SCHEDULE_V1")

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "descriptor-anchored directory substitution test is Linux-specific")
    def test_external_output_parent_swap_is_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            allowed = folder / "allowed"
            moved = folder / "moved"
            attacker_target = folder / "attacker-target"
            allowed.mkdir()
            attacker_target.mkdir()
            output = allowed / "result.json"
            original_external = workflow._external

            def swap_after_check(candidate):
                checked = original_external(candidate)
                if candidate == output:
                    allowed.rename(moved)
                    try:
                        allowed.symlink_to(attacker_target, target_is_directory=True)
                    except (OSError, NotImplementedError) as exc:
                        if getattr(exc, "winerror", None) in (5, 1314):
                            self.skipTest("Windows symlink privilege unavailable")
                        raise
                return checked

            # Old absolute O_EXCL creation would place result.json in the
            # attacker-target directory. The new parent-handle-relative
            # creation rejects the changed final parent before writing.
            with patch.object(workflow, "_external", swap_after_check):
                with self.assertRaises(loopback.LoopbackRejected):
                    workflow._exclusive_output(output, {"schema": "OUTPUT_SWAP_TEST"})
            self.assertFalse((attacker_target / "result.json").exists())

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "descriptor-anchored directory replacement test is Linux-specific")
    def test_same_path_replacement_parent_cannot_receive_exclusive_output(self):
        # An attacker who can rename directories can replace a formerly
        # approved parent with a DIFFERENT directory of the same pathname.
        # Path equivalence alone is not an identity/custody witness.
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            allowed, moved = folder / "allowed", folder / "moved"
            allowed.mkdir()
            output = allowed / "private-output.json"
            original_external = workflow._external

            def replace_with_same_name(candidate):
                checked = original_external(candidate)
                if candidate == output:
                    allowed.rename(moved)
                    allowed.mkdir()
                return checked

            with patch.object(workflow, "_external", replace_with_same_name):
                with self.assertRaises(loopback.LoopbackRejected):
                    workflow._exclusive_output(output, {"schema": "PRIVATE_OUTPUT"})
            self.assertFalse((allowed / output.name).exists())
            self.assertFalse((moved / output.name).exists())

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "post-create opened parent witness test is Linux-specific")
    def test_parent_rename_at_child_creation_must_not_report_success(self):
        # With a pinned dir_fd, a co-privileged actor can still move that
        # directory between the first identity check and child creation.
        # The already-written file cannot be unwritten, but the caller must
        # never receive a success receipt for the wrong destination.
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            allowed, moved = folder / "allowed", folder / "moved"
            allowed.mkdir()
            output = allowed / "private.json"
            original_open = workflow.os.open
            changed = False

            def move_after_verification(path, flags, *args, **kwargs):
                nonlocal changed
                if path == output.name and "dir_fd" in kwargs and not changed:
                    changed = True
                    allowed.rename(moved)
                    allowed.mkdir()
                return original_open(path, flags, *args, **kwargs)

            with patch.object(workflow.os, "open", side_effect=move_after_verification):
                with self.assertRaisesRegex(loopback.LoopbackRejected,
                                            "parent changed after output creation"):
                    workflow._exclusive_output(output, {"schema": "PARENT_MOVED"})
            self.assertTrue(changed)
            self.assertFalse((allowed / output.name).exists())
            # This is an acknowledged write-before-detection, not a claim
            # that the payload remained secret or that removal was safe.
            self.assertTrue((moved / output.name).exists())

    def test_windows_private_output_refuses_unqualified_inherited_acl(self):
        # The previous source created a file with ObjectAttributes SecurityDescriptor
        # unset. This inherits parent ACL and is not proof of private custody.
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            with self.assertRaisesRegex(loopback.LoopbackRejected,
                                        "Windows private evaluation output HOLD"):
                workflow._windows_create_in_parent(parent, "private-output.json")
            self.assertFalse((parent / "private-output.json").exists())


if __name__ == "__main__":
    unittest.main()
