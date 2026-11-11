"""Historical evidence result flags cannot be elevated by a caller."""

import unittest

from vera_memory.historical_evidence import (
    HistoricalEvidenceAccessError,
    HistoricalEvidenceError,
    HistoricalEvidenceRecord,
    HistoricalEvidenceResult,
    RESULT_SEMANTICS,
    query_historical_evidence,
)


class HistoricalResultInvariantTests(unittest.TestCase):
    def test_direct_constructor_rejects_out_of_scope_records(self):
        secret = HistoricalEvidenceRecord(
            memory_id="secret:1",
            privacy_scope="SECRET",
            event_time=None,
            recorded_at=None,
            effective_from=None,
            source_ids=("fixture:1",),
            provenance_ceiling="USER_DIRECT",
            currentness_rule="HISTORICAL_ONLY",
        )
        common = {
            "records": (secret,),
            "authorized_privacy_scopes": ("PUBLIC",),
            "retrieved_at": "2026-11-03T00:00:00Z",
        }
        with self.assertRaises(HistoricalEvidenceAccessError):
            HistoricalEvidenceResult(**common)

        allowed = HistoricalEvidenceResult(
            **{**common, "authorized_privacy_scopes": ("SECRET",)}
        )
        self.assertEqual(allowed.records, (secret,))
        filtered = query_historical_evidence(
            (secret,), authorized_privacy_scopes=("PUBLIC",),
            retrieved_at=common["retrieved_at"],
        )
        self.assertEqual(filtered.records, ())

    def test_direct_constructor_rejects_noncanonical_containers_and_scope_values(self):
        common = {
            "records": (),
            "authorized_privacy_scopes": ("PUBLIC",),
            "retrieved_at": "2026-11-03T00:00:00Z",
        }
        for change in (
            {"records": []},
            {"records": (object(),)},
            {"authorized_privacy_scopes": ["PUBLIC"]},
            {"authorized_privacy_scopes": ()},
            {"authorized_privacy_scopes": ("PUBLIC", "PUBLIC")},
            {"authorized_privacy_scopes": ("",)},
            {"authorized_privacy_scopes": (1,)},
            {"retrieved_at": ""},
        ):
            with self.subTest(change=change):
                with self.assertRaises((HistoricalEvidenceAccessError, TypeError, ValueError)):
                    HistoricalEvidenceResult(**{**common, **change})

    def test_direct_constructor_rejects_forged_effects(self):
        common = {
            "records": (),
            "authorized_privacy_scopes": ("PROJECT",),
            "retrieved_at": "2026-11-03T00:00:00Z",
        }
        for field, forbidden in (
            ("current_memory_effect", "WRITE_CURRENT"),
            ("authorization_effect", "GRANTED"),
            ("result_semantics", "CURRENT_MEMORY_AUTHORITY"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(HistoricalEvidenceError):
                    HistoricalEvidenceResult(**common, **{field: forbidden})

    def test_query_remains_effect_free(self):
        result = query_historical_evidence(
            (), authorized_privacy_scopes=("PROJECT",),
            retrieved_at="2026-11-03T00:00:00Z",
        )
        self.assertEqual(result.result_semantics, RESULT_SEMANTICS)
        self.assertEqual(result.current_memory_effect, "NONE")
        self.assertEqual(result.authorization_effect, "NONE")


if __name__ == "__main__":
    unittest.main()
