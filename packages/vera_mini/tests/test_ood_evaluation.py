"""Frozen, author-authored OOD challenge set; inference-only evaluation.

Passing these tests means dataset integrity and reproducibility, not accuracy.
Never make training or checkpoint choices using this set's predictions.
"""

from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import unittest
from unittest.mock import patch

from mini_vera.learning import IntentLearner, LABELS


ROOT = Path(__file__).resolve().parents[1]
OOD_PATH = ROOT / "data/ood_test.jsonl"
FROZEN_OOD_SHA256 = "47a879128c6e08356abaf8155e108f12984afc4622faf4e63059c73498bf7cb2"
EXPECTED_LABELS = set(LABELS)


def canonical(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def read_records(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


class OODEvaluationTests(unittest.TestCase):
    def test_frozen_hash_strict_schema_and_balance(self):
        self.assertEqual(hashlib.sha256(OOD_PATH.read_bytes()).hexdigest(),
                         FROZEN_OOD_SHA256)
        rows = read_records(OOD_PATH)
        self.assertEqual(len(rows), 72)
        self.assertTrue(all(type(row) is dict and set(row) ==
                            {"text", "label", "group"} for row in rows))
        self.assertTrue(all(type(row["text"]) is str and
                            10 <= len(row["text"]) <= 512 and
                            type(row["label"]) is str and
                            row["label"] in EXPECTED_LABELS and
                            type(row["group"]) is str and row["group"]
                            for row in rows))
        self.assertEqual(Counter(row["label"] for row in rows),
                         {label: 12 for label in LABELS})
        groups = Counter(row["group"] for row in rows)
        self.assertEqual(len(groups), 12)
        self.assertEqual(set(groups.values()), {6})
        for group in groups:
            self.assertEqual({row["label"] for row in rows if row["group"] == group},
                             EXPECTED_LABELS)

    def test_no_train_validation_test_text_or_scenario_leakage(self):
        ood = read_records(OOD_PATH)
        ood_groups = {r["group"] for r in ood}
        ood_canonical = [canonical(r["text"]) for r in ood]
        self.assertEqual(len(ood_canonical), len(set(ood_canonical)))
        for split in ("train", "validation", "test"):
            existing = read_records(ROOT / "data" / f"{split}.jsonl")
            with self.subTest(split=split):
                self.assertFalse(ood_groups & {r["group"] for r in existing})
                existing_canonical = [canonical(r["text"]) for r in existing]
                self.assertFalse(set(ood_canonical) & set(existing_canonical))
                # A conservative mechanical near-duplicate tripwire; it does
                # not establish deeper semantic or stylistic independence.
                for a in ood_canonical:
                    for b in existing_canonical:
                        self.assertLess(SequenceMatcher(None, a, b).ratio(), 0.85)

    def test_original_training_checkpoint_remains_exact(self):
        receipt = json.loads((ROOT / "data/training_receipt_v1.json")
                             .read_text(encoding="utf-8"))
        for split in ("train", "validation", "test"):
            self.assertEqual(hashlib.sha256(
                (ROOT / "data" / f"{split}.jsonl").read_bytes()).hexdigest(),
                receipt["data_sha256"][split])
        checkpoint = ROOT / "mini_vera/resources/INTENT_POLICY_V1.json"
        self.assertEqual(hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                         receipt["checkpoint_sha256"])

    def test_inference_only_and_frozen_baseline(self):
        rows = read_records(OOD_PATH)
        checkpoint = ROOT / "mini_vera/resources/INTENT_POLICY_V1.json"
        with patch.object(IntentLearner, "fit", side_effect=AssertionError(
                "OOD evaluation must never train")):
            model = IntentLearner.load(checkpoint)
            guesses = [model.predict(row["text"]) for row in rows]
        self.assertEqual(len(guesses), 72)
        self.assertTrue(all(g["label"] in EXPECTED_LABELS and
                            g["advisory_only"] is True for g in guesses))
        self.assertTrue(all(abs(sum(g["probabilities"].values()) - 1) < 1e-10
                            for g in guesses))
        # Predeclared baselines: the original tied-majority class from the
        # training receipt is 'direct'; a constant unknown has same score.
        self.assertEqual(sum(row["label"] == "direct" for row in rows), 12)
        self.assertEqual(sum(row["label"] == "unknown" for row in rows), 12)


if __name__ == "__main__":
    unittest.main()
