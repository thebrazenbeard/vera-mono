from vera_core.console import VeraConsole
from vera_core.provenance_preflight import (
    ProvenancePreflight,
    ProvenancePreflightStatus,
)


def test_relational_question_triggers_bound_roots_lookup_before_answer():
    called = []

    def lookup(raw):
        called.append(raw)
        return ProvenancePreflight(
            status=ProvenancePreflightStatus.SEARCHED,
            candidate_refs=("roots:conversation:123",),
            source_head="head-verified-by-provider",
        )

    console = VeraConsole.source_only(provenance_preflight=lookup)
    response = console.dispatch("Who am I to you?")
    assert called == ["Who am I to you?"]
    assert "Patrick" in response.text
    assert console.last_provenance_preflight is not None
    assert console.last_provenance_preflight.candidate_refs == (
        "roots:conversation:123",
    )
    assert response.envelope.authorization_effect == "NONE"


def test_roots_lookup_unavailable_blocks_regular_answer():
    def lookup(_raw):
        return ProvenancePreflight(status=ProvenancePreflightStatus.UNAVAILABLE)

    console = VeraConsole.source_only(provenance_preflight=lookup)
    response = console.dispatch("Who am I to you?")
    assert "PROVENANCE_UNAVAILABLE" in response.text
    assert "Patrick" not in response.text
    assert console.last_provenance_preflight is not None


def test_roots_lookup_ambiguous_blocks_regular_answer():
    console = VeraConsole.source_only(
        provenance_preflight=lambda _raw: ProvenancePreflight(
            status=ProvenancePreflightStatus.AMBIGUOUS,
        )
    )
    response = console.dispatch("Who am I to you?")
    assert "PROVENANCE_AMBIGUOUS" in response.text
    assert "Patrick" not in response.text


def test_roots_lookup_exception_fails_closed_without_leaking_exception():
    def unavailable(_raw):
        raise RuntimeError("secret provider text")

    console = VeraConsole.source_only(provenance_preflight=unavailable)
    response = console.dispatch("Who am I to you?")
    assert "PROVENANCE_LOOKUP_UNAVAILABLE" in response.text
    assert "secret provider text" not in response.text
    assert "Patrick" not in response.text


def test_roots_lookup_wrong_return_type_fails_closed():
    console = VeraConsole.source_only(provenance_preflight=lambda _raw: {})
    response = console.dispatch("Who am I to you?")
    assert "PROVENANCE_LOOKUP_UNAVAILABLE" in response.text


def test_exact_controls_and_diagnostic_operand_are_not_roots_searches():
    calls = []
    console = VeraConsole.source_only(
        provenance_preflight=lambda raw: (
            calls.append(raw)
            or ProvenancePreflight(status=ProvenancePreflightStatus.NOT_REQUIRED)
        )
    )
    assert "SOURCE_ONLY" in console.dispatch(":status").text
    assert console.dispatch(":meaning Who am I to you?").channel == (
        "DIAGNOSTIC_INTERPRETATION"
    )
    assert console.dispatch(":exit").exit_requested is True
    assert calls == []


def test_assertions_and_negated_requests_do_not_invoke_provenance():
    calls = []
    console = VeraConsole.source_only(
        provenance_preflight=lambda raw: (
            calls.append(raw)
            or ProvenancePreflight(status=ProvenancePreflightStatus.NOT_REQUIRED)
        )
    )
    console.dispatch("the string :status is an example")
    console.dispatch("do not show me your status")
    assert calls == []


def test_lookup_receipt_does_not_survive_next_unrelated_dispatch():
    console = VeraConsole.source_only(
        provenance_preflight=lambda _raw: ProvenancePreflight(
            status=ProvenancePreflightStatus.SEARCHED,
        )
    )
    console.dispatch("Who am I to you?")
    assert console.last_provenance_preflight is not None
    console.dispatch(":status")
    assert console.last_provenance_preflight is None


def test_provenance_receipts_reject_authority_like_untyped_data():
    try:
        ProvenancePreflight(
            status=ProvenancePreflightStatus.SEARCHED,
            candidate_refs=("valid", ""),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("empty provenance source reference was admitted")
    try:
        ProvenancePreflight(
            status=ProvenancePreflightStatus.NOT_REQUIRED,
            candidate_refs=("fake-evidence",),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("non-search decision claimed retrieved evidence")
