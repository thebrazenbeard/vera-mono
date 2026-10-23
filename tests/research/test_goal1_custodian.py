"""Adversarial tests for the process-isolated synthetic challenge custodian."""
from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = "research.goal1_evaluator.custodian"
TEST_SEED = "1"


class ControllerClient:
    def __init__(self, db: Path):
        env = os.environ.copy()
        env["VERA_EVAL_TEST_MODE"] = "1"
        self.process = subprocess.Popen(
            [sys.executable, "-m", MODULE, "--db", str(db), "--test-seed", TEST_SEED],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=ROOT,
            env=env,
        )

    def send(self, request: dict[str, object]) -> dict[str, object]:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr is not None else ""
            raise AssertionError(f"controller process exited without a response: {stderr}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"controller emitted invalid JSON: {line!r}") from exc

    def close(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            code = self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            code = self.process.wait(timeout=5)
        stderr = self.process.stderr.read() if self.process.stderr is not None else ""
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()
        if code != 0:
            raise AssertionError(f"controller process exit {code}: {stderr}")


SESSIONS: dict[str, ControllerClient] = {}


def call(db: Path, request: dict[str, object]) -> dict[str, object]:
    key = str(db.resolve())
    client = SESSIONS.get(key)
    if client is None or client.process.poll() is not None:
        client = ControllerClient(db)
        SESSIONS[key] = client
    return client.send(request)


def restart(db: Path) -> None:
    client = SESSIONS.pop(str(db.resolve()), None)
    if client is not None:
        client.close()


def issue(db: Path, phase: str) -> dict[str, object]:
    result = call(db, {"op": "issue", "phase": phase})
    if not result.get("ok"):
        raise AssertionError(result)
    return result


def commit(db: Path, challenge: dict[str, object], candidate: str, prediction: str, p_a: float = 0.5) -> dict[str, object]:
    return call(db, {
        "op": "commit",
        "challenge_id": challenge["challenge_id"],
        "candidate_id": candidate,
        "prediction": prediction,
        "p_a": p_a,
    })


def fit_parity(train: list[tuple[str, str]]) -> tuple[int, list[int]]:
    labels = [0 if label == "A" else 1 for _, label in train]
    bias = labels[0]
    weights = [labels[i + 1] ^ bias for i in range(3)]
    return bias, weights


def parity_prediction(bits: str, bias: int, weights: list[int]) -> str:
    y = bias ^ (sum(int(bit) * weight for bit, weight in zip(bits, weights)) % 2)
    return "B" if y else "A"


class CustodianProcessTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in list(SESSIONS):
            client = SESSIONS.pop(key)
            client.close()

    def test_public_challenge_is_opaque_and_feedback_requires_prior_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "private-controller.sqlite"
            challenge = issue(db, "train")
            self.assertEqual(set(challenge), {"ok", "challenge_id", "features"})
            self.assertNotIn("label", challenge)
            self.assertNotIn("expected_label", challenge)
            self.assertNotIn("phase", challenge)
            self.assertNotIn("split", challenge)
            self.assertNotIn("rule_version", challenge)

            early = call(db, {"op": "feedback", "challenge_id": challenge["challenge_id"]})
            self.assertFalse(early["ok"])
            self.assertIn("committed", str(early["error"]))

            poisoned = call(db, {
                "op": "commit",
                "challenge_id": challenge["challenge_id"],
                "candidate_id": "candidate",
                "prediction": "A",
                "p_a": 0.5,
                "label": "A",
            })
            self.assertFalse(poisoned["ok"])
            self.assertIn("request fields", str(poisoned["error"]))

            receipt = commit(db, challenge, "candidate", "A")
            self.assertTrue(receipt["ok"])
            feedback = call(db, {"op": "feedback", "challenge_id": challenge["challenge_id"]})
            self.assertTrue(feedback["ok"])
            self.assertIn(feedback["label"], ("A", "B"))
            self.assertLess(receipt["commit_sequence"], feedback["feedback_sequence"])

    def test_one_use_commit_feedback_and_candidate_identity_survive_process_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "private-controller.sqlite"
            first = issue(db, "train")
            self.assertTrue(commit(db, first, "candidate-1", "A")["ok"])
            restart(db)  # the replay attempt is issued by a distinct OS process

            replay_commit = commit(db, first, "candidate-1", "B")
            self.assertFalse(replay_commit["ok"])
            self.assertIn("already-used", str(replay_commit["error"]))

            replay_feedback = call(db, {"op": "feedback", "challenge_id": first["challenge_id"]})
            self.assertTrue(replay_feedback["ok"])
            replay_feedback = call(db, {"op": "feedback", "challenge_id": first["challenge_id"]})
            self.assertFalse(replay_feedback["ok"])

            second = issue(db, "train")
            rotated = commit(db, second, "candidate-rotated", "A")
            self.assertFalse(rotated["ok"])
            self.assertIn("identity is fixed", str(rotated["error"]))
            self.assertTrue(commit(db, second, "candidate-1", "A")["ok"])

    def test_holdout_is_blocked_until_training_feedback_is_consumed(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "private-controller.sqlite"
            blocked = call(db, {"op": "issue", "phase": "holdout"})
            self.assertFalse(blocked["ok"])
            self.assertIn("training feedback", str(blocked["error"]))

    def test_train_and_holdout_features_are_disjoint_and_hidden_from_issue_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "private-controller.sqlite"
            training_features = []
            for _ in range(4):
                challenge = issue(db, "train")
                training_features.extend(challenge["features"])
                receipt = commit(db, challenge, "candidate", "A")
                self.assertTrue(receipt["ok"])
                self.assertTrue(call(db, {"op": "feedback", "challenge_id": challenge["challenge_id"]})["ok"])

            holdout_features = []
            for _ in range(4):
                challenge = issue(db, "holdout")
                holdout_features.extend(challenge["features"])
                self.assertEqual(set(challenge), {"ok", "challenge_id", "features"})
                self.assertTrue(commit(db, challenge, "candidate", "A")["ok"])
            self.assertEqual(len(training_features), 4)
            self.assertEqual(len(holdout_features), 4)
            self.assertTrue(set(training_features).isdisjoint(set(holdout_features)))

    def test_holdout_scoring_is_aggregate_budgeted_and_one_use(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "private-controller.sqlite"
            for _ in range(4):
                challenge = issue(db, "train")
                self.assertTrue(commit(db, challenge, "candidate", "A", 0.99)["ok"])
                self.assertTrue(call(db, {"op": "feedback", "challenge_id": challenge["challenge_id"]})["ok"])
            for _ in range(4):
                challenge = issue(db, "holdout")
                self.assertTrue(commit(db, challenge, "candidate", "A", 0.99)["ok"])

            score = call(db, {"op": "score_holdout"})
            self.assertTrue(score["ok"])
            self.assertEqual(score["scored_cases"], 4)
            self.assertEqual(score["budget_units"], 8)
            self.assertIn("brier_score", score)
            self.assertNotIn("label", score)
            self.assertNotIn("per_case", score)
            self.assertNotIn("challenge_ids", score)
            self.assertFalse(call(db, {"op": "score_holdout"})["ok"])

    def test_always_abstain_is_not_rewarded_as_high_accuracy_or_calibration(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "private-controller.sqlite"
            for _ in range(4):
                challenge = issue(db, "train")
                self.assertTrue(commit(db, challenge, "candidate", "ABSTAIN", 0.5)["ok"])
                self.assertTrue(call(db, {"op": "feedback", "challenge_id": challenge["challenge_id"]})["ok"])
            for _ in range(4):
                challenge = issue(db, "holdout")
                self.assertTrue(commit(db, challenge, "candidate", "ABSTAIN", 0.5)["ok"])
            score = call(db, {"op": "score_holdout"})
            self.assertEqual(score["accuracy"], 0.0)
            self.assertEqual(score["coverage"], 0.0)
            self.assertIsNone(score["selective_accuracy"])
            self.assertAlmostEqual(score["brier_score"], 0.25)

    def test_truth_store_tampering_is_detected_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "private-controller.sqlite"
            issue(db, "train")
            restart(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute("UPDATE challenge SET expected_label=CASE expected_label WHEN 'A' THEN 'B' ELSE 'A' END WHERE ordinal=0")
            result = call(db, {"op": "issue", "phase": "train"})
            self.assertFalse(result["ok"])
            self.assertIn("truth-store integrity", str(result["error"]))

    def test_event_journal_tampering_is_detected_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "private-controller.sqlite"
            issue(db, "train")
            restart(db)
            with closing(sqlite3.connect(db)) as connection, connection:
                connection.execute("UPDATE event SET digest=? WHERE seq=1", ("0" * 64,))
            result = call(db, {"op": "issue", "phase": "train"})
            self.assertFalse(result["ok"])
            self.assertIn("event-journal integrity", str(result["error"]))

    def test_adaptive_rule_inference_beats_matched_frozen_placebo_shuffled_and_memorizer(self):
        results: dict[str, dict[str, object]] = {}
        for arm in ("adaptive", "frozen", "placebo", "shuffled", "memorizer"):
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as directory:
                db = Path(directory) / f"{arm}.sqlite"
                training: list[tuple[str, str]] = []
                memorized: dict[str, str] = {}
                for _ in range(4):
                    challenge = issue(db, "train")
                    bits = str(challenge["features"][0]).split(":", 1)[1]
                    self.assertTrue(commit(db, challenge, arm, "A", 0.5)["ok"])
                    response = call(db, {"op": "feedback", "challenge_id": challenge["challenge_id"]})
                    self.assertTrue(response["ok"])
                    label = str(response["label"])
                    training.append((bits, label))
                    memorized[bits] = label

                fit_data = list(reversed(training)) if arm == "shuffled" else training
                bias, weights = fit_parity(fit_data)
                for _ in range(4):
                    challenge = issue(db, "holdout")
                    bits = str(challenge["features"][0]).split(":", 1)[1]
                    if arm == "adaptive":
                        prediction = parity_prediction(bits, bias, weights)
                        p_a = 0.99 if prediction == "A" else 0.01
                    elif arm == "shuffled":
                        prediction = parity_prediction(bits, bias, weights)
                        p_a = 0.99 if prediction == "A" else 0.01
                    elif arm == "memorizer":
                        prediction = memorized.get(bits, "A")
                        p_a = 0.99 if prediction == "A" else 0.01
                    elif arm == "placebo":
                        prediction, p_a = "A", 0.99
                    else:
                        prediction, p_a = "A", 0.5
                    self.assertTrue(commit(db, challenge, arm, prediction, p_a)["ok"])
                score = call(db, {"op": "score_holdout"})
                self.assertTrue(score["ok"])
                results[arm] = score

        self.assertEqual({result["budget_units"] for result in results.values()}, {8})
        self.assertEqual(results["adaptive"]["accuracy"], 1.0)
        self.assertLess(results["adaptive"]["brier_score"], 0.001)
        for arm in ("frozen", "placebo", "memorizer", "shuffled"):
            self.assertLess(results[arm]["accuracy"], 1.0)
        self.assertGreater(results["placebo"]["brier_score"], results["frozen"]["brier_score"])
        # This is a deterministic mechanism check, not a statistical claim
        # about QVR or any real model.


if __name__ == "__main__":
    unittest.main(verbosity=2)
