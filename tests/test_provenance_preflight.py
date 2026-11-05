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
    assert "PROVENANCE_SEARCHED" in response.text
    assert "Patrick" not in response.text
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


def test_assertions_reach_pure_detector_but_negated_commands_do_not_search():
    calls = []
    console = VeraConsole.source_only(
        provenance_preflight=lambda raw: (
            calls.append(raw)
            or ProvenancePreflight(status=ProvenancePreflightStatus.NOT_REQUIRED)
        )
    )
    console.dispatch("the string :status is an example")
    console.dispatch("do not show me your status")
    assert calls == ["the string :status is an example"]


def test_lookup_receipt_does_not_survive_next_unrelated_dispatch():
    console = VeraConsole.source_only(
        provenance_preflight=lambda _raw: ProvenancePreflight(
            status=ProvenancePreflightStatus.SEARCHED,
            candidate_refs=("roots:test",),
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



def test_roots_trigger_adapter_searches_only_matched_query_and_scope():
    from types import SimpleNamespace
    from vera_core.provenance_preflight import RootsSearchResult, build_roots_preflight

    calls = []

    def detect(raw):
        calls.append(("detect", raw))
        return SimpleNamespace(
            status="LOOKUP_REQUESTED",
            hits=(
                SimpleNamespace(
                    concept_id="relational_pragmatics",
                    query="origin of our relational naming",
                    scope_key="private-consented-history",
                ),
            ),
        )

    def search(query, scope_key):
        calls.append(("search", query, scope_key))
        return RootsSearchResult(candidate_refs=("roots:record:2",), source_head="head")

    console = VeraConsole.source_only(
        provenance_preflight=build_roots_preflight(
            resolve_trigger=detect,
            search_candidates=search,
        )
    )
    answer = console.dispatch("Who am I to you?")
    assert "PROVENANCE_SEARCHED" in answer.text
    assert "Patrick" not in answer.text
    assert calls == [
        ("detect", "Who am I to you?"),
        ("search", "origin of our relational naming", "private-consented-history"),
    ]
    assert console.last_provenance_preflight.candidate_refs == ("roots:record:2",)


def test_roots_no_trigger_does_not_silence_ordinary_questions():
    from types import SimpleNamespace
    from vera_core.provenance_preflight import build_roots_preflight

    def forbidden_search(_query, _scope):
        raise AssertionError("no-trigger text must not cause Roots corpus search")

    preflight = build_roots_preflight(
        resolve_trigger=lambda _raw: SimpleNamespace(status="NO_TRIGGER", hits=()),
        search_candidates=forbidden_search,
    )
    console = VeraConsole.source_only(provenance_preflight=preflight)
    response = console.dispatch("what is your status?")
    assert "SOURCE_ONLY" in response.text
    assert console.last_provenance_preflight.status is (
        ProvenancePreflightStatus.NOT_REQUIRED
    )


def test_roots_ambiguous_trigger_blocks_without_archive_search():
    from types import SimpleNamespace
    from vera_core.provenance_preflight import build_roots_preflight

    def forbidden_search(_query, _scope):
        raise AssertionError("ambiguous provenance must not initiate corpus search")

    preflight = build_roots_preflight(
        resolve_trigger=lambda _raw: SimpleNamespace(status="AMBIGUOUS", hits=()),
        search_candidates=forbidden_search,
    )
    response = VeraConsole.source_only(
        provenance_preflight=preflight
    ).dispatch("Who am I to you?")
    assert "PROVENANCE_AMBIGUOUS" in response.text


def test_roots_search_must_return_typed_evidence_metadata():
    from types import SimpleNamespace
    from vera_core.provenance_preflight import build_roots_preflight

    hit = SimpleNamespace(query="relationship provenance", scope_key="private")
    preflight = build_roots_preflight(
        resolve_trigger=lambda _raw: SimpleNamespace(
            status="LOOKUP_REQUESTED", hits=(hit,)
        ),
        search_candidates=lambda _query, _scope: {"source": "claimed"},
    )
    response = VeraConsole.source_only(
        provenance_preflight=preflight
    ).dispatch("Who am I to you?")
    assert "PROVENANCE_UNAVAILABLE" in response.text


def test_unknown_high_value_question_still_reaches_roots_preflight():
    calls = []

    def unavailable(raw):
        calls.append(raw)
        return ProvenancePreflight(status=ProvenancePreflightStatus.UNAVAILABLE)

    console = VeraConsole.source_only(provenance_preflight=unavailable)
    response = console.dispatch("What does the silver staircase mean to us?")
    assert calls == ["What does the silver staircase mean to us?"]
    assert "PROVENANCE_UNAVAILABLE" in response.text


def test_quoted_subject_assertion_and_unknown_negation_do_not_search():
    calls = []
    console = VeraConsole.source_only(
        provenance_preflight=lambda raw: (
            calls.append(raw)
            or ProvenancePreflight(status=ProvenancePreflightStatus.NOT_REQUIRED)
        )
    )
    console.dispatch("The phrase 'who am I to you' is a quote.")
    console.dispatch("Do not explain the silver staircase.")
    assert calls == []
