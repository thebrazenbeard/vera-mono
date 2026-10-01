from vera_core.interaction_semantics import (
    InteractionTarget,
    SpeechAct,
    TransferFidelity,
    interpret_utterance,
)


def test_exact_colon_status_is_exact_and_non_authorizing():
    env = interpret_utterance(":status")
    assert env.target is InteractionTarget.STATUS
    assert env.speech_act is SpeechAct.REQUEST
    assert env.fidelity is TransferFidelity.EXACT
    assert env.authorization_effect == "NONE"
    assert env.raw_text == ":status"


def test_natural_status_question_is_constructive():
    env = interpret_utterance("what is your status?")
    assert env.target is InteractionTarget.STATUS
    assert env.speech_act is SpeechAct.QUESTION
    assert env.fidelity is TransferFidelity.CONSTRUCTIVE
    assert env.evidence_cues


def test_correction_binds_previous_interaction_without_promoting_truth():
    env = interpret_utterance(
        "no, I meant show me the tasks",
        previous_interaction_id="turn-7",
    )
    assert env.speech_act is SpeechAct.CORRECTION
    assert env.target is InteractionTarget.TASKS
    assert env.corrects_interaction_id == "turn-7"
    assert env.truth_effect == "NONE"
    assert env.authorization_effect == "NONE"


def test_hedge_is_local_modifier_not_global_request_erasure():
    env = interpret_utterance("maybe show me the runtime status")
    assert env.target is InteractionTarget.STATUS
    assert env.speech_act is SpeechAct.REQUEST
    assert "maybe" in env.hedges
    assert env.action_requested is True


def test_conflicting_control_targets_remain_unresolved():
    env = interpret_utterance(":status :tasks")
    assert env.target is InteractionTarget.AMBIGUOUS
    assert env.fidelity is TransferFidelity.UNREPRESENTABLE
    assert env.resolved is False
    assert {item.target for item in env.candidates} == {
        InteractionTarget.STATUS,
        InteractionTarget.TASKS,
    }


def test_unknown_statement_preserves_raw_text_without_guessing_target():
    text = "the blue thing feels different today"
    env = interpret_utterance(text)
    assert env.raw_text == text
    assert env.speech_act is SpeechAct.ASSERTION
    assert env.target is InteractionTarget.UNKNOWN
    assert env.fidelity is TransferFidelity.LOSSY
    assert env.resolved is False


def test_identity_and_meaning_targets_are_recognized():
    assert interpret_utterance("who are you?").target is InteractionTarget.IDENTITY
    assert interpret_utterance(":meaning maybe show status").target is InteractionTarget.MEANING


def test_negative_request_preserves_target_but_denies_dispatch():
    env = interpret_utterance("do not show me the status")
    assert env.target is InteractionTarget.STATUS
    assert env.action_forbidden is True
    assert env.action_requested is False
    assert "do not" in env.negation_cues


def test_embedded_colon_command_is_not_exact_control_syntax():
    env = interpret_utterance("the string :status is an example")
    assert env.fidelity is not TransferFidelity.EXACT
