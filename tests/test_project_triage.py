"""Synthetic-only qualification for native Project cleanup dry-run triage."""

import unittest
from dataclasses import replace

from ingest.project_triage import ProjectEvidence, ProjectTriageError, triage_projects


def project(project_id="project:a", **kwargs):
    fields = dict(
        source_digest="a" * 64, coverage="COMPLETE", active_work=False,
        unique_material=False, outstanding_references=False,
        memory_scope="DEFAULT", file_library_enabled=True,
    )
    fields.update(kwargs)
    return ProjectEvidence(project_id=project_id, **fields)


class ProjectTriageTests(unittest.TestCase):
    def test_preserves_active_unique_or_linked_projects(self):
        for key in ("active_work", "unique_material", "outstanding_references"):
            with self.subTest(key=key):
                result = triage_projects((project(**{key: True}),))
                self.assertEqual(result["records"][0]["disposition"], "PRESERVE")
                self.assertFalse(result["records"][0]["delete_authorized"])

    def test_all_project_only_memory_is_protected_regardless_of_library_access(self):
        for enabled in (False, True, None):
            with self.subTest(enabled=enabled):
                result = triage_projects((project(memory_scope="PROJECT_ONLY", file_library_enabled=enabled),))
                self.assertEqual(result["records"][0]["disposition"], "PRESERVE")
                self.assertIn("PROJECT_ONLY_MEMORY_BOUNDARY", result["records"][0]["reasons"])

    def test_partial_or_unknown_inventory_is_not_eligible(self):
        for candidate in (project(coverage="PARTIAL"), project(active_work=None),
                          project(memory_scope="UNKNOWN"), project(file_library_enabled=None)):
            with self.subTest(candidate=candidate):
                result = triage_projects((candidate,))
                self.assertEqual(result["records"][0]["disposition"], "INSPECT_MISSING_EVIDENCE")

    def test_caller_claimed_receipts_cannot_nominate_retirement(self):
        original = project("project:a")
        redundant = project("project:b", duplicate_of="project:a",
                            duplicate_review_ref="review:1", archive_copy_receipt_ref="archive:1")
        result = triage_projects((redundant, original))
        self.assertEqual(result["records"][0]["disposition"], "PRESERVE")
        self.assertIn("DUPLICATE_TARGET_MUST_BE_RETAINED", result["records"][0]["reasons"])
        self.assertEqual(result["records"][1]["disposition"], "REVIEW_FOR_CONSOLIDATION")
        self.assertIn("UNVERIFIED_CALLER_RECEIPTS", result["records"][1]["reasons"])
        self.assertFalse(result["records"][1]["delete_authorized"])
        self.assertFalse(result["delete_api_available"])
        self.assertFalse(result["retirement_review_available"])
        self.assertEqual(result["native_project_effect"], "NONE")
        self.assertEqual(result["memory_admission_effect"], "NONE")
        self.assertEqual(result["status"], "DRY_RUN_ONLY")

    def test_missing_receipts_or_target_do_not_nominate_retirement(self):
        no_copy = project("project:b", duplicate_of="project:a", duplicate_review_ref="review:1")
        result = triage_projects((project(), no_copy))
        self.assertEqual(result["records"][1]["disposition"], "REVIEW_FOR_CONSOLIDATION")
        result = triage_projects((replace(no_copy, archive_copy_receipt_ref="archive:1"),))
        self.assertEqual(result["records"][0]["disposition"], "INSPECT_MISSING_EVIDENCE")

    def test_deterministic_canonical_order_and_digest(self):
        first, second = project("project:a"), project("project:b", source_digest="b" * 64)
        result = triage_projects((second, first))
        self.assertEqual(result, triage_projects((first, second)))
        self.assertEqual([r["record_ref"] for r in result["records"]], ["item:0001", "item:0002"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_report_does_not_echo_private_ids_or_receipt_values(self):
        sensitive = "PRIVATE-ID-DO-NOT-COPY"
        result = triage_projects((
            project("project:a"),
            project(sensitive, duplicate_of="project:a",
                    duplicate_review_ref="review:PRIVATE-ID-DO-NOT-COPY",
                    archive_copy_receipt_ref="archive:PRIVATE-ID-DO-NOT-COPY"),
        ))
        import json
        encoded = json.dumps(result)
        self.assertNotIn(sensitive, encoded)
        self.assertNotIn("project:a", encoded)
        self.assertNotIn("archive:PRIVATE", encoded)
        self.assertNotIn('"source_digest"', encoded)
        self.assertNotIn('"duplicate_of"', encoded)
        self.assertTrue(all(not r["delete_authorized"] for r in result["records"]))

    def test_project_only_cannot_be_retired_even_with_claimed_receipts(self):
        result = triage_projects((
            project("project:a"),
            project("project:b", memory_scope="PROJECT_ONLY", file_library_enabled=True,
                    duplicate_of="project:a", duplicate_review_ref="review:arbitrary",
                    archive_copy_receipt_ref="archive:arbitrary"),
        ))
        self.assertEqual(result["records"][1]["disposition"], "PRESERVE")

    def test_malformed_sources_and_duplicate_ids_fail_closed(self):
        with self.assertRaises(ProjectTriageError):
            triage_projects((project(), project()))
        with self.assertRaises(ProjectTriageError):
            triage_projects([project()])
        with self.assertRaises(ProjectTriageError):
            triage_projects((project(),) * 513)
        for bad in (dict(source_digest="a"), dict(project_id="x\x00evil"),
                    dict(active_work=1), dict(memory_scope="UNKNOWN_OTHER"),
                    dict(duplicate_of="project:a")):
            with self.subTest(bad=bad), self.assertRaises(ProjectTriageError):
                if "project_id" in bad:
                    project(bad["project_id"])
                else:
                    project(**bad)
        with self.assertRaises(ProjectTriageError):
            project(duplicate_review_ref="review:orphan")
        with self.assertRaises(ProjectTriageError):
            triage_projects(({},))

    def test_duplicate_target_cycles_fail_closed(self):
        left = project("project:a", duplicate_of="project:b", duplicate_review_ref="review:a")
        right = project("project:b", duplicate_of="project:a", duplicate_review_ref="review:b")
        with self.assertRaisesRegex(ProjectTriageError, "cycle"):
            triage_projects((left, right))


if __name__ == "__main__":
    unittest.main()
