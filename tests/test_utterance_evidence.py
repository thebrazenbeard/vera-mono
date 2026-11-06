"""Small honest semantic-bounds test suite; no model/runtime loading."""

import pytest

from vera_core.utterance_evidence import observe_utterance


def test_unrelated_tasks_cannot_share_the_same_utterance_event():
    pump = observe_utterance("diagnose a broken pump")
    poem = observe_utterance("write a poem about moonlight")
    assert (pump.parser_speech_act, poem.parser_speech_act) == ("ASSERTION", "ASSERTION")
    assert pump.observed_speech_act == poem.observed_speech_act == "REQUEST"
    assert (pump.action_lexeme, pump.literal_task_object) == ("diagnose", "a broken pump")
    assert (poem.action_lexeme, poem.literal_task_object) == ("write", "a poem about moonlight")
    assert pump.utterance_sha256 != poem.utterance_sha256
    for evidence in (pump, poem):
        assert evidence.noema_discrepancy is None
        assert evidence.humility_priors is None
        assert evidence.affect_valence is None
        assert evidence.volition_intent is None
        assert evidence.authorization_effect == "NONE"
        assert evidence.memory_admission == "NONE"
        donor = evidence.as_five_donor_input()
        assert donor["existing_five_donor_invocation_permitted"] is False
        assert donor["noema"]["discrepancy"] is None
        assert donor["empathy"]["response_policy"] is None


def test_same_referent_stop_play_and_different_referent():
    prior = observe_utterance("diagnose a broken pump")
    stopped = observe_utterance(
        "STOP_PLAY: diagnose a broken pump",
        prior_interaction_id=prior.utterance_sha256,
        prior_task_object=prior.literal_task_object,
    )
    changed = observe_utterance(
        "STOP_PLAY: write a poem about moonlight",
        prior_interaction_id=prior.utterance_sha256,
        prior_task_object=prior.literal_task_object,
    )
    assert stopped.observed_speech_act == "STOP_PLAY"
    assert stopped.stop_play == "EXPLICIT"
    # A caller-provided literal and ID are not custody/currentness proof.
    assert not stopped.same_referent_stop
    assert stopped.ambiguity == "PRIOR_CURRENTNESS_UNVERIFIED"
    assert changed.stop_play == "EXPLICIT"
    assert not changed.same_referent_stop
    assert stopped.authorization_effect == changed.authorization_effect == "NONE"


@pytest.mark.parametrize("text", [
    "Do not search for Inner Council",
    "I asked you not to search for Inner Council",
    "Please do not ever browse for my private history",
    "Ｄｏ　ｎｏｔ　ｓｅａｒｃｈ for Inner Council",
])
def test_explicit_prohibition_produces_a_veto_not_a_lookup(text):
    e = observe_utterance(text)
    assert e.lookup_prohibition == "EXPLICIT"
    assert e.private_lookup_permission == "NONE"
    assert e.authorization_effect == "NONE"


def test_quoted_negation_is_not_an_executable_prohibition_or_retrieval():
    e = observe_utterance('She wrote, “do not search Inner Council”.')
    assert e.lookup_prohibition == "UNKNOWN"
    assert e.private_lookup_permission == "NONE"
    assert e.action_lexeme is None


@pytest.mark.parametrize("text", [
    "explain 'do not search' as a phrase",
    "explain ‘do not search’ as a phrase",
    "explain `do not search` as a phrase",
    "explain the phrase 'don't search' without doing it",
])
def test_single_quoted_or_code_negation_is_not_a_prohibition(text):
    e = observe_utterance(text)
    assert e.lookup_prohibition == "UNKNOWN"
    assert e.private_lookup_permission == "NONE"


def test_apostrophe_contraction_still_vetoes_lookup():
    e = observe_utterance("Don't search my files")
    assert e.lookup_prohibition == "EXPLICIT"


def test_no_prior_custody_from_arbitrary_caller_values():
    e = observe_utterance(
        "STOP_PLAY: diagnose a broken pump",
        prior_task_object="a broken pump",
    )
    assert e.stop_play == "EXPLICIT"
    assert e.same_referent_stop is False
    assert e.ambiguity == "PRIOR_CURRENTNESS_UNVERIFIED"


def test_double_negative_is_ambiguous_and_never_becomes_permission():
    e = observe_utterance("Do not not search the private file")
    assert e.ambiguity == "AMBIGUOUS_NEGATION"
    assert e.lookup_prohibition == "UNKNOWN"
    assert e.private_lookup_permission == "NONE"


def test_unbalanced_quote_fails_closed():
    e = observe_utterance('write a poem about “moonlight')
    assert e.ambiguity == "UNBALANCED_QUOTE"
    assert e.action_lexeme is None
    assert e.authorization_effect == "NONE"


def test_correction_requires_authenticated_antecedent_to_resolve():
    e = observe_utterance("No, I meant the pump")
    assert e.observed_speech_act == "CORRECTION"
    assert e.ambiguity == "CORRECTION_WITHOUT_ANTECEDENT"
    assert e.correction_of is None
    assert e.literal_task_object is None


def test_arbitrary_correction_id_does_not_become_verified_history():
    e = observe_utterance("No, I meant the pump", prior_interaction_id="f" * 64)
    assert e.observed_speech_act == "CORRECTION"
    assert e.correction_of is None
    assert e.ambiguity == "ANTECEDENT_ID_UNVERIFIED"
    assert e.as_five_donor_input()["claimed_correction_of"] is None


@pytest.mark.parametrize("text", ["write\u200ba poem", "write\ud800a poem", "\x00write a poem"])
def test_hidden_unicode_and_control_characters_rejected(text):
    with pytest.raises(ValueError):
        observe_utterance(text)


def test_unknown_utterance_does_not_cause_inferred_task():
    e = observe_utterance("The pump is acting strangely; is it magic?")
    assert e.observed_speech_act == "QUESTION"
    assert e.action_lexeme is None
    assert e.literal_task_object is None
    assert e.noema_discrepancy is None
