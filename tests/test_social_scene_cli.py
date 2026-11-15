"""Subprocess-level proof that source decisions precede model generation."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "route_social_scene.py"


class TestSocialSceneCLI(unittest.TestCase):
    def invoke(self, turns):
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--model", "qwen3.5:0.8b"],
            input=json.dumps({"user_turns": turns}),
            text=True, capture_output=True, timeout=25,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def test_source_grounded_route_runs_without_model_dependency(self):
        row = self.invoke([
            "State: Ava is the pilot; Ben is the passenger.",
            "Correction: Ben is the pilot, Ava is the passenger.",
            "Who is the pilot now? One name only.",
        ])
        self.assertEqual(row["answer"], "Ben")
        self.assertEqual(row["status"], "RESOLVED")
        self.assertFalse(row["model_used"])
        self.assertFalse(row["external_effect_authorized"])
        self.assertFalse(row["canonical_memory_admitted"])

    def test_unknown_scoped_actor_does_not_query_model(self):
        row = self.invoke([
            "State: Ava is the pilot; Heron is a spacecraft.",
            "Who pilots the Heron now? One name only.",
        ])
        self.assertEqual(row["answer"], "UNKNOWN")
        self.assertEqual(row["status"], "UNSUPPORTED_SCOPE")
        self.assertFalse(row["model_used"])


if __name__ == "__main__":
    unittest.main()
