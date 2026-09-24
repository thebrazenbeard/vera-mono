import json
from pathlib import Path

from vera_core.task_execution import (
    CLOSEOUT_STATES,
    CLOSEOUT_SURFACES,
    TASK_DEPENDENCY_STATUSES,
    TaskExecutionLedger,
)


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path):
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_task_architecture_contracts_match_executable_event_and_status_sets():
    manifest = load_json("architecture/VERA_MONO_MANIFEST_V1.json")
    closeout = load_json("architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json")
    delegation = load_json(
        "architecture/VERA_TASK_DELEGATION_OWNERSHIP_V1.json"
    )

    manifest_task = manifest["task_execution_closeout"]
    assert set(manifest_task["event_types"]) == set(
        TaskExecutionLedger.EVENT_TYPES
    )
    assert set(closeout["integrity"]["event_types"]) == set(
        TaskExecutionLedger.EVENT_TYPES
    )
    assert set(closeout["dependencies"]["statuses"]) == set(
        TASK_DEPENDENCY_STATUSES
    )
    assert tuple(closeout["closeout_surfaces"]) == CLOSEOUT_SURFACES
    assert set(closeout["closeout_states"]) == set(CLOSEOUT_STATES)

    delegation_events = {
        "TASK_DELEGATED",
        "TASK_DELEGATION_REASSIGNED",
        "TASK_DELEGATION_RETURNED",
        "TASK_DELEGATION_CANCELLED",
    }
    assert set(delegation["event_types"]) == delegation_events
    assert delegation_events <= set(TaskExecutionLedger.EVENT_TYPES)
    assert manifest_task["closeout_gate"]["active_delegation"] == "DENY"
    assert (
        closeout["qualified_closeout_gate"][
            "active_delegation_forbids_close"
        ]
        is True
    )


def test_delegation_contract_keeps_return_shape_executable_not_descriptive():
    delegation = load_json(
        "architecture/VERA_TASK_DELEGATION_OWNERSHIP_V1.json"
    )
    binding = delegation["binding"]
    assert binding["return_shape_is_enforced_on_return"] is True
    assert binding["return_shape_is_not_documentation_only"] is True
    assert delegation["restart"][
        "stale_owner_reference_after_reassignment"
    ] == "DENY"
    assert delegation["restart"][
        "owner_reference_after_return_or_cancel"
    ] == "DENY"

    required = set(delegation["lifecycle"]["return_requires"])
    assert any("exactly equal" in item for item in required)
    assert any("non-empty" in item for item in required)
