from vera_assurance import DriftPolicy, Snapshot, compare_snapshots


def test_critical_identity_drift_blocks():
    baseline = Snapshot("vera", {"identity": "v1", "tone": "direct", "session": "old"})
    candidate = Snapshot("vera", {"identity": "v2", "tone": "direct", "session": "new"})
    report = compare_snapshots(
        baseline,
        candidate,
        DriftPolicy(
            critical_fields=("identity",),
            mutable_fields=("session",),
            required_fields=("identity", "tone"),
        ),
    )
    assert report.status == "BLOCK"
    assert report.independent_review is False
    assert [finding.code for finding in report.findings] == ["CRITICAL_DRIFT"]


def test_mutable_only_change_passes():
    baseline = Snapshot("vera", {"identity": "v1", "session": "a"})
    candidate = Snapshot("vera", {"identity": "v1", "session": "b"})
    report = compare_snapshots(
        baseline,
        candidate,
        DriftPolicy(critical_fields=("identity",), mutable_fields=("session",)),
    )
    assert report.status == "PASS"
