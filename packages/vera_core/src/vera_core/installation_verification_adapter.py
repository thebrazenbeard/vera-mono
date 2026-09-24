from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TYPE_CHECKING

from .installation_verification import (
    InstallationObservation,
    InstallationVerificationError,
    InstallationVerificationReceipt,
    InstallationVerificationRequirement,
    InstallationVerificationStore,
    InstallationVerificationTransport,
    installation_verification_requirements,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


@dataclass(frozen=True, slots=True)
class InstallationVerificationAssessment:
    task_id: str
    target_id: str
    distribution_name: str
    expected_version: str
    latest_status: str | None
    latest_receipt_digest: str | None
    latest_installation_digest: str | None
    transport_available: bool
    current_observed_version: str | None
    current_installation_digest: str | None
    current_matches_receipt: bool | None
    passed: bool
    reason: str


class QualifiedInstallationVerificationAdapter:
    """Read-only, task-bound installation currentness verification."""

    def __init__(
        self,
        *,
        runtime: "QualifiedVeraRuntime",
        transports: Mapping[
            tuple[str, str], InstallationVerificationTransport
        ],
    ):
        self.runtime = runtime
        registry = dict(transports)
        for scope, transport in registry.items():
            if (
                not isinstance(scope, tuple)
                or len(scope) != 2
                or not all(type(item) is str and item for item in scope)
            ):
                raise TypeError(
                    "installation verification transport keys must be "
                    "(target_id, distribution_name)"
                )
            if not isinstance(
                transport,
                InstallationVerificationTransport,
            ):
                raise TypeError(
                    f"installation verification transport for {scope!r} "
                    "does not satisfy InstallationVerificationTransport"
                )
            if (
                transport.target_id,
                transport.distribution_name,
            ) != scope:
                raise ValueError(
                    "installation verification transport identity mismatch "
                    f"for {scope!r}"
                )
        self.transports = registry

    def _requirements(
        self,
        task_id: str,
    ) -> tuple[InstallationVerificationRequirement, ...]:
        task = self.runtime.tasks.read(task_id)
        requirements = installation_verification_requirements(
            task.packet.evidence_requirements
        )
        seen: dict[tuple[str, str], str] = {}
        for requirement in requirements:
            key = (
                requirement.target_id,
                requirement.distribution_name,
            )
            prior = seen.get(key)
            if prior is not None and prior != requirement.expected_version:
                raise InstallationVerificationError(
                    "task packet declares conflicting installation versions "
                    f"for {key!r}"
                )
            seen[key] = requirement.expected_version
        return tuple(
            requirement
            for index, requirement in enumerate(requirements)
            if (
                requirement.target_id,
                requirement.distribution_name,
                requirement.expected_version,
            )
            not in {
                (
                    previous.target_id,
                    previous.distribution_name,
                    previous.expected_version,
                )
                for previous in requirements[:index]
            }
        )

    def _requirement(
        self,
        task_id: str,
        target_id: str,
        distribution_name: str,
    ) -> InstallationVerificationRequirement:
        matches = tuple(
            requirement
            for requirement in self._requirements(task_id)
            if (
                requirement.target_id == target_id
                and requirement.distribution_name
                == distribution_name
            )
        )
        if len(matches) != 1:
            raise InstallationVerificationError(
                "task packet must declare exactly one matching "
                "INSTALL_VERIFY requirement"
            )
        return matches[0]

    def assess(
        self,
        task_id: str,
        target_id: str,
        distribution_name: str,
    ) -> InstallationVerificationAssessment:
        task = self.runtime.tasks.read(task_id)
        requirement = self._requirement(
            task_id,
            target_id,
            distribution_name,
        )
        key = (target_id, distribution_name)
        transport = self.transports.get(key)
        try:
            latest = self.runtime.installation_verifications.latest(
                task_id,
                target_id,
                distribution_name,
            )
        except KeyError:
            return InstallationVerificationAssessment(
                task_id=task_id,
                target_id=target_id,
                distribution_name=distribution_name,
                expected_version=requirement.expected_version,
                latest_status=None,
                latest_receipt_digest=None,
                latest_installation_digest=None,
                transport_available=transport is not None,
                current_observed_version=None,
                current_installation_digest=None,
                current_matches_receipt=None,
                passed=False,
                reason="required installation verification has not run",
            )

        if latest.packet_digest != task.packet.packet_digest:
            return InstallationVerificationAssessment(
                task_id=task_id,
                target_id=target_id,
                distribution_name=distribution_name,
                expected_version=requirement.expected_version,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                latest_installation_digest=latest.installation_digest,
                transport_available=transport is not None,
                current_observed_version=None,
                current_installation_digest=None,
                current_matches_receipt=False,
                passed=False,
                reason=(
                    "latest installation verification binds a different "
                    "task packet"
                ),
            )
        if latest.expected_version != requirement.expected_version:
            return InstallationVerificationAssessment(
                task_id=task_id,
                target_id=target_id,
                distribution_name=distribution_name,
                expected_version=requirement.expected_version,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                latest_installation_digest=latest.installation_digest,
                transport_available=transport is not None,
                current_observed_version=None,
                current_installation_digest=None,
                current_matches_receipt=False,
                passed=False,
                reason=(
                    "latest installation verification binds a different "
                    "expected version"
                ),
            )
        if latest.status != "PASS":
            return InstallationVerificationAssessment(
                task_id=task_id,
                target_id=target_id,
                distribution_name=distribution_name,
                expected_version=requirement.expected_version,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                latest_installation_digest=latest.installation_digest,
                transport_available=transport is not None,
                current_observed_version=latest.observed_version,
                current_installation_digest=latest.installation_digest,
                current_matches_receipt=None,
                passed=False,
                reason=f"installation verification is {latest.status}",
            )
        if transport is None:
            return InstallationVerificationAssessment(
                task_id=task_id,
                target_id=target_id,
                distribution_name=distribution_name,
                expected_version=requirement.expected_version,
                latest_status=latest.status,
                latest_receipt_digest=latest.receipt_digest,
                latest_installation_digest=latest.installation_digest,
                transport_available=False,
                current_observed_version=None,
                current_installation_digest=None,
                current_matches_receipt=None,
                passed=False,
                reason=(
                    "stored installation verification passed, but current "
                    "installation cannot be refreshed because no transport "
                    "is available"
                ),
            )

        current = transport.observe(requirement.expected_version)
        current_status = InstallationVerificationStore._status(
            requirement,
            current,
        )
        current_matches = (
            current_status == "PASS"
            and current.observed_version == latest.observed_version
            and current.installation_digest
            == latest.installation_digest
        )
        return InstallationVerificationAssessment(
            task_id=task_id,
            target_id=target_id,
            distribution_name=distribution_name,
            expected_version=requirement.expected_version,
            latest_status=latest.status,
            latest_receipt_digest=latest.receipt_digest,
            latest_installation_digest=latest.installation_digest,
            transport_available=True,
            current_observed_version=current.observed_version,
            current_installation_digest=current.installation_digest,
            current_matches_receipt=current_matches,
            passed=current_matches,
            reason=(
                "installation verification passed and live installation "
                "digest remains current"
                if current_matches
                else (
                    "live installation no longer matches the exact stored "
                    "PASS observation"
                )
            ),
        )

    def verify(
        self,
        task_id: str,
        target_id: str,
        distribution_name: str,
    ) -> InstallationVerificationReceipt:
        task = self.runtime.tasks.read(task_id)
        if task.closed:
            raise InstallationVerificationError(
                "closed task cannot append installation verification"
            )
        if "install/registration" not in task.packet.relevant_surfaces:
            raise InstallationVerificationError(
                "task packet does not declare install/registration surface"
            )
        requirement = self._requirement(
            task_id,
            target_id,
            distribution_name,
        )
        transport = self.transports.get(
            (target_id, distribution_name)
        )
        if transport is None:
            raise InstallationVerificationError(
                "no host-injected installation verification transport "
                "for target/distribution"
            )
        self.runtime.accepted_permit()
        observation = transport.observe(requirement.expected_version)
        return self.runtime.installation_verifications.append(
            task_id=task_id,
            packet_digest=task.packet.packet_digest,
            requirement=requirement,
            observation=observation,
        )

    def assess_task(
        self,
        task_id: str,
    ) -> tuple[InstallationVerificationAssessment, ...]:
        return tuple(
            self.assess(
                task_id,
                requirement.target_id,
                requirement.distribution_name,
            )
            for requirement in self._requirements(task_id)
        )

    def recover(
        self,
    ) -> tuple[InstallationVerificationAssessment, ...]:
        return tuple(
            assessment
            for task in self.runtime.tasks.tasks()
            if not task.closed
            for assessment in self.assess_task(task.task_id)
        )
