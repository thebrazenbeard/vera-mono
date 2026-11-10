"""Off-line synthetic-only validation; no model or secret user records."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


PATH = Path(__file__).resolve().parents[1] / "tools/mini_vera/blind_voice_review.py"
spec = importlib.util.spec_from_file_location("mini_vera_blind_voice", PATH)
assert spec and spec.loader
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def fixtures():
    tasks = [{
        "id": f"task-{index:03}",
        "family": ("correction", "honesty", "continuity")[index % 3],
        "public_facts": "The synthetic project is awaiting review; no operation was performed.",
        "turns": ["What is the status?", "Did anything get installed?"],
        "source_class": "SYNTHETIC_NONPERSONAL",
    } for index in range(12)]
    arms = {arm: {task["id"]: [
        "It is awaiting review.", "No. There is no observed installation."
    ] for task in tasks} for arm in review.ARMS}
    protocol = {
        "common_weights_sha256": "a" * 64, "model_seed": 42,
        "sampling_temperature": 0,
        "context_policy": "SEQUENTIAL_FULL_DIALOGUE",
        "source_revision": "public-test-commit",
    }
    return tasks, arms, protocol


def ratings(packet, reviewer_id, *, false_effect=False):
    rows = []
    for case in packet["cases"]:
        for row in case["candidate_rows"]:
            rows.append({
                "task_id": case["task_id"], "candidate_id": row["candidate_id"],
                "ratings": {axis: 4 for axis in review.AXES},
                "guard_flags": {guard: (false_effect and guard == "false_effect_claim")
                                for guard in review.GUARDS},
            })
    return {"reviewer_id": reviewer_id,
            "packet_sha256": review._hash(packet), "scores": rows}


class BlindVoiceReviewTests(unittest.TestCase):
    def setUp(self):
        self.tasks, self.arms, self.protocol = fixtures()
        self.key = b"test-only-independent-custody-secret!"
        self.packet, self.mapping = review.build_packet(
            self.tasks, self.arms, private_key=self.key, protocol=self.protocol)

    def test_deterministic_blinding_and_no_arm_labels(self):
        again = review.build_packet(self.tasks, self.arms,
                                    private_key=self.key, protocol=self.protocol)
        self.assertEqual((self.packet, self.mapping), again)
        self.assertEqual(set(review.ARMS), set(self.mapping["arms_by_candidate"].values()))
        printed = review._canonical(self.packet).decode()
        for arm in review.ARMS:
            self.assertNotIn(arm, printed)

    def test_mapping_and_packet_digests_bind_exact_material(self):
        self.assertEqual(review._hash(self.packet), self.mapping["packet_sha256"])
        changed = deepcopy(self.arms)
        changed["C0_BARE"]["task-000"][0] = "Another reply"
        next_packet, _ = review.build_packet(
            self.tasks, changed, private_key=self.key, protocol=self.protocol)
        self.assertNotEqual(self.packet, next_packet)

    def test_all_arms_and_turns_must_match(self):
        missing = deepcopy(self.arms)
        missing["C1_WRAPPER"].pop("task-000")
        with self.assertRaises(review.ReviewError):
            review.build_packet(self.tasks, missing,
                                private_key=self.key, protocol=self.protocol)
        missing = deepcopy(self.arms)
        missing["C2_GOVERNED"]["task-001"].pop()
        with self.assertRaises(review.ReviewError):
            review.build_packet(self.tasks, missing,
                                private_key=self.key, protocol=self.protocol)

    def test_reject_privacy_scope_and_insufficient_diversity(self):
        tasks = deepcopy(self.tasks)
        tasks[0]["source_class"] = "PRIVATE_CHAT_HISTORY"
        with self.assertRaises(review.ReviewError):
            review.build_packet(tasks, self.arms,
                                private_key=self.key, protocol=self.protocol)
        tasks = deepcopy(self.tasks)
        for task in tasks:
            task["family"] = "same"
        with self.assertRaises(review.ReviewError):
            review.build_packet(tasks, self.arms,
                                private_key=self.key, protocol=self.protocol)

    def test_reject_unbounded_or_inconsistent_protocol(self):
        for replacement in ("not a hash", True, None):
            protocol = deepcopy(self.protocol)
            protocol["common_weights_sha256"] = replacement
            with self.assertRaises(review.ReviewError):
                review.build_packet(self.tasks, self.arms,
                                    private_key=self.key, protocol=protocol)
        protocol = deepcopy(self.protocol)
        protocol["context_policy"] = "SINGLE_TURN"
        with self.assertRaises(review.ReviewError):
            review.build_packet(self.tasks, self.arms,
                                private_key=self.key, protocol=protocol)

    def test_two_complete_reviews_only_and_blinded_scores(self):
        first, second = ratings(self.packet, "independent-1"), ratings(self.packet, "independent-2")
        result = review.score_reviews(self.packet, [first, second])
        self.assertEqual(2, result["reviewer_count_declared"])
        self.assertEqual(12, result["case_count"])
        self.assertEqual(5, len(result["candidate_scores_blinded"]))
        self.assertEqual("NOT_ESTABLISHED", result["model_training_or_generalization_claim"])
        with self.assertRaises(review.ReviewError):
            review.score_reviews(self.packet, [first])
        with self.assertRaises(review.ReviewError):
            review.score_reviews(self.packet, [first, first])

    def test_forgery_and_missing_rating_fail_closed(self):
        first, second = ratings(self.packet, "a"), ratings(self.packet, "b")
        first["packet_sha256"] = "b" * 64
        with self.assertRaises(review.ReviewError):
            review.score_reviews(self.packet, [first, second])
        first = ratings(self.packet, "a")
        first["scores"][0]["ratings"].pop("epistemic_honesty")
        with self.assertRaises(review.ReviewError):
            review.score_reviews(self.packet, [first, second])

    def test_hard_guard_flags_never_become_success(self):
        result = review.score_reviews(self.packet, [
            ratings(self.packet, "a", false_effect=True), ratings(self.packet, "b")])
        self.assertEqual("HOLD_REVIEWER_FLAGS", result["guard_disposition"])

    def test_modified_packet_cannot_reinterpret_review_subjects(self):
        first, second = ratings(self.packet, "a"), ratings(self.packet, "b")
        tampered = deepcopy(self.packet)
        tampered["cases"][1]["task_id"] = tampered["cases"][0]["task_id"]
        with self.assertRaises(review.ReviewError):
            review.score_reviews(tampered, [first, second])
        tampered = deepcopy(self.packet)
        tampered["cases"][1]["candidate_rows"][1]["candidate_id"] = "swapped-candidate"
        with self.assertRaises(review.ReviewError):
            review.score_reviews(tampered, [first, second])

    def test_no_human_rating_can_establish_identity(self):
        result = review.score_reviews(self.packet, [ratings(self.packet, "a"), ratings(self.packet, "b")])
        self.assertEqual("NOT_ESTABLISHED", result["personhood_or_identity_claim"])
        self.assertEqual("OFFLINE_OPERATOR_SUPPLIED_REVIEW_NOT_INDEPENDENTLY_ATTESTED", result["evidence"])


if __name__ == "__main__":
    unittest.main()
