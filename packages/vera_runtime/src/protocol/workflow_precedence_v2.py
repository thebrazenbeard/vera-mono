"""Executable projection of Vera Protocol V2 work-precedence semantics.

This module decides only the next bounded workflow action. It does not perform
repository effects, grant authority, install Project controls, or prove runtime
consumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProtocolV2Action(str, Enum):
    OBSERVE = "OBSERVE"
    CREATE_INCLUDED_SETUP = "CREATE_INCLUDED_SETUP"
    ACT_VERIFY_REPORT = "ACT_VERIFY_REPORT"
    DIRECT_GITHUB_HANDOFF = "DIRECT_GITHUB_HANDOFF"
    REFRESH_EXACT_STATE = "REFRESH_EXACT_STATE"
    COMPLETE = "COMPLETE"
    STOP_AMBIGUITY = "STOP_AMBIGUITY"
    STOP_CONFLICTING_INSTRUCTIONS = "STOP_CONFLICTING_INSTRUCTIONS"
    STOP_COMPETING_WRITER = "STOP_COMPETING_WRITER"
    STOP_REPOSITORY_STEWARD = "STOP_REPOSITORY_STEWARD"
    STOP_PROTECTED_AUTHORITY = "STOP_PROTECTED_AUTHORITY"
    STOP_INTEGRITY_OR_CAPABILITY = "STOP_INTEGRITY_OR_CAPABILITY"
    STOP_AMBIGUOUS_NON_IDEMPOTENT_EFFECT = "STOP_AMBIGUOUS_NON_IDEMPOTENT_EFFECT"
    STOP_FAILED_VERIFICATION = "STOP_FAILED_VERIFICATION"
    STOP_SAFETY = "STOP_SAFETY"
    STOP_EXPLICIT_WAIT = "STOP_EXPLICIT_WAIT"
    STOP_NO_CURRENT_AUTHORITY = "STOP_NO_CURRENT_AUTHORITY"


@dataclass(frozen=True)
class ProtocolV2Context:
    effect_class: int
    current_instruction: bool = True
    necessary_setup_missing: bool = False
    isolated_owner_surface: bool = False
    competing_writer: bool = False
    repository_steward_allows: bool = True
    protected_authority: bool = False
    material_ambiguity: bool = False
    conflicting_current_instructions: bool = False
    deterministic_integrity_or_capability_failure: bool = False
    ambiguous_non_idempotent_effect: bool = False
    verification_failed: bool = False
    safety_boundary: bool = False
    explicit_wait_required: bool = False
    handoff_required: bool = False
    github_route_available: bool = False
    exact_state_required_for_next_claim: bool = False
    exact_state_current: bool = True
    correction_requires_still_current_act: bool = False
    acceptance_criteria_passed: bool = False
    unresolved_high_medium_defects: int = 0
    older_generic_rule_conflicts: bool = False

    def __post_init__(self) -> None:
        if self.effect_class not in (0, 1, 2, 3):
            raise ValueError("effect_class must be 0, 1, 2, or 3")
        if type(self.unresolved_high_medium_defects) is not int:
            raise ValueError("unresolved_high_medium_defects must be an integer")
        if self.unresolved_high_medium_defects < 0:
            raise ValueError("unresolved_high_medium_defects cannot be negative")
        for name, value in self.__dict__.items():
            if name in {"effect_class", "unresolved_high_medium_defects"}:
                continue
            if type(value) is not bool:
                raise ValueError(f"{name} must be boolean")


@dataclass(frozen=True)
class ProtocolV2Decision:
    action: ProtocolV2Action
    may_act: bool
    reason: str
    stale_generic_rule_controls: bool = False
    authority_expanded: bool = False


def decide_protocol_v2(context: ProtocolV2Context) -> ProtocolV2Decision:
    """Return the next action under the existing Protocol V2 contract."""

    if type(context) is not ProtocolV2Context:
        raise TypeError("context must be an exact ProtocolV2Context")

    if context.safety_boundary:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_SAFETY, False, "safety or policy boundary controls"
        )
    if context.material_ambiguity:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_AMBIGUITY, False, "material target/outcome ambiguity"
        )
    if context.conflicting_current_instructions:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_CONFLICTING_INSTRUCTIONS,
            False,
            "current instructions conflict and precedence is unresolved",
        )
    if not context.repository_steward_allows:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_REPOSITORY_STEWARD,
            False,
            "current repository-local steward boundary excludes mutation",
        )
    if context.deterministic_integrity_or_capability_failure:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_INTEGRITY_OR_CAPABILITY,
            False,
            "deterministic integrity/auth/tool/schema/capability failure",
        )
    if context.ambiguous_non_idempotent_effect:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_AMBIGUOUS_NON_IDEMPOTENT_EFFECT,
            False,
            "ambiguous non-idempotent effect requires inspection",
        )
    if context.verification_failed:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_FAILED_VERIFICATION,
            False,
            "failed verification prevents safe continuation",
        )
    if context.explicit_wait_required:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_EXPLICIT_WAIT,
            False,
            "current instruction explicitly requires approval before the next step",
        )

    if context.effect_class == 3 and not context.protected_authority:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_PROTECTED_AUTHORITY,
            False,
            "Class 3 effect lacks exact protected-effect authority",
        )

    if context.effect_class == 2 and context.competing_writer:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_COMPETING_WRITER,
            False,
            "shared target has a competing current writer",
        )

    if not context.current_instruction:
        return ProtocolV2Decision(
            ProtocolV2Action.STOP_NO_CURRENT_AUTHORITY,
            False,
            "no current instruction authorizes the bounded act",
        )

    if context.handoff_required and context.github_route_available:
        return ProtocolV2Decision(
            ProtocolV2Action.DIRECT_GITHUB_HANDOFF,
            True,
            "GitHub can carry the work-bearing handoff directly",
        )

    if context.exact_state_required_for_next_claim and not context.exact_state_current:
        return ProtocolV2Decision(
            ProtocolV2Action.REFRESH_EXACT_STATE,
            True,
            "the next material claim depends on fresh exact state",
        )

    if (
        context.acceptance_criteria_passed
        and context.unresolved_high_medium_defects == 0
    ):
        return ProtocolV2Decision(
            ProtocolV2Action.COMPLETE,
            False,
            "stated acceptance criteria pass with no unresolved HIGH/MEDIUM defects",
        )

    # A fresher specific instruction controls its bounded scope. An older
    # generic restriction is evidence/history, not a veto over this act.
    if context.effect_class == 0:
        return ProtocolV2Decision(
            ProtocolV2Action.OBSERVE,
            True,
            "Class 0 observation is authorized",
            stale_generic_rule_controls=False,
        )

    if (
        context.effect_class == 1
        and context.necessary_setup_missing
        and context.isolated_owner_surface
    ):
        return ProtocolV2Decision(
            ProtocolV2Action.CREATE_INCLUDED_SETUP,
            True,
            "missing reversible actor-owned setup is included in the current assignment",
            stale_generic_rule_controls=False,
        )

    if context.correction_requires_still_current_act:
        return ProtocolV2Decision(
            ProtocolV2Action.ACT_VERIFY_REPORT,
            True,
            "present correction requires the still-current executable act before explanation",
            stale_generic_rule_controls=False,
        )

    return ProtocolV2Decision(
        ProtocolV2Action.ACT_VERIFY_REPORT,
        True,
        "current instruction authorizes the bounded act; verify and report",
        stale_generic_rule_controls=False,
    )


__all__ = [
    "ProtocolV2Action",
    "ProtocolV2Context",
    "ProtocolV2Decision",
    "decide_protocol_v2",
]
