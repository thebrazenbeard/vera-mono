"""Synthetic human-rating fixtures; no genuine withheld cases or model loads."""

from __future__ import annotations

from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
