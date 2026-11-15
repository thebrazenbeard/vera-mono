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

    def test_rejects_reordered_turns_and_arm_blocks(self):
        for rows in (self.rows[::-1],
                     [self.rows[1], self.rows[0], *self.rows[2:]],
                     [*self.rows[3:6], *self.rows[:3]]):
            with self.subTest(order=[(r['arm'], r['turn_index']) for r in rows]):
                with self.assertRaisesRegex(ValueError, 'order'):
                    self.audit(rows)

    def test_rejects_invalid_token_counts(self):
        for bad in (-1, True, 1.5, None):
            with self.subTest(bad=bad):
                rows = [dict(r) for r in self.rows]
                rows[0]['eval_count'] = bad
                with self.assertRaisesRegex(ValueError, 'eval_count'):
                    self.audit(rows)

    def test_second_case_reverses_prompt_arm_order(self):
        from audit_social_behavior_transfer import audit_records
        other = {
            "id": "fictional_two",
            "turns": ["Different question", "Different correction",
                      "What about that change?"],
            "criteria": {"required": ["different"], "forbidden": ["invented"]},
        }
        fixture = dict(self.fixture, cases=[*self.fixture["cases"], other])
        raw = json.dumps(fixture, sort_keys=True).encode("utf8")
        sha = hashlib.sha256(raw).hexdigest()
        original = [dict(r, fixture_sha256=sha) for r in self.rows]
        added = []
        for arm in ("judgment_v3", "base"):
            system = hashlib.sha256(
                messages_for_arm(other, arm)[0]["content"].encode()
            ).hexdigest()
            for turn in (1, 2, 3):
                old = next(
                    r for r in self.rows
                    if r["arm"] == arm and r["turn_index"] == turn
                )
                added.append(dict(
                    old,
                    case_id=other["id"],
                    fixture_sha256=sha,
                    system_sha256=system,
                    user=other["turns"][turn - 1],
                    presented_user=render_turn(other, arm, turn),
                ))
        args = dict(arms=("base", "judgment_v3"), model=self.model,
                    digest=self.digest, seed=79)
        self.assertEqual(
            audit_records(raw, original + added, **args)["records"], 12
        )
        with self.assertRaisesRegex(ValueError, "order"):
            audit_records(raw, original + added[3:] + added[:3], **args)

    def test_pinned_result_hash_detects_response_file_changes(self):
        from audit_social_behavior_transfer import check_results_digest
        original = b'{"response":"genuine"}\n'
        expected = hashlib.sha256(original).hexdigest()
        self.assertEqual(
            check_results_digest(original, expected),
            {"sha256": expected, "pinned": True},
        )
        self.assertEqual(
            check_results_digest(original, None),
            {"sha256": expected, "pinned": False},
        )
        with self.assertRaisesRegex(ValueError, "results sha256 mismatch"):
            check_results_digest(original.replace(b"genuine", b"forged!"), expected)
        with self.assertRaisesRegex(ValueError, "expected_results_sha256"):
            check_results_digest(original, "wrong-digest")

    def test_rejects_undeclared_attestation_metadata(self):
        rows = [dict(r) for r in self.rows]
        rows[0]["model_response_authenticated"] = True
        # A row must not smuggle an authoritative-looking attestation.
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            self.audit(rows)

    def test_rejects_ambiguous_duplicate_json_response_keys(self):
        from audit_social_behavior_transfer import parse_results_bytes
        row = json.dumps(self.rows[0], sort_keys=True)
        original = '"response": "base reply 1"'
        self.assertIn(original, row)
        row = row.replace(
            original, '"response": "forged reply", "response": "base reply 1"', 1
        )
        # Vanilla json.loads silently uses the last value: this parsed
        # response currently passes every existing audit field check.
        self.assertEqual(
            self.audit([json.loads(row), *self.rows[1:]])["records"], 6
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            parse_results_bytes((row + "\n").encode("utf8"))

    def test_truncations_are_reported_without_being_called_complete(self):
        rows = [dict(r) for r in self.rows]
        rows[5]["done_reason"] = "length"
        report = self.audit(rows)
        self.assertEqual((report["complete"], report["truncated"]), (5, 1))


if __name__ == "__main__":
    unittest.main()
