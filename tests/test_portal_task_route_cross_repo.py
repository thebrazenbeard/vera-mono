"""Execute both exact source APIs together when PORTAL_SOURCE_ROOT is supplied."""
import os
from pathlib import Path
import sys

import pytest

from vera_core.task_execution import TaskExecutionLedger, TaskPacket, TaskExecutionError
from vera_core.portal_task_handoff import export_portal_route_request, verify_portal_route_assessment

root=os.environ.get("PORTAL_SOURCE_ROOT")
if root and Path(root).is_dir():
    sys.path.insert(0,root)


def test_cross_repository_durable_task_route_and_restart(tmp_path):
    if not root:
        pytest.skip("Set PORTAL_SOURCE_ROOT to an exact PORTAL checkout for cross-repository contract qualification")
    from portal.route_resolver import PortalRouteAdvertisement
    from portal.vera_task_handoff import assess_vera_task_route

    ledger_file=tmp_path/"vera-tasks.sqlite"
    packet=TaskPacket(
        purpose="Vera selects an advisory portal route without authorizing execution",
        subject="thebrazenbeard/portal@4089d18",
        completion_state="Require separately verified owner-approved execution receipt",
        evidence_requirements=("host currentness",),
        writable_scope=(),
        non_targets=("no writes",),
        forbidden_shortcuts_or_effects=("no effect rights",),
        priority_order=("durability","safety"),
        unknowns=("route may move",),
        return_shape=("proposal","hold reason"),
        relevant_surfaces=("current route","workspace/coordination"),
    )
    ledger=TaskExecutionLedger(ledger_file)
    ledger.open_task("vera-integration-task-001",packet,lifecycle_evidence_digest="f"*64)
    request=export_portal_route_request(
        ledger,"vera-integration-task-001",
        node_id="lappy",target_kind="repository",target_id="thebrazenbeard/portal",
        required_capabilities=("repository_read",),
    )
    route=PortalRouteAdvertisement(
        adapter_id="github",route_id="local-read",
        node_id="lappy",target_kind="repository",target_id="thebrazenbeard/portal",
        capabilities=("repository_read",),
        effect_capabilities=("NO_PROTECTED_EFFECT",),
        authorized_effects=("NO_PROTECTED_EFFECT",),
        available=True,attached=True,current=True,
    )
    proposal=assess_vera_task_route(request,[route])
    assert proposal["state"]=="ROUTE_PROPOSED"
    # Reconstruct in new Python object from real SQLite, no transcript or
    # task packet recreated by hand, and accept the exact advisory only.
    after_restart=TaskExecutionLedger(ledger_file)
    assert verify_portal_route_assessment(after_restart,request,proposal)["route"]["route_id"]=="local-read"
    assert len(after_restart.events("vera-integration-task-001"))==1
    held=assess_vera_task_route(request,[PortalRouteAdvertisement(
        adapter_id="github",route_id="local-read",
        node_id="lappy",target_kind="repository",target_id="thebrazenbeard/portal",
        capabilities=("repository_read",),
        effect_capabilities=("NO_PROTECTED_EFFECT",),
        authorized_effects=("NO_PROTECTED_EFFECT",),
        available=True,attached=True,current=False,
    )])
    assert verify_portal_route_assessment(after_restart,request,held)["state"]=="HELD"
    # A Vera dependency changes the ledger head, invalidating both old replies.
    after_restart.bind_dependency(
        "vera-integration-task-001","dependency-new",
        kind="COORDINATION_COMMAND",target_id="command:new",
    )
    with pytest.raises(TaskExecutionError,match="stale task"):
        verify_portal_route_assessment(TaskExecutionLedger(ledger_file),request,proposal)
