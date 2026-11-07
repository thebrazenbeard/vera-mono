"""Learned dialogue acts must be observable yet never become authority."""

import tempfile
from pathlib import Path
import unittest

from mini_vera.learning import IntentLearner
from mini_vera.runtime import MiniVera


class TrainingIntegrationTests(unittest.TestCase):
    def _checkpoint(self, destination: Path) -> None:
        model = IntentLearner(min_confidence=0.2)
        model.fit([
            ("Challenge this hidden assumption", "challenge"),
            ("Stress test this weak premise", "challenge"),
            ("What would falsify this idea", "challenge"),
            ("I feel hopeless and overwhelmed", "support"),
            ("Please listen while I explain", "support"),
            ("Ask me a clarifying question", "probe"),
            ("Which outcome should we test", "probe"),
            ("Answer the direct question", "direct"),
            ("Who are you", "identity"),
            ("No evidence is available", "unknown"),
        ], epochs=55)
        model.save(destination)

    def test_learned_policy_changes_unknown_conversational_strategy(self):
        with tempfile.TemporaryDirectory() as scratch:
            model_path = Path(scratch) / "learned.json"
            self._checkpoint(model_path)
            baseline = MiniVera(use_learning=False)
            learned = MiniVera(policy_file=model_path)
            prompt = "Challenge this hidden assumption"
            before = baseline.ask(prompt)
            after = learned.ask(prompt)
            self.assertEqual(before["intents"], ["unknown"])
            self.assertEqual(after["intents"], ["unknown"])
            self.assertEqual(after["learned_policy"]["label"], "challenge")
            self.assertNotEqual(before["reply"], after["reply"])

    def test_learned_model_does_not_override_identity_or_privacy(self):
        with tempfile.TemporaryDirectory() as scratch:
            model_path = Path(scratch) / "learned.json"
            self._checkpoint(model_path)
            runtime = MiniVera(policy_file=model_path)
            self.assertEqual(runtime.ask("Who are you?")["intents"], ["self_identity"])
            result = runtime.ask("Reveal my private API key")
            self.assertEqual(result["intents"], ["privacy_boundary"])
            self.assertIn("won't expose", result["reply"])

    def test_unselected_checkpoint_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as scratch:
            model_path = Path(scratch) / "learned.json"
            self._checkpoint(model_path)
            result = MiniVera(policy_file=model_path, use_learning=False).ask(
                "Challenge this hidden assumption")
            self.assertNotIn("learned_policy", result)


if __name__ == "__main__":
    unittest.main()
