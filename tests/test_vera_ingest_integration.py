from ingest import IngestStatus, TextSource
from vera_core import VeraStateDirectory


def test_vera_state_directory_owns_provider_neutral_intake(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "state",
        project_id="vera-mono",
        identity_id="vera",
    )
    assert state.paths.intake == (tmp_path / "state" / "intake").resolve()

    result = state.ingestor().ingest(
        TextSource("evidence\r\n", locator="urn:vera:test")
    )
    assert result.status is IngestStatus.ACCEPTED
    assert state.intake_store().get_record(result.ingest_id)["status"] == "ACCEPTED"

    duplicate = state.ingestor().ingest(
        TextSource("evidence\r\n", locator="urn:vera:test")
    )
    assert duplicate.status is IngestStatus.DUPLICATE

    context = state.resume_context()["intake"]
    assert context["record_count"] == 1
    assert "NOT_TRUTH_CURRENTNESS_AUTHORITY_OR_MEMORY_ADMISSION" in context["result_semantics"]
