"""Fail-closed operator policy for normal Chat Bus message writes.

This module validates a proposed connector-action plan before mutation. It does
not itself call GitHub, install a runtime router, or prove that a live operator
consulted the policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


class OperatorPolicyViolation(ValueError):
    """A proposed Bus mutation plan exceeds the bounded message-write effect."""


REQUIRED_BUS_WRITE_ACTIONS = (
    "READ_BRANCH_HEAD",
    "READ_HEAD_JSON",
    "CREATE_APPEND_ONLY_MESSAGE",
    "REFRESH_BRANCH_HEAD",
    "REFRESH_HEAD_JSON",
    "CAS_UPDATE_HEAD_JSON",
    "NONFORCE_UPDATE_BRANCH_REF",
    "VERIFY_MESSAGE_READBACK",
    "VERIFY_HEAD_JSON_READBACK",
)

ALLOWED_BUS_WRITE_ACTIONS = frozenset(REQUIRED_BUS_WRITE_ACTIONS)

FORBIDDEN_BUS_WRITE_ACTIONS = frozenset(
    {
        "CREATE_PULL_REQUEST",
        "MERGE_PULL_REQUEST",
        "DELETE_REF",
        "FORCE_UPDATE_REF",
    }
)


@dataclass(frozen=True)
class BusWritePlan:
    """Exact preflight subject for one normal Bus message write."""

    writer_branch: str
    message_path: str
    initial_branch_head: str
    initial_head_blob: str
    refreshed_branch_head: str
    refreshed_head_blob: str
    cas_expected_branch_head: str
    cas_expected_head_blob: str
    force_ref_update: bool
    actions: tuple[str, ...]


def _validate_git_oid(value: str, field: str) -> None:
    if type(value) is not str or len(value) != 40:
        raise OperatorPolicyViolation(f"{field} must be a 40-character Git object id")
    try:
        int(value, 16)
    except ValueError as exc:
        raise OperatorPolicyViolation(
            f"{field} must be a 40-character hexadecimal Git object id"
        ) from exc


def _validate_action_sequence(actions: Sequence[str]) -> None:
    for action in actions:
        if action in FORBIDDEN_BUS_WRITE_ACTIONS:
            raise OperatorPolicyViolation(
                f"{action} is forbidden for BUS_MESSAGE_WRITE intent"
            )
        if action not in ALLOWED_BUS_WRITE_ACTIONS:
            raise OperatorPolicyViolation(
                f"{action} is not an allowed BUS_MESSAGE_WRITE action"
            )

    if tuple(actions) != REQUIRED_BUS_WRITE_ACTIONS:
        raise OperatorPolicyViolation(
            "BUS_MESSAGE_WRITE must use the exact required action sequence"
        )


def validate_bus_write_plan(
    plan: BusWritePlan,
    *,
    expected_writer_branch: str,
) -> BusWritePlan:
    """Validate one normal append-only Bus message mutation plan.

    The caller supplies the currently authoritative writer branch so this
    generic policy does not freeze a topology value that may later move.
    """

    if type(expected_writer_branch) is not str or not expected_writer_branch:
        raise OperatorPolicyViolation("expected writer branch must be non-empty")
    if plan.writer_branch != expected_writer_branch:
        raise OperatorPolicyViolation(
            "writer branch does not match the current authorized Bus route"
        )

    if (
        type(plan.message_path) is not str
        or not plan.message_path.startswith("messages/")
        or plan.message_path == "messages/"
        or "\\" in plan.message_path
        or ".." in plan.message_path.split("/")
    ):
        raise OperatorPolicyViolation(
            "Bus message path must be an append-only messages/ path"
        )

    for field in (
        "initial_branch_head",
        "initial_head_blob",
        "refreshed_branch_head",
        "refreshed_head_blob",
        "cas_expected_branch_head",
        "cas_expected_head_blob",
    ):
        _validate_git_oid(getattr(plan, field), field)

    if type(plan.force_ref_update) is not bool:
        raise OperatorPolicyViolation("force_ref_update must be boolean")
    if plan.force_ref_update:
        raise OperatorPolicyViolation(
            "force ref update is forbidden for normal Bus message writes"
        )

    if plan.cas_expected_branch_head != plan.refreshed_branch_head:
        raise OperatorPolicyViolation(
            "branch CAS expectation must equal the refreshed branch frontier"
        )
    if plan.cas_expected_head_blob != plan.refreshed_head_blob:
        raise OperatorPolicyViolation(
            "HEAD.json CAS expectation must equal the refreshed HEAD.json blob"
        )

    if type(plan.actions) is not tuple:
        raise OperatorPolicyViolation("actions must be an immutable tuple")
    _validate_action_sequence(plan.actions)

    return plan


__all__ = [
    "ALLOWED_BUS_WRITE_ACTIONS",
    "BusWritePlan",
    "FORBIDDEN_BUS_WRITE_ACTIONS",
    "OperatorPolicyViolation",
    "REQUIRED_BUS_WRITE_ACTIONS",
    "validate_bus_write_plan",
]
