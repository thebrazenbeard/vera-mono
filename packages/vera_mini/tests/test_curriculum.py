"""Training provenance and reproducibility of the small original policy."""

import hashlib
import json
from pathlib import Path
import unittest

from mini_vera.learning import IntentLearner, LABELS


ROOT = Path(__file__).resolve().parents[1]


class CurriculumTests(unittest.TestCase):
    def test_split_groups_texts_and_balance(self):
        corpus = {}
        all_groups = set()
        all_texts = set()
        for name, expected in (("train", 72), ("validation", 36), ("test", 36)):
            rows = [json.loads(line) for line in (ROOT / "data" / f"{name}.jsonl")
                    .read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(len(rows), expected)
            self.assertEqual({r["label"] for r in rows}, set(LABELS))
            self.assertTrue(all(set(r) == {"text", "label", "group"} for r in rows))
            groups = {r["group"] for r in rows}
            texts = {" ".join(r["text"].casefold().split()) for r in rows}
            self.assertFalse(groups & all_groups)
            self.assertFalse(texts & all_texts)
            self.assertEqual(len(texts), len(rows))
            all_groups.update(groups)
            all_texts.update(texts)
            corpus[name] = rows
        self.assertEqual(len(all_texts), 144)

    def test_checkpoint_receipt_matches_and_can_reproduce(self):
        receipt = json.loads((ROOT / "data/training_receipt_v1.json").read_text(encoding="utf-8"))
        for name in ("train", "validation", "test"):
            blob = (ROOT / "data" / f"{name}.jsonl").read_bytes()
            self.assertEqual(hashlib.sha256(blob).hexdigest(), receipt["data_sha256"][name])
        checkpoint = ROOT / "mini_vera/resources/INTENT_POLICY_V1.json"
        self.assertEqual(hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                         receipt["checkpoint_sha256"])
        released = IntentLearner.load(checkpoint)
        train = [json.loads(line) for line in (ROOT / "data/train.jsonl")
                 .read_text(encoding="utf-8").splitlines() if line]
        duplicate = IntentLearner(seed=receipt["seed"])
        duplicate.fit([(row["text"], row["label"]) for row in train],
                      epochs=receipt["training"]["epochs"])
        self.assertEqual(duplicate.to_dict(), released.to_dict())


if __name__ == "__main__":
    unittest.main()
