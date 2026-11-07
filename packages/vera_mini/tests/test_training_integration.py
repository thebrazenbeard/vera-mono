"""Learned dialogue acts must be observable yet never become authority."""

import tempfile
from pathlib import Path
import unittest
import io
import hashlib
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from mini_vera.learning import IntentLearner
from mini_vera.runtime import MiniVera, _bundled_policy
from mini_vera.__main__ import main


class TrainingIntegrationTests(unittest.TestCase):
    def _manifest(self, checkpoint: Path) -> Path:
        manifest = checkpoint.with_name(checkpoint.name + ".manifest.json")
        manifest.write_text(json.dumps({
            "schema": "mini-vera-policy-manifest-v1",
            "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            "consent": True,
            "checkpoint": checkpoint.name,
            "created_by": "mini-vera train-policy",
        }), encoding="utf-8")
        return manifest

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
        self._manifest(destination)

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

    def test_missing_manifest_rejects_explicit_checkpoint(self):
        with tempfile.TemporaryDirectory() as scratch:
            checkpoint = Path(scratch) / "learned.json"
            self._checkpoint(checkpoint)
            checkpoint.with_name(checkpoint.name + ".manifest.json").unlink()
            with self.assertRaisesRegex(ValueError, "policy manifest missing"):
                MiniVera(policy_file=checkpoint)
            # Disabling learning remains a true no-load ablation.
            self.assertNotIn("learned_policy", MiniVera(
                policy_file=checkpoint, use_learning=False).ask("Challenge this"))

    def test_tampered_checkpoint_rejected_even_if_json_is_valid(self):
        with tempfile.TemporaryDirectory() as scratch:
            checkpoint = Path(scratch) / "learned.json"
            self._checkpoint(checkpoint)
            checkpoint.write_bytes(checkpoint.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "SHA-256 does not match"):
                MiniVera(policy_file=checkpoint)

    def test_manifest_consent_digest_and_basename_must_match(self):
        with tempfile.TemporaryDirectory() as scratch:
            checkpoint = Path(scratch) / "learned.json"
            self._checkpoint(checkpoint)
            manifest = checkpoint.with_name(checkpoint.name + ".manifest.json")
            original = json.loads(manifest.read_text(encoding="utf-8"))
            for changes in (
                {"consent": False},
                {"sha256": "0" * 64},
                {"checkpoint": "different.json"},
                {"created_by": "unknown"},
                {"schema": "invalid"},
            ):
                with self.subTest(changes=changes):
                    manifest.write_text(json.dumps(original | changes), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        MiniVera(policy_file=checkpoint)

    def test_malformed_or_oversized_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as scratch:
            checkpoint = Path(scratch) / "learned.json"
            self._checkpoint(checkpoint)
            manifest = checkpoint.with_name(checkpoint.name + ".manifest.json")
            manifest.write_text('{"consent":true,"consent":false}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate JSON keys"):
                MiniVera(policy_file=checkpoint)
            manifest.write_bytes(b" " * 16_385)
            with self.assertRaisesRegex(ValueError, "size limit"):
                MiniVera(policy_file=checkpoint)

    def test_bundled_checkpoint_is_pinned_to_training_receipt(self):
        root = Path(__file__).resolve().parents[1]
        checkpoint = root / "mini_vera/resources/INTENT_POLICY_V1.json"
        receipt = json.loads((root / "data/training_receipt_v1.json").read_text(
            encoding="utf-8"))
        self.assertEqual(hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                         receipt["checkpoint_sha256"])
        self.assertIsNotNone(MiniVera().policy)
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch)
            resource_dir = source / "resources"
            resource_dir.mkdir()
            (resource_dir / "INTENT_POLICY_V1.json").write_bytes(
                checkpoint.read_bytes() + b"\n")
            with patch("mini_vera.runtime.resources.files", return_value=source):
                with self.assertRaisesRegex(ValueError, "SHA-256 does not match"):
                    _bundled_policy()

    def test_training_cli_refuses_implicit_overwrite(self):
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            source = folder / "approved.jsonl"
            source.write_text('{"text":"Please be direct","label":"direct"}\n',
                              encoding="utf-8")
            checkpoint = folder / "existing.json"
            checkpoint.write_text("sentinel", encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error):
                code = main(["train-policy", "--data", str(source),
                             "--output", str(checkpoint), "--consent"])
            self.assertEqual(code, 2)
            self.assertEqual(checkpoint.read_text(encoding="utf-8"), "sentinel")
            self.assertIn("overwrite", error.getvalue())

    def test_consented_training_cli_writes_loadable_matching_manifest(self):
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            source = folder / "approved.jsonl"
            source.write_text('{"text":"Challenge this premise","label":"challenge"}\n',
                              encoding="utf-8")
            checkpoint = folder / "trained.json"
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["train-policy", "--data", str(source),
                             "--output", str(checkpoint), "--consent"])
            self.assertEqual(code, 0)
            manifest_path = checkpoint.with_name(checkpoint.name + ".manifest.json")
            self.assertEqual(json.loads(output.getvalue())["manifest"], str(manifest_path))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["sha256"],
                             hashlib.sha256(checkpoint.read_bytes()).hexdigest())
            self.assertTrue(manifest["consent"])
            self.assertIsNotNone(MiniVera(policy_file=checkpoint).policy)


if __name__ == "__main__":
    unittest.main()
