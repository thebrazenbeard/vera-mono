import json

from vera_core.console import VeraConsole


def test_source_only_identity_and_greeting_are_repo_native():
    console = VeraConsole.source_only()
    assert "configured interaction identity" in console.dispatch("who are you?").text
    assert "Vera Mono" in console.dispatch("hey Vera").text


def test_source_only_status_does_not_claim_live_runtime():
    response = VeraConsole.source_only().dispatch(":status")
    assert "SOURCE_ONLY" in response.text
    assert "no live runtime state" in response.text.lower()


def test_bound_status_and_tasks_read_context_without_effects():
    context = {
        "status": "ACCEPTED_CURRENT",
        "accepted_runtime_id": "runtime-1",
        "tasks": {
            "schema": "VERA_TASK_EXECUTION_CONTEXT_V1",
            "open_task_ids": ["task-a"],
        },
    }
    console = VeraConsole.runtime_bound(lambda: context)

    status = console.dispatch("what is your status?")
    assert "ACCEPTED_CURRENT" in status.text
    assert "runtime-1" in status.text

    tasks = console.dispatch(":tasks")
    assert "task-a" in tasks.text
    assert tasks.envelope.authorization_effect == "NONE"


def test_meaning_diagnostic_is_separate_from_nested_input():
    console = VeraConsole.source_only()
    response = console.dispatch(":meaning maybe show me the runtime status")
    payload = json.loads(response.text)
    assert payload["channel"] == "DIAGNOSTIC_INTERPRETATION"
    assert payload["interpretation"]["target"] == "STATUS"
    assert payload["interpretation"]["hedges"] == ["maybe"]


def test_correction_links_previous_interaction():
    console = VeraConsole.source_only()
    first = console.dispatch("show me the status")
    second = console.dispatch("no, I meant show me the tasks")
    assert second.envelope.corrects_interaction_id == first.envelope.interaction_id


def test_unknown_free_form_input_is_preserved_not_hallucinated():
    console = VeraConsole.source_only()
    text = "the blue thing feels different today"
    response = console.dispatch(text)
    assert "UNRESOLVED" in response.text
    assert text in response.text
    assert response.envelope.resolved is False


def test_conflicting_targets_do_not_dispatch():
    response = VeraConsole.source_only().dispatch(":status :tasks")
    assert "AMBIGUOUS" in response.text
    assert response.envelope.resolved is False


def test_exit_sets_explicit_exit_flag():
    response = VeraConsole.source_only().dispatch(":exit")
    assert response.exit_requested is True


def test_capabilities_reads_existing_repo_registry_without_runtime_claim():
    response = VeraConsole.source_only().dispatch(":capabilities")
    payload = json.loads(response.text)
    ids = {item["capability_id"] for item in payload["capabilities"]}
    assert "reasoning" in ids
    assert "memory" in ids
    assert all(
        item["status"] == "SOURCE_DECLARED_NOT_RUNTIME_CONSUMPTION_PROOF"
        for item in payload["capabilities"]
    )


def test_negated_status_request_does_not_dispatch_status():
    response = VeraConsole.source_only().dispatch("do not show me the status")
    assert response.envelope.action_forbidden is True
    assert "NOT DISPATCHED" in response.text
    assert "SOURCE_ONLY" not in response.text


def test_target_mention_in_assertion_does_not_dispatch():
    response = VeraConsole.source_only().dispatch("the string :status is an example")
    assert response.envelope.speech_act.value == "ASSERTION"
    assert response.envelope.dispatch_permitted is False
    assert "NOT DISPATCHED" in response.text
    assert "SOURCE_ONLY" not in response.text


def test_plain_exit_aliases_leave_console():
    console = VeraConsole.source_only()
    for text in ("exit", "/exit", "end", "bye"):
        assert console.dispatch(text).exit_requested is True


def test_vera_invocation_acknowledges_address():
    response = VeraConsole.source_only().dispatch("vera")
    assert response.text == "I'm here."


def test_who_am_i_uses_governed_source_identity_with_authentication_ceiling():
    response = VeraConsole.source_only().dispatch("Who am I?")
    assert "Patrick" in response.text
    assert "governed" in response.text.lower()
    assert "authenticate" in response.text.lower()
