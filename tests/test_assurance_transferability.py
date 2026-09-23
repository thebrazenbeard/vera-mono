from vera_assurance.resources import load_json_resource


def test_driftguard_transferability_is_local_reference_data():
    payload = load_json_resource("architecture/VERA_DRIFTGUARD_TRANSFERABILITY_V1.json")
    assert payload["schema"] == "VERA_DRIFTGUARD_TRANSFERABILITY_V1"
    assert "DRIFT_ALARM != IDENTITY_LOSS" in payload["hard_non_equivalences"]
    dispositions = {row["mechanism"]: row["disposition"] for row in payload["dispositions"]}
    assert dispositions["evidence_class_separation"] == "REUSE"
    assert dispositions["holdout_digest_as_nonaccess_proof"] == "REJECT"
