"""Real weight updates, deterministic held-out prediction, and safe checkpoints."""

import json
import tempfile
import unittest
from pathlib import Path

from mini_vera.learning import IntentLearner, LABELS


EXAMPLES = [
    ("challenge the weak assumption", "challenge"),
    ("challenge that conclusion", "challenge"),
    ("question the assumption carefully", "challenge"),
    ("support me through this", "support"),
    ("I need support and kindness", "support"),
    ("offer gentle support please", "support"),
    ("probe the actual system", "probe"),
    ("probe with a test", "probe"),
    ("run the system test", "probe"),
    ("directly build the component", "direct"),
    ("direct action and build now", "direct"),
    ("please build the feature", "direct"),
    ("identity of yourself", "identity"),
    ("explain your identity", "identity"),
    ("what is your identity", "identity"),
    ("unknown unrelated subject", "unknown"),
    ("unknown topic outside scope", "unknown"),
    ("this is an unrelated topic", "unknown"),
]


class LearningTests(unittest.TestCase):
    def test_weights_learn_and_generalize_to_disjoint_text(self):
        model = IntentLearner(seed=41)
        before = model.to_dict()["weights"]
        metrics = model.fit(EXAMPLES, epochs=80)
        self.assertEqual(metrics["samples"], len(EXAMPLES))
        self.assertNotEqual(before, model.weights)
        held_out = [
            ("challenge the assumption again", "challenge"),
            ("I need gentle support", "support"),
            ("probe the system with a test", "probe"),
            ("build the component please", "direct"),
            ("explain the identity of yourself", "identity"),
        ]
        guesses = [model.predict(text)["label"] for text, _ in held_out]
        self.assertGreaterEqual(sum(a == b for a, (_, b) in zip(guesses, held_out)), 4)
        self.assertTrue(all(model.predict(text)["advisory_only"] for text, _ in held_out))

    def test_repeatable_training(self):
        a, b = IntentLearner(seed=12), IntentLearner(seed=12)
        a.fit(EXAMPLES, epochs=15)
        b.fit(EXAMPLES, epochs=15)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(set(a.predict("challenge this")["probabilities"]), set(LABELS))

    def test_round_trip_contains_no_examples(self):
        model = IntentLearner(seed=3)
        model.fit(EXAMPLES, epochs=10)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            model.save(path)
            self.assertNotIn("challenge the weak assumption", path.read_text())
            restored = IntentLearner.load(path)
            self.assertEqual(model.to_dict(), restored.to_dict())
            self.assertEqual(model.predict("identity please"), restored.predict("identity please"))

    def test_malformed_checkpoint_rejected(self):
        model = IntentLearner()
        model.fit(EXAMPLES, epochs=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for mutate in (
                lambda d: d.update(labels=["admin"]),
                lambda d: d["weights"][0].pop(),
                lambda d: d["bias"].__setitem__(0, float("nan")),
                lambda d: d.update(extra="unexpected"),
            ):
                data = model.to_dict()
                mutate(data)
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    IntentLearner.load(path)
            path.write_text("{malformed", encoding="utf-8")
            with self.assertRaises(ValueError):
                IntentLearner.load(path)

    def test_private_data_and_untrusted_label_rejected(self):
        model = IntentLearner()
        for examples in (
            [("email me at patrick@example.com", "direct")],
            [("password: abc123", "support")],
            [("do something", "authorize-write")],
        ):
            with self.assertRaises(ValueError):
                model.fit(examples)
        self.assertEqual(model.predict("What now?")["label"], "unknown")
        self.assertTrue(model.predict("What now?")["advisory_only"])

    def test_compute_limits(self):
        model = IntentLearner()
        with self.assertRaises(ValueError):
            model.fit(EXAMPLES, epochs=201)
        with self.assertRaises(ValueError):
            model.fit(EXAMPLES * 112)
        with self.assertRaises(ValueError):
            model.predict("x" * 2049)


if __name__ == "__main__":
    unittest.main()
