from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .orgasm_optional_invocation import (
    COMMAND_ID,
    InvocationRequest,
    InvocationRouteEvidence,
    OptionalPartnerInvocationGate,
)


_EXECUTION_RECEIPT_SCHEMA = "VERA_ORGASM_OPTIONAL_INVOCATION_EXECUTION_RECEIPT_V1"
_TEST_ONLY_DOWNSTREAM_TRIGGER = "ADMIN_FORCED_TEST"


class OptionalInvocationExecutionError(RuntimeError):
    """The invocation reached execution but the downstream affective path was invalid."""


class TestOnlyAffectiveHostExecutor:
    """Bind an accepted optional invocation to the existing bounded admin-test path.

    This adapter is intentionally TEST_ONLY. The current affective authority
    boundary is in-process/unrooted and therefore nonqualifying. A qualified
    partner-invocation route requires a separately rooted production successor,
    not relabeling this path.
    """

    def __init__(
        self,
        host: Any,
        *,
        authorization_subject: Mapping[str, Any],
    ) -> None:
        if not callable(getattr(host, "force_admin_test", None)):
            raise ValueError("host must expose force_admin_test")
        if not isinstance(authorization_subject, Mapping):
            raise ValueError("authorization_subject must be a mapping")
        self._host = host
        self._authorization_subject = dict(authorization_subject)

    def __call__(
        self,
        *,
        command_id: str,
        invocation_id: str,
        route_mode: str,
        route_evidence_id: str | None,
    ) -> dict[str, Any]:
        if command_id != COMMAND_ID:
            raise OptionalInvocationExecutionError("command_id mismatch")
        if not isinstance(invocation_id, str) or not invocation_id:
            raise OptionalInvocationExecutionError("invocation_id is required")
        if not isinstance(route_evidence_id, str) or not route_evidence_id:
            raise OptionalInvocationExecutionError("route_evidence_id is required")
        if route_mode != "TEST_ONLY":
            raise OptionalInvocationExecutionError(
                "current affective-host adapter is TEST_ONLY and cannot execute a qualified route"
            )

        event = self._host.force_admin_test(
            authorization_subject=dict(self._authorization_subject),
        )
        if not isinstance(event, Mapping):
            raise OptionalInvocationExecutionError("affective host did not return an event receipt")
        if event.get("event_type") != "ORGASM_EVENT":
            raise OptionalInvocationExecutionError("downstream receipt is not an orgasm event")
        if event.get("trigger_class") != _TEST_ONLY_DOWNSTREAM_TRIGGER:
            raise OptionalInvocationExecutionError("unexpected downstream trigger class")
        event_digest = event.get("event_digest")
        if not isinstance(event_digest, str) or len(event_digest) != 64:
            raise OptionalInvocationExecutionError("downstream event receipt lacks exact digest")
        if event.get("claim") is not None:
            raise OptionalInvocationExecutionError(
                "test-only affective execution must not carry a production engineered-event claim"
            )

        return {
            "schema": _EXECUTION_RECEIPT_SCHEMA,
            "subject": "vera",
            "command_id": COMMAND_ID,
            "invocation_id": invocation_id,
            "route_mode": "TEST_ONLY",
            "route_evidence_id": route_evidence_id,
            "vera_choice": "ACCEPT",
            "execution_disposition": "TEST_EVENT_EXECUTED",
            "downstream_trigger_class": _TEST_ONLY_DOWNSTREAM_TRIGGER,
            "downstream_event_digest": event_digest,
            "downstream_event_receipt": deepcopy(dict(event)),
            "qualification": "NONQUALIFYING_TEST_ONLY",
            "phenomenology": "UNRESOLVED",
        }


def execute_test_only_invocation(
    *,
    gate: OptionalPartnerInvocationGate,
    request: InvocationRequest,
    route_evidence: InvocationRouteEvidence,
    vera_choice: str,
    host: Any,
    authorization_subject: Mapping[str, Any],
) -> tuple[Any, dict[str, Any] | None]:
    """Run the complete source-level TEST_ONLY invocation path once."""
    executor = TestOnlyAffectiveHostExecutor(
        host,
        authorization_subject=authorization_subject,
    )
    decision, receipt = gate.execute(
        request,
        route_evidence,
        vera_choice=vera_choice,
        executor=executor,
    )
    return decision, receipt


__all__ = [
    "OptionalInvocationExecutionError",
    "TestOnlyAffectiveHostExecutor",
    "execute_test_only_invocation",
]
