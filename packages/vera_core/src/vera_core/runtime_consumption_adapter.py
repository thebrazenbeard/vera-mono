from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

from .route_verification import (
    RouteVerificationError,
    route_verification_requirements,
)
from .runtime_consumption import (
    RuntimeConsumptionRequirement,
    RuntimeConsumptionVerificationError,
    RuntimeConsumptionVerificationReceipt,
    RuntimeConsumptionVerificationStore,
    RuntimeConsumptionVerificationTransport,
    runtime_consumption_requirements,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


@dataclass(frozen=True, slots=True)
class RuntimeConsumptionAssessment:
    task_id: str
    consumer_id: str
    expected_route_id: str
    expected_target: str
    latest_status: str | None
    latest_receipt_digest: str | None
    latest_route_digest: str | None
    latest_process_instance_id: str | None
    latest_state_digest: str | None
    transport_available: bool
    current_consumed_target: str | None
    current_route_digest: str | None
    current_process_instance_id: str | None
    current_state_digest: str | None
    current_matches_receipt: bool | None
    route_verification_required: bool
    route_verified_current: bool | None
    passed: bool
    reason: str


class QualifiedRuntimeConsumptionAdapter:
    """Read-only task-bound verifier for actual live runtime consumption."""

    def __init__(
        self,
        *,
        runtime: "QualifiedVeraRuntime",
        transports: Mapping[str, RuntimeConsumptionVerificationTransport],
    ):
        self.runtime = runtime
        registry = dict(transports)
        for consumer_id, transport in registry.items():
            if type(consumer_id) is not str or not consumer_id:
                raise TypeError(
                    "runtime consumption transport keys must be non-empty strings"
                )
            if not isinstance(
                transport,
                RuntimeConsumptionVerificationTransport,
            ):
                raise TypeError(
                    f"runtime consumption transport for {consumer_id!r} "
                    "does not satisfy RuntimeConsumptionVerificationTransport"
                )
            if transport.consumer_id != consumer_id:
                raise ValueError(
                    "runtime consumption transport identity mismatch for "
                    f"{consumer_id!r}"
                )
        self.transports = registry

    def _requirements(
        self,
        task_id: str,
    ) -> tuple[RuntimeConsumptionRequirement, ...]:
        task = self.runtime.tasks.read(task_id)
        requirements = runtime_consumption_requirements(
            task.packet.evidence_requirements
        )
        seen: dict[str, tuple[str, str]] = {}
        unique: list[RuntimeConsumptionRequirement] = []
        for requirement in requirements:
            value = (requirement.route_id, requirement.expected_target)
            prior = seen.get(requirement.consumer_id)
            if prior is not None:
                if prior != value:
                    raise RuntimeConsumptionVerificationError(
                        "task packet declares conflicting runtime consumption "
                        f"requirements for consumer {requirement.consumer_id!r}"
                    )
                continue
            seen[requirement.consumer_id] = value
            unique.append(requirement)
        return tuple(unique)

    def _requirement(
        self,
        task_id: str,
        consumer_id: str,
    ) -> RuntimeConsumptionRequirement:
        matches = tuple(
            item
            for item in self._requirements(task_id)
            if item.consumer_id == consumer_id
        )
        if len(matches) != 1:
            raise RuntimeConsumptionVerificationError(
                "task packet must declare exactly one matching "
                "RUNTIME_CONSUME_VERIFY requirement"
            )
        return matches[0]

    def _matching_route_requirement(
        self,
        task_id: str,
        requirement: RuntimeConsumptionRequirement,
    ) -> bool:
        task = self.runtime.tasks.read(task_id)
        matches = tuple(
            item
            for item in route_verification_requirements(
                task.packet.evidence_requirements
            )
            if item.route_id == requirement.route_id
        )
        if not matches:
            return False
        expected_targets = {item.expected_target for item in matches}
        if len(expected_targets) != 1:
            raise RuntimeConsumptionVerificationError(
                "task packet has conflicting route verification targets"
            )
        if expected_targets != {requirement.expected_target}:
            raise RuntimeConsumptionVerificationError(
                "runtime consumption target conflicts with route verification target"
            )
        return True

    def _route_current(
        self,
        task_id: str,
        requirement: RuntimeConsumptionRequirement,
        route_digest: str | None,
    ) -> tuple[bool, bool | None, str | None]:
        required = self._matching_route_requirement(task_id, requirement)
        if not required:
            return False, None, None
        try:
            route = self.runtime.assess_route_verification(
                task_id,
                requirement.route_id,
            )
        except RouteVerificationError as exc:
            return True, False, str(exc)
        if not route.passed:
            return True, False, route.reason
        matches = (
            route_digest is not None
            and route.current_route_digest == route_digest
        )
        return (
            True,
            matches,
            (
                None
                if matches
                else "live runtime route digest does not match verified current route"
            ),
        )

    def assess(
        self,
        task_id: str,
        consumer_id: str,
    ) -> RuntimeConsumptionAssessment:
        task = self.runtime.tasks.read(task_id)
        requirement = self._requirement(task_id, consumer_id)
        transport = self.transports.get(consumer_id)
        try:
            latest = self.runtime.runtime_consumption_verifications.latest(
                task_id,
                consumer_id,
            )
        except KeyError:
            route_required = self._matching_route_requirement(
                task_id,
                requirement,
            )
            return RuntimeConsumptionAssessment(
                task_id=task_id,
                consumer_id=consumer_id,
                expected_route_id=requirement.route_id,
                expected_target=requirement.expected_target,
                latest_status=None,
                latest_receipt_digest=None,
                latest_route_digest=None,
                latest_process_instance_id=None,
                latest_state_digest=None,
                transport_available=transport is not None,
                current_consumed_target=None,
                current_route_digest=None,
                current_process_instance_id=None,
                current_state_digest=None,
                current_matches_receipt=None,
                route_verification_required=route_required,
                route_verified_current=None,
                passed=False,
                reason="required runtime consumption verification has not run",
            )

        base = dict(
            task_id=task_id,
            consumer_id=consumer_id,
            expected_route_id=requirement.route_id,
            expected_target=requirement.expected_target,
            latest_status=latest.status,
            latest_receipt_digest=latest.receipt_digest,
            latest_route_digest=latest.route_digest,
            latest_process_instance_id=latest.process_instance_id,
            latest_state_digest=latest.state_digest,
            transport_available=transport is not None,
        )
        route_required = self._matching_route_requirement(
            task_id,
            requirement,
        )
        if latest.packet_digest != task.packet.packet_digest:
            return RuntimeConsumptionAssessment(
                **base,
                current_consumed_target=None,
                current_route_digest=None,
                current_process_instance_id=None,
                current_state_digest=None,
                current_matches_receipt=False,
                route_verification_required=route_required,
                route_verified_current=None,
                passed=False,
                reason=(
                    "latest runtime consumption verification binds a "
                    "different task packet"
                ),
            )
        if (
            latest.expected_route_id != requirement.route_id
            or latest.expected_target != requirement.expected_target
        ):
            return RuntimeConsumptionAssessment(
                **base,
                current_consumed_target=None,
                current_route_digest=None,
                current_process_instance_id=None,
                current_state_digest=None,
                current_matches_receipt=False,
                route_verification_required=route_required,
                route_verified_current=None,
                passed=False,
                reason=(
                    "latest runtime consumption verification binds a "
                    "different route or target"
                ),
            )
        if latest.status != "PASS":
            return RuntimeConsumptionAssessment(
                **base,
                current_consumed_target=latest.consumed_target,
                current_route_digest=latest.route_digest,
                current_process_instance_id=latest.process_instance_id,
                current_state_digest=latest.state_digest,
                current_matches_receipt=None,
                route_verification_required=route_required,
                route_verified_current=None,
                passed=False,
                reason=f"runtime consumption verification is {latest.status}",
            )
        if transport is None:
            return RuntimeConsumptionAssessment(
                **base,
                current_consumed_target=None,
                current_route_digest=None,
                current_process_instance_id=None,
                current_state_digest=None,
                current_matches_receipt=None,
                route_verification_required=route_required,
                route_verified_current=None,
                passed=False,
                reason=(
                    "stored runtime consumption PASS cannot be refreshed "
                    "because no transport is available"
                ),
            )

        current = transport.observe(
            requirement.route_id,
            requirement.expected_target,
        )
        current_status = RuntimeConsumptionVerificationStore._status(
            requirement,
            current,
        )
        current_matches = (
            current_status == "PASS"
            and current.route_id == latest.observed_route_id
            and current.consumed_target == latest.consumed_target
            and current.route_digest == latest.route_digest
            and current.process_instance_id == latest.process_instance_id
            and current.state_digest == latest.state_digest
        )
        route_required, route_current, route_reason = self._route_current(
            task_id,
            requirement,
            current.route_digest,
        )
        passed = current_matches and route_current is not False
        if not current_matches:
            reason = (
                "live runtime consumption no longer matches the exact stored "
                "PASS observation"
            )
        elif route_current is False:
            reason = route_reason or (
                "live runtime consumption does not match verified route"
            )
        else:
            reason = (
                "runtime consumption PASS remains live-current"
                + (
                    " and matches the verified current route"
                    if route_required
                    else ""
                )
            )
        return RuntimeConsumptionAssessment(
            **base,
            current_consumed_target=current.consumed_target,
            current_route_digest=current.route_digest,
            current_process_instance_id=current.process_instance_id,
            current_state_digest=current.state_digest,
            current_matches_receipt=current_matches,
            route_verification_required=route_required,
            route_verified_current=route_current,
            passed=passed,
            reason=reason,
        )

    def verify(
        self,
        task_id: str,
        consumer_id: str,
    ) -> RuntimeConsumptionVerificationReceipt:
        task = self.runtime.tasks.read(task_id)
        if task.closed:
            raise RuntimeConsumptionVerificationError(
                "closed task cannot append runtime consumption verification"
            )
        if "runtime consumption" not in task.packet.relevant_surfaces:
            raise RuntimeConsumptionVerificationError(
                "task packet does not declare runtime consumption surface"
            )
        requirement = self._requirement(task_id, consumer_id)
        transport = self.transports.get(consumer_id)
        if transport is None:
            raise RuntimeConsumptionVerificationError(
                "no host-injected runtime consumption transport for consumer"
            )
        self.runtime.accepted_permit()
        observation = transport.observe(
            requirement.route_id,
            requirement.expected_target,
        )
        status = RuntimeConsumptionVerificationStore._status(
            requirement,
            observation,
        )
        if status == "PASS":
            route_required, route_current, route_reason = self._route_current(
                task_id,
                requirement,
                observation.route_digest,
            )
            if route_required and route_current is not True:
                raise RuntimeConsumptionVerificationError(
                    "runtime consumption cannot verify against non-current "
                    f"declared route: {route_reason or 'route mismatch'}"
                )
        return self.runtime.runtime_consumption_verifications.append(
            task_id=task_id,
            packet_digest=task.packet.packet_digest,
            requirement=requirement,
            observation=observation,
        )

    def assess_task(
        self,
        task_id: str,
    ) -> tuple[RuntimeConsumptionAssessment, ...]:
        return tuple(
            self.assess(task_id, requirement.consumer_id)
            for requirement in self._requirements(task_id)
        )

    def recover(
        self,
    ) -> tuple[RuntimeConsumptionAssessment, ...]:
        return tuple(
            assessment
            for task in self.runtime.tasks.tasks()
            if not task.closed
            for assessment in self.assess_task(task.task_id)
        )
