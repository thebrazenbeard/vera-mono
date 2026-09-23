from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StateTransitionError(ValueError):
    """Raised when a PCCC lifecycle transition is not legal."""


class JobState(str, Enum):
    SUBMITTED = "SUBMITTED"
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AttemptState(str, Enum):
    CLAIMED = "CLAIMED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    ABANDONED = "ABANDONED"


class CancellationState(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    OBSERVED = "OBSERVED"
    STOPPING = "STOPPING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class SideEffectStatus(str, Enum):
    NONE = "NONE"
    POSSIBLE = "POSSIBLE"
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"


class JobEvent(str, Enum):
    REQUEST_AUTHORIZATION = "REQUEST_AUTHORIZATION"
    AUTHORIZE = "AUTHORIZE"
    REJECT = "REJECT"
    QUEUE = "QUEUE"
    CLAIM = "CLAIM"
    START = "START"
    COMPLETE = "COMPLETE"
    FAIL_TERMINAL = "FAIL_TERMINAL"
    FAIL_RETRYABLE = "FAIL_RETRYABLE"
    LEASE_EXPIRE = "LEASE_EXPIRE"
    RECOVER_NO_EFFECT = "RECOVER_NO_EFFECT"
    RECOVER_SUCCESS = "RECOVER_SUCCESS"
    RECOVER_FAILURE = "RECOVER_FAILURE"
    REQUEST_CANCEL = "REQUEST_CANCEL"
    ACK_CANCEL = "ACK_CANCEL"
    EXPIRE = "EXPIRE"


class AttemptEvent(str, Enum):
    PREPARE_START = "PREPARE_START"
    START = "START"
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"
    ACK_CANCEL = "ACK_CANCEL"
    LEASE_EXPIRE = "LEASE_EXPIRE"
    ABANDON = "ABANDON"


class CancellationEvent(str, Enum):
    REQUEST = "REQUEST"
    OBSERVE = "OBSERVE"
    BEGIN_STOP = "BEGIN_STOP"
    ACKNOWLEDGE = "ACKNOWLEDGE"


TERMINAL_JOB_STATES = frozenset(
    {
        JobState.SUCCEEDED,
        JobState.FAILED,
        JobState.CANCELLED,
        JobState.REJECTED,
        JobState.EXPIRED,
    }
)
TERMINAL_ATTEMPT_STATES = frozenset(
    {
        AttemptState.SUCCEEDED,
        AttemptState.FAILED,
        AttemptState.CANCELLED,
        AttemptState.LEASE_EXPIRED,
        AttemptState.ABANDONED,
    }
)


@dataclass(frozen=True)
class TransitionGuards:
    state_version: int
    expected_state_version: int
    lease_current: bool = False
    fence_current: bool = False
    attempts_remaining: bool = False
    side_effect_status: SideEffectStatus = SideEffectStatus.NONE
    independent_readback: bool = False
    no_newer_attempt: bool = False
    cancellation_state: CancellationState = CancellationState.NONE
    safe_to_expire: bool = False

    def validate_version(self) -> None:
        if (
            isinstance(self.state_version, bool)
            or isinstance(self.expected_state_version, bool)
            or not isinstance(self.state_version, int)
            or not isinstance(self.expected_state_version, int)
            or self.state_version < 0
            or self.expected_state_version != self.state_version
        ):
            raise StateTransitionError("state_version conflict")

    def require_fence(self) -> None:
        if not self.lease_current or not self.fence_current:
            raise StateTransitionError(
                "current lease and fence are required"
            )


def transition_job(
    state: JobState | str,
    event: JobEvent | str,
    *,
    guards: TransitionGuards,
) -> JobState:
    try:
        current = JobState(state)
        observed = JobEvent(event)
    except ValueError as exc:
        raise StateTransitionError(
            "unknown job state or event"
        ) from exc
    guards.validate_version()
    if current in TERMINAL_JOB_STATES:
        raise StateTransitionError(
            f"terminal job state {current.value} is immutable"
        )

    direct = {
        (
            JobState.SUBMITTED,
            JobEvent.REQUEST_AUTHORIZATION,
        ): JobState.PENDING_AUTHORIZATION,
        (
            JobState.PENDING_AUTHORIZATION,
            JobEvent.AUTHORIZE,
        ): JobState.AUTHORIZED,
        (
            JobState.PENDING_AUTHORIZATION,
            JobEvent.REJECT,
        ): JobState.REJECTED,
        (JobState.AUTHORIZED, JobEvent.QUEUE): JobState.QUEUED,
        (JobState.QUEUED, JobEvent.CLAIM): JobState.CLAIMED,
    }
    if (current, observed) in direct:
        return direct[(current, observed)]

    if observed == JobEvent.START:
        if current != JobState.CLAIMED:
            raise StateTransitionError("only a claimed job may start")
        guards.require_fence()
        return JobState.RUNNING

    if observed == JobEvent.COMPLETE:
        if current != JobState.RUNNING:
            raise StateTransitionError(
                "completion requires RUNNING; CLAIMED cannot "
                "succeed directly"
            )
        guards.require_fence()
        return JobState.SUCCEEDED

    if observed == JobEvent.FAIL_TERMINAL:
        if current not in {
            JobState.CLAIMED,
            JobState.RUNNING,
            JobState.RECOVERY_REQUIRED,
        }:
            raise StateTransitionError(
                "terminal failure is not legal here"
            )
        if current != JobState.RECOVERY_REQUIRED:
            guards.require_fence()
        return JobState.FAILED

    if observed == JobEvent.FAIL_RETRYABLE:
        if current not in {JobState.CLAIMED, JobState.RUNNING}:
            raise StateTransitionError(
                "retryable failure is not legal here"
            )
        guards.require_fence()
        if guards.side_effect_status != SideEffectStatus.NONE:
            return JobState.RECOVERY_REQUIRED
        return (
            JobState.QUEUED
            if guards.attempts_remaining
            else JobState.FAILED
        )

    if observed == JobEvent.LEASE_EXPIRE:
        if current not in {JobState.CLAIMED, JobState.RUNNING}:
            raise StateTransitionError(
                "lease expiry is not legal here"
            )
        if guards.side_effect_status != SideEffectStatus.NONE:
            return JobState.RECOVERY_REQUIRED
        return (
            JobState.QUEUED
            if guards.attempts_remaining
            else JobState.FAILED
        )

    if observed == JobEvent.RECOVER_NO_EFFECT:
        if current != JobState.RECOVERY_REQUIRED:
            raise StateTransitionError(
                "recovery resolution requires recovery state"
            )
        if (
            not guards.independent_readback
            or not guards.no_newer_attempt
        ):
            raise StateTransitionError(
                "independent exact readback is required"
            )
        if guards.side_effect_status != SideEffectStatus.NONE:
            raise StateTransitionError(
                "no-effect recovery requires NONE"
            )
        return (
            JobState.QUEUED
            if guards.attempts_remaining
            else JobState.FAILED
        )

    if observed == JobEvent.RECOVER_SUCCESS:
        if current != JobState.RECOVERY_REQUIRED:
            raise StateTransitionError(
                "recovery resolution requires recovery state"
            )
        if (
            not guards.independent_readback
            or not guards.no_newer_attempt
            or guards.side_effect_status
            != SideEffectStatus.CONFIRMED
        ):
            raise StateTransitionError(
                "recovery success requires confirmed "
                "independent readback"
            )
        return JobState.SUCCEEDED

    if observed == JobEvent.RECOVER_FAILURE:
        if current != JobState.RECOVERY_REQUIRED:
            raise StateTransitionError(
                "recovery resolution requires recovery state"
            )
        if (
            not guards.independent_readback
            or not guards.no_newer_attempt
        ):
            raise StateTransitionError(
                "independent exact readback is required"
            )
        return JobState.FAILED

    if observed == JobEvent.REQUEST_CANCEL:
        if current in {
            JobState.SUBMITTED,
            JobState.PENDING_AUTHORIZATION,
            JobState.AUTHORIZED,
            JobState.QUEUED,
        }:
            return JobState.CANCELLED
        if current in {
            JobState.CLAIMED,
            JobState.RUNNING,
            JobState.RECOVERY_REQUIRED,
        }:
            return current
        raise StateTransitionError(
            "cancellation request is not legal here"
        )

    if observed == JobEvent.ACK_CANCEL:
        if current not in {
            JobState.CLAIMED,
            JobState.RUNNING,
            JobState.RECOVERY_REQUIRED,
        }:
            raise StateTransitionError(
                "cancellation acknowledgement is not legal"
            )
        if guards.cancellation_state not in {
            CancellationState.REQUESTED,
            CancellationState.OBSERVED,
            CancellationState.STOPPING,
        }:
            raise StateTransitionError(
                "cancellation was not requested"
            )
        if current != JobState.RECOVERY_REQUIRED:
            guards.require_fence()
        return JobState.CANCELLED

    if observed == JobEvent.EXPIRE:
        if (
            current
            in {JobState.RUNNING, JobState.RECOVERY_REQUIRED}
            and (
                not guards.safe_to_expire
                or guards.side_effect_status
                in {
                    SideEffectStatus.POSSIBLE,
                    SideEffectStatus.UNKNOWN,
                }
            )
        ):
            return JobState.RECOVERY_REQUIRED
        if not guards.safe_to_expire:
            raise StateTransitionError(
                "safe expiry evidence is required"
            )
        return JobState.EXPIRED

    raise StateTransitionError(
        f"illegal job transition: {current.value} + {observed.value}"
    )


def transition_attempt(
    state: AttemptState | str,
    event: AttemptEvent | str,
    *,
    lease_current: bool,
    fence_current: bool,
) -> AttemptState:
    try:
        current = AttemptState(state)
        observed = AttemptEvent(event)
    except ValueError as exc:
        raise StateTransitionError(
            "unknown attempt state or event"
        ) from exc
    if current in TERMINAL_ATTEMPT_STATES:
        raise StateTransitionError(
            f"terminal attempt state {current.value} is immutable"
        )
    if not lease_current or not fence_current:
        raise StateTransitionError(
            "current attempt lease and fence are required"
        )
    table = {
        (
            AttemptState.CLAIMED,
            AttemptEvent.PREPARE_START,
        ): AttemptState.STARTING,
        (
            AttemptState.STARTING,
            AttemptEvent.START,
        ): AttemptState.RUNNING,
        (
            AttemptState.RUNNING,
            AttemptEvent.COMPLETE,
        ): AttemptState.SUCCEEDED,
        (AttemptState.CLAIMED, AttemptEvent.FAIL): AttemptState.FAILED,
        (AttemptState.STARTING, AttemptEvent.FAIL): AttemptState.FAILED,
        (AttemptState.RUNNING, AttemptEvent.FAIL): AttemptState.FAILED,
        (
            AttemptState.CLAIMED,
            AttemptEvent.ACK_CANCEL,
        ): AttemptState.CANCELLED,
        (
            AttemptState.STARTING,
            AttemptEvent.ACK_CANCEL,
        ): AttemptState.CANCELLED,
        (
            AttemptState.RUNNING,
            AttemptEvent.ACK_CANCEL,
        ): AttemptState.CANCELLED,
        (
            AttemptState.CLAIMED,
            AttemptEvent.LEASE_EXPIRE,
        ): AttemptState.LEASE_EXPIRED,
        (
            AttemptState.STARTING,
            AttemptEvent.LEASE_EXPIRE,
        ): AttemptState.LEASE_EXPIRED,
        (
            AttemptState.RUNNING,
            AttemptEvent.LEASE_EXPIRE,
        ): AttemptState.LEASE_EXPIRED,
        (
            AttemptState.CLAIMED,
            AttemptEvent.ABANDON,
        ): AttemptState.ABANDONED,
        (
            AttemptState.STARTING,
            AttemptEvent.ABANDON,
        ): AttemptState.ABANDONED,
    }
    try:
        return table[(current, observed)]
    except KeyError as exc:
        raise StateTransitionError(
            f"illegal attempt transition: {current.value} + "
            f"{observed.value}"
        ) from exc


def transition_cancellation(
    state: CancellationState | str,
    event: CancellationEvent | str,
) -> CancellationState:
    try:
        current = CancellationState(state)
        observed = CancellationEvent(event)
    except ValueError as exc:
        raise StateTransitionError(
            "unknown cancellation state or event"
        ) from exc
    table = {
        (
            CancellationState.NONE,
            CancellationEvent.REQUEST,
        ): CancellationState.REQUESTED,
        (
            CancellationState.REQUESTED,
            CancellationEvent.OBSERVE,
        ): CancellationState.OBSERVED,
        (
            CancellationState.OBSERVED,
            CancellationEvent.BEGIN_STOP,
        ): CancellationState.STOPPING,
        (
            CancellationState.REQUESTED,
            CancellationEvent.ACKNOWLEDGE,
        ): CancellationState.ACKNOWLEDGED,
        (
            CancellationState.OBSERVED,
            CancellationEvent.ACKNOWLEDGE,
        ): CancellationState.ACKNOWLEDGED,
        (
            CancellationState.STOPPING,
            CancellationEvent.ACKNOWLEDGE,
        ): CancellationState.ACKNOWLEDGED,
    }
    try:
        return table[(current, observed)]
    except KeyError as exc:
        raise StateTransitionError(
            f"illegal cancellation transition: {current.value} + "
            f"{observed.value}"
        ) from exc


__all__ = [
    "AttemptEvent",
    "AttemptState",
    "CancellationEvent",
    "CancellationState",
    "JobEvent",
    "JobState",
    "SideEffectStatus",
    "StateTransitionError",
    "TERMINAL_ATTEMPT_STATES",
    "TERMINAL_JOB_STATES",
    "TransitionGuards",
    "transition_attempt",
    "transition_cancellation",
    "transition_job",
]
