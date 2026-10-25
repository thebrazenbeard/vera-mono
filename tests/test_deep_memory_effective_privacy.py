"""Public-adapter regression tests for Deep Memory overlay privacy custody.

These tests use only an injected in-memory read-only provider. They do not
install or execute a DeepMemoryStorage checkout.
"""

import unittest
from copy import deepcopy

from runtime_cohesion.deep_memory_evidence import (
    DeepMemoryEvidenceAdapter,
    EvidenceAuthorizationError,
    EvidenceContractError,
    EvidenceSearchRequest,
)


def _overlay(**changes):
    return {
        "recorded_at": "2026-01-02T00:00:00Z",
        "recorded_at_status": "SOURCE_RECORDED",
        "effective_from": None,
        "effective_from_status": "UNKNOWN_NOT_RECORDED_IN_SOURCE_ROW",
        "chronology_semantics": "EVENT_TIME_RECORD_TIME_EFFECTIVE_TIME_RETRIEVAL_TIME_SEPARATE",
        **changes,
    }


def _provider_result(field_name, overlay, scopes):
    row = {
        "memory_id": "historical-a",
        "memory_class": "EVENT",
        "stored_historical_canonicity": "UNRESOLVED_HISTORY",
        "historical_canonicity": "UNRESOLVED_HISTORY",
        "event_time": "2026-01-01T00:00:00Z",
        "recorded_at": "2026-01-02T00:00:00Z",
        "recorded_at_status": "SOURCE_RECORDED",
        "chronology_semantics": "EVENT_TIME_RECORD_TIME_EFFECTIVE_TIME_RETRIEVAL_TIME_SEPARATE",
        "provenance_ceiling": "HISTORICAL_ONLY",
        "privacy_scope": "PROJECT",
        "currentness_rule": "HISTORICAL_ONLY",
        "governed_memory_admission": "NOT_ADMITTED",
        "source_ids": ["tranche:1"],
        "ledger_path": "ledger/memories_001.jsonl",
        "overlay_privacy_semantics": "OVERLAY_INHERITS_TARGET_PRIVACY_UNLESS_EXPLICIT_SCOPE_REQUIRES_SEPARATE_AUTHORIZATION",
        "result_semantics": "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY",
        field_name: [overlay],
    }
    return {
        "schema": "VERA_DEEP_MEMORY_EVIDENCE_RESULT_V1",
        "query": "history",
        "privacy_mode": "AUTHORIZED_SCOPE_FILTER",
        "retrieved_at": "2026-10-25T00:00:00Z",
        "authorized_privacy_scopes": list(scopes),
        "count": 1,
        "results": [row],
    }


def _search(field_name, overlay, scopes=("PROJECT",)):
    result = _provider_result(field_name, overlay, scopes)
    adapter = DeepMemoryEvidenceAdapter(lambda **_: deepcopy(result))
    return adapter.search(EvidenceSearchRequest("history", scopes))


class DeepMemoryEffectiveOverlayPrivacyTests(unittest.TestCase):
    def test_foreign_effective_scope_cannot_hide_behind_missing_explicit_scope(self):
        for field in (
            "amendments",
            "historical_canon_overlays",
            "classification_corrections",
        ):
            with (
                self.subTest(field=field),
                self.assertRaises(EvidenceAuthorizationError),
            ):
                _search(field, _overlay(effective_privacy_scope="PRIVATE"))

    def test_explicit_and_effective_scope_conflict_even_when_both_authorized(self):
        for field in (
            "amendments",
            "historical_canon_overlays",
            "classification_corrections",
        ):
            with self.subTest(field=field), self.assertRaises(EvidenceContractError):
                _search(
                    field,
                    _overlay(
                        privacy_scope="PROJECT", effective_privacy_scope="PRIVATE"
                    ),
                    ("PROJECT", "PRIVATE"),
                )

    def test_malformed_effective_scope_produces_controlled_denial(self):
        for value in ([], {}, 42, False):
            with (
                self.subTest(value=value),
                self.assertRaises(EvidenceAuthorizationError),
            ):
                _search("amendments", _overlay(effective_privacy_scope=value))

    def test_allowed_inherited_and_consistent_scope_stay_read_only(self):
        for overlay in (
            _overlay(),
            _overlay(privacy_scope="PROJECT", effective_privacy_scope="PROJECT"),
        ):
            with self.subTest(overlay=overlay):
                batch = _search("amendments", overlay)
                self.assertEqual(batch.count, 1)
                self.assertFalse(batch.canonical_memory_transfer)
                self.assertFalse(batch.execution_authorized)


if __name__ == "__main__":
    unittest.main()
