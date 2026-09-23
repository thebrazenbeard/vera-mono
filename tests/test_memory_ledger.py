from vera_memory import AdmissionRequest, MemoryClass, MemoryLedger, StaleMemoryHead


def test_memory_ledger_cas_and_supersession(tmp_path):
    ledger = MemoryLedger(tmp_path / "memory.sqlite", project_id="vera-mono", identity_id="vera")
    head0 = ledger.current_head

    first = AdmissionRequest(
        record_id="m1",
        text="first",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id="op1",
        project_id="vera-mono",
        governed_identity_id="vera",
    )
    receipt1 = ledger.admit(first, expected_head=head0)
    assert receipt1["store_head"] != head0
    assert ledger.read("m1").status == "CURRENT"

    second = AdmissionRequest(
        record_id="m2",
        text="corrected",
        memory_class=MemoryClass.WORKING_PROJECT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test", "correction:test"),
        operation_id="op2",
        project_id="vera-mono",
        governed_identity_id="vera",
        supersedes="m1",
    )
    receipt2 = ledger.admit(second, expected_head=receipt1["store_head"])
    assert ledger.read("m1").status == "SUPERSEDED"
    assert ledger.read("m2").status == "CURRENT"
    assert ledger.read("m1").superseded_by == "m2"

    try:
        ledger.admit(second, expected_head=head0)
    except Exception:
        raise AssertionError("idempotent replay should return the original receipt")
    assert ledger.admit(second, expected_head=head0) == receipt2


def test_stale_head_fails_closed(tmp_path):
    ledger = MemoryLedger(tmp_path / "memory.sqlite", project_id="vera-mono", identity_id="vera")
    request = AdmissionRequest(
        record_id="m1",
        text="first",
        memory_class=MemoryClass.HISTORICAL_AUDIT,
        source_actor="test",
        authority_ref="authority:test",
        privacy_ref="privacy:test",
        provenance_refs=("source:test",),
        operation_id="op1",
        project_id="vera-mono",
        governed_identity_id="vera",
    )
    try:
        ledger.admit(request, expected_head="wrong")
    except StaleMemoryHead:
        pass
    else:
        raise AssertionError("stale head was accepted")
