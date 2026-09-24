from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

from .route_verification import (
    RouteVerificationError,
    RouteVerificationReceipt,
    RouteVerificationRequirement,
    RouteVerificationStore,
    RouteVerificationTransport,
    route_verification_requirements,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


@dataclass(frozen=True, slots=True)
class RouteVerificationAssessment:
    task_id: str
    route_id: str
    expected_target: str
    latest_status: str | None
    latest_receipt_digest: str | None
    latest_route_digest: str | None
    transport_available: bool
    current_selected_target: str | None
    current_route_digest: str | None
    current_matches_receipt: bool | None
    passed: bool
    reason: str


class QualifiedRouteVerificationAdapter:
    """Read-only, task-bound live current-route verifier."""

    def __init__(
        self,
        *,
        runtime: "QualifiedVeraRuntime",
        transports: Mapping[str, RouteVerificationTransport],
    ):
        self.runtime = runtime
        registry = dict(transports)
        for route_id, transport in registry.items():
            if type(route_id) is not str or not route_id:
                raise TypeError(
                    "route verification transport keys must be non-empty strings"
                )
            if not isinstance(transport, RouteVerificationTransport):
                raise TypeError(
                    f"route verification transport for {route_id!r} "
                    "does not satisfy RouteVerificationTransport"
                )
            if transport.route_id != route_id:
                raise ValueError(
                    "route verification transport identity mismatch for "
                    f"{route_id!r}"
                )
        self.transports = registry

    def _requirements(
        self,
        task_id: str,
    ) -> tuple[RouteVerificationRequirement, ...]:
        task = self.runtime.tasks.read(task_id)
        requirements = route_verification_requirements(
            task.packet.evidence_requirements
        )
        seen: dict[str, str] = {}
        unique: list[RouteVerificationRequirement] = []
        for requirement in requirements:
            prior = seen.get(requirement.route_id)
            if prior is not None:
                if prior != requirement.expected_target:
                    raise RouteVerificationError(
                        "task packet declares conflicting expected targets "
                        f"for route {requirement.route_id!r}"
                    )
                continue
            seen[requirement.route_id] = requirement.expected_target
            unique.append(requirement)
        return tuple(unique)

    def _requirement(
        self,
        task_id: str,
        route_id: str,
    ) -> RouteVerificationRequirement:
        matches = tuple(
            item
            for item in self._requirements(task_id)
            if item.route_id == route_id
        )
        if len(matches) != 1:
            raise RouteVerificationError(
                "task packet must declare exactly one matching ROUTE_VERIFY "
                "requirement"
            )
        return matches[0]

    def assess(
        self,
        task_id: str,
        route_id: str,
    ) -> RouteVerificationAssessment:
        task = self.runtime.tasks.read(task_id)
        requirement = self._requirement(task_id, route_id)
        transport = self.transports.get(route_id)
        try:
            latest = self.runtime.route_verifications.latest(
                task_id,
                route_id,
            )
        except KeyError:
            return RouteVerificationAssessment(
                task_id=task_id,
                route_id=route_id,
                expected_target=requirement.expected_target,
                latest_status=None,
                latest_receipt_digest=None,
                latest_route_digest=None,
                transport_available=transport is not None,
                current_selected_target=None,
                current_route_digest=None,
                current_matches_receipt=None,
                passed=False,
                reason="required route verification has not run",
            )

        if latest.packet_digest != task.packet.packet_digest:
            return RouteVerificationAssessment(
                task_id=task_id,
                route_id=route_id,
                expected_target=requirement.expected_target,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                latest_route_digest=latest.route_digest,
                transport_available=transport is not None,
                current_selected_target=None,
                current_route_digest=None,
                current_matches_receipt=False,
                passed=False,
                reason="latest route verification binds a different task packet",
            )
        if latest.expected_target != requirement.expected_target:
            return RouteVerificationAssessment(
                task_id=task_id,
                route_id=route_id,
                expected_target=requirement.expected_target,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                latest_route_digest=latest.route_digest,
                transport_available=transport is not None,
                current_selected_target=None,
                current_route_digest=None,
                current_matches_receipt=False,
                passed=False,
                reason="latest route verification binds a different target",
            )
        if latest.status != "PASS":
            return RouteVerificationAssessment(
                task_id=task_id,
                route_id=route_id,
                expected_target=requirement.expected_target,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                latest_route_digest=latest.route_digest,
                transport_available=transport is not None,
                current_selected_target=latest.selected_target,
                current_route_digest=latest.route_digest,
                current_matches_receipt=None,
                passed=False,
                reason=f"route verification is {latest.status}",
            )
        if transport is None:
            return RouteVerificationAssessment(
                task_id=task_id,
                route_id=route_id,
                expected_target=requirement.expected_target,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                latest_route_digest=latest.route_digest,
                transport_available=False,
                current_selected_target=None,
                current_route_digest=None,
                current_matches_receipt=None,
                passed=False,
                reason=(
                    "stored route verification passed, but current route cannot "
                    "be refreshed because no transport is available"
                ),
            )

        current = transport.observe(requirement.expected_target)
        current_status = RouteVerificationStore._status(
            requirement,
            current,
        )
        current_matches = (
            current_status == "PASS"
            and current.selected_target == latest.selected_target
            and current.route_digest == latest.route_digest
        )
        return RouteVerificationAssessment(
            task_id=task_id,
            route_id=route_id,
            expected_target=requirement.expected_target,
            latest_status=latest.status,
            latest_receipt_digest=latest.receipt_digest,
            latest_route_digest=latest.route_digest,
            transport_available=True,
            current_selected_target=current.selected_target,
            current_route_digest=current.route_digest,
            current_matches_receipt=current_matches,
            passed=current_matches,
            reason=(
                "route verification passed and the live route remains current"
                if current_matches
                else (
                    "live route no longer matches the exact stored PASS "
                    "observation"
                )
            ),
        )

    def verify(
        self,
        task_id: str,
        route_id: str,
    ) -> RouteVerificationReceipt:
        task = self.runtime.tasks.read(task_id)
        if task.closed:
            raise RouteVerificationError(
                "closed task cannot append route verification"
            )
        if "current route" not in task.packet.relevant_surfaces:
            raise RouteVerificationError(
                "task packet does not declare current route surface"
            )
        requirement = self._requirement(task_id, route_id)
        transport = self.transports.get(route_id)
        if transport is None:
            raise RouteVerificationError(
                "no host-injected route verification transport for route"
            )
        self.runtime.accepted_permit()
        observation = transport.observe(requirement.expected_target)
        return self.runtime.route_verifications.append(
            task_id=task_id,
            packet_digest=task.packet.packet_digest,
            requirement=requirement,
            observation=observation,
        )

    def assess_task(
        self,
        task_id: str,
    ) -> tuple[RouteVerificationAssessment, ...]:
        return tuple(
            self.assess(task_id, requirement.route_id)
            for requirement in self._requirements(task_id)
        )

    def recover(
        self,
    ) -> tuple[RouteVerificationAssessment, ...]:
        return tuple(
            assessment
            for task in self.runtime.tasks.tasks()
            if not task.closed
            for assessment in self.assess_task(task.task_id)
        )
