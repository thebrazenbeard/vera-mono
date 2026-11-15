"""Source-only audit: reported multi-turn results must match frozen inputs exactly."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_social_behavior_simple_ab import messages_for_arm, render_turn


class TransferAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = {
            "schema": "VERA_SOCIAL_MULTITURN_HELDOUT_V1",
            "cases": [{
                "id": "fictional_one",
                "turns": ["Question", "Correction", "What changed?"],
                "criteria": {"required": ["correction"], "forbidden": ["forget correction"]}
            }],
        }
        self.raw = json.dumps(self.fixture, sort_keys=True).encode("utf8")
        self.model = "qwen3:4b-instruct"
        self.digest = "pinned-test-digest"
        self.rows = [
            {
                "schema": "VERA_SOCIAL_BEHAVIOR_SIMPLE_AB_V1",
                "case_id": "fictional_one",
                "arm": arm,
                "seed": 79,
                "turn_index": turn,
                "fixture_sha256": hashlib.sha256(self.raw).hexdigest(),
                "system_sha256": hashlib.sha256(
                    messages_for_arm(self.fixture["cases"][0], arm)[0]["content"].encode()
                ).hexdigest(),
                "model": self.model,
                "model_digest": self.digest,
                "user": self.fixture["cases"][0]["turns"][turn - 1],
                "presented_user": render_turn(self.fixture["cases"][0], arm, turn),
                "response": f"{arm} reply {turn}",
                "done_reason": "stop",
                "eval_count": 10,
                "tool_use": False
            }
            for arm in ("base", "judgment_v3")
            for turn in (1, 2, 3)
        ]

    def audit(self, rows=None):
        from audit_social_behavior_transfer import audit_records
        return audit_records(
            self.raw, list(self.rows if rows is None else rows),
            arms=("base", "judgment_v3"), model=self.model,
            digest=self.digest, seed=79,
        )

    def test_exact_clean_and_nontruncation_count(self):
        report = self.audit()
        self.assertEqual(report["records"], 6)
        self.assertEqual(report["cases"], 1)
        self.assertEqual(report["complete"], 6)
        self.assertEqual(report["truncated"], 0)
        self.assertEqual(set(report["final_replies"]), {"fictional_one"})
        self.assertEqual(set(report["final_replies"]["fictional_one"]), {"base", "judgment_v3"})

    def test_rejects_missing_and_duplicate_records(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            self.audit(self.rows[:-1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.audit([*self.rows, self.rows[0]])

    def test_rejects_wrong_actor_turn_or_injected_rubric(self):
        for field, bad in [
            ("user", "different source text"),
            ("presented_user", "swapped recipient"),
            ("system_sha256", "foreign-prompt-hash"),
            ("fixture_sha256", "stale-fixture-hash"),
            ("model_digest", "different-checkpoint"),
            ("tool_use", True)
        ]:
            with self.subTest(field=field):
                rows = [dict(r) for r in self.rows]
                rows[2][field] = bad
                with self.assertRaisesRegex(ValueError, field):
                    self.audit(rows)

    def test_truncations_are_reported_without_being_called_complete(self):
        rows = [dict(r) for r in self.rows]
        rows[5]["done_reason"] = "length"
        report = self.audit(rows)
        self.assertEqual((report["complete"], report["truncated"]), (5, 1))


if __name__ == "__main__":
    unittest.main()
