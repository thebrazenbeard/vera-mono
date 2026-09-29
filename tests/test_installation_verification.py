from dataclasses import dataclass

import pytest

from vera_core import (
    InstallationObservation,
    InstallationVerificationError,
    PythonDistributionInstallationTransport,
    QualifiedVeraRuntime,
    TaskExecutionError,
    TaskPacket,
    VeraStateDirectory,
)
from vera_memory import AdmissionRequest, MemoryClass


PROJECT = "vera-mono"
IDENTITY = "vera"
TARGET = "local-test"
DISTRIBUTION = "vera-mono"
VERSION = "0.1.0"


@dataclass
class FakeInstallationTransport:
    target_id: str = TARGET
    distribution_name: str = DISTRIBUTION
    observed_version: str = VERSION
    installation_digest: str = "a" * 64
    available: bool = True

    def __post_init__(self):
        self.calls = []

    def observe(self, expected_version):
        self.calls.append(expected_version)
        if not self.available:
            return InstallationObservation(
                target_id=self.target_id,
                distribution_name=self.distribution_name,
                observed_version=None,
                location_ref=None,
                installation_digest=None,
                file_count=0,
                import_roots=(),
                available=False,
            )
        return InstallationObservation(
            target_id=self.target_id,
            distribution_name=self.distribution_name,
            observed_version=self.observed_version,
            location_ref="/opt/vera-mono",
            installation_digest=self.installation_digest,
            file_count=42,
            import_roots=("vera_core", "vera_memory"),
            available=True,
        )


def packet():
    return TaskPacket(
        purpose="Verify exact installation state.",
        subject="local vera-mono installation",
        completion_state="Declared installation is verified-current.",
        evidence_requirements=(
            f"INSTALL_VERIFY|{TARGET}|{DISTRIBUTION}|{VERSION}",
        ),
        writable_scope=(),
        non_targets=("deployment", "provider activation"),
        forbidden_shortcuts_or_effects=(
            "do not infer installation from wheel build",
        ),
        priority_order=("exactness", "currentness", "reversibility"),
        unknowns=(),
        return_shape=("installation receipt",),
        relevant_surfaces=("install/registration",),
    )


def surfaces():
    return {"install/registration": "verified-current"}


def accepted_state(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    lifecycle = state.open()
    admitted = lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m1",
            text="installation verification state",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op1",
            project_id=PROJECT,
            governed_identity_id=IDENTITY,
        ),
        expected_head=lifecycle.memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-install",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def runtime_with_transport(tmp_path, transport):
    state = accepted_state(tmp_path)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        installation_verification_transports={
            (transport.target_id, transport.distribution_name): transport,
        },
    )
    runtime.start_task("task-install", packet())
    return state, runtime


def test_required_installation_verification_gates_closeout(tmp_path):
    transport = FakeInstallationTransport()
    _, runtime = runtime_with_transport(tmp_path, transport)

    before = runtime.assess_task_closeout(
        "task-install",
        surfaces=surfaces(),
    )
    assert before.ready is False
    assert any(
        "required installations are not verified-current" in reason
        for reason in before.reasons
    )

    receipt = runtime.verify_task_installation(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )
    assert receipt.status == "PASS"
    assert receipt.observed_version == VERSION
    assert transport.calls == [VERSION]

    assessment = runtime.assess_installation_verification(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )
    assert assessment.passed is True
    assert assessment.current_matches_receipt is True
    assert assessment.latest_receipt_digest == receipt.receipt_digest

    ready = runtime.assess_task_closeout(
        "task-install",
        surfaces=surfaces(),
    )
    assert ready.ready is True

    closed = runtime.close_task(
        "task-install",
        "close-install",
        surfaces=surfaces(),
        evidence_refs=("operator requested installation verification",),
        claim_ceiling=(
            "INSTALLATION_VERIFIED_NOT_ROUTE_NOT_RUNTIME_NOT_BEHAVIOR"
        ),
        next_frontier="verify current route separately",
    )
    assert closed.closed is True
    assert any(
        ref
        == (
            f"task-installation:{TARGET}:{DISTRIBUTION}:"
            f"{receipt.receipt_digest}"
        )
        for ref in closed.closeout.evidence_refs
    )

    with pytest.raises(InstallationVerificationError):
        runtime.verify_task_installation(
            "task-install",
            TARGET,
            DISTRIBUTION,
        )


def test_live_installation_digest_change_invalidates_stored_pass(tmp_path):
    transport = FakeInstallationTransport()
    _, runtime = runtime_with_transport(tmp_path, transport)
    runtime.verify_task_installation(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )
    assert runtime.assess_task_closeout(
        "task-install",
        surfaces=surfaces(),
    ).ready is True

    transport.installation_digest = "b" * 64
    assessment = runtime.assess_installation_verification(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )
    assert assessment.latest_status == "PASS"
    assert assessment.passed is False
    assert assessment.current_matches_receipt is False
    assert runtime.assess_task_closeout(
        "task-install",
        surfaces=surfaces(),
    ).ready is False


def test_wrong_installed_version_is_fail_and_cannot_close(tmp_path):
    transport = FakeInstallationTransport(
        observed_version="0.2.0",
    )
    _, runtime = runtime_with_transport(tmp_path, transport)

    receipt = runtime.verify_task_installation(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )
    assert receipt.status == "FAIL"
    assessment = runtime.assess_installation_verification(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )
    assert assessment.passed is False
    assert runtime.assess_task_closeout(
        "task-install",
        surfaces=surfaces(),
    ).ready is False


def test_stored_pass_without_live_transport_is_not_current_after_restart(tmp_path):
    transport = FakeInstallationTransport()
    state, runtime = runtime_with_transport(tmp_path, transport)
    receipt = runtime.verify_task_installation(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )
    assert receipt.status == "PASS"

    restarted = QualifiedVeraRuntime.from_state_directory(state)
    assessment = restarted.assess_installation_verification(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )
    assert assessment.latest_status == "PASS"
    assert assessment.transport_available is False
    assert assessment.passed is False
    assert restarted.assess_task_closeout(
        "task-install",
        surfaces=surfaces(),
    ).ready is False

    recovery = restarted.resume_context()[
        "installation_verification_recovery"
    ]
    assert len(recovery) == 1
    assert recovery[0]["task_id"] == "task-install"
    assert recovery[0]["passed"] is False
    assert recovery[0]["transport_available"] is False


def test_install_requirement_cannot_be_closed_as_out_of_scope(tmp_path):
    transport = FakeInstallationTransport()
    _, runtime = runtime_with_transport(tmp_path, transport)
    runtime.verify_task_installation(
        "task-install",
        TARGET,
        DISTRIBUTION,
    )

    assessment = runtime.assess_task_closeout(
        "task-install",
        surfaces={"install/registration": "out-of-scope"},
    )
    assert assessment.ready is False
    assert any(
        "cannot close an install/registration surface" in reason
        for reason in assessment.reasons
    )


def test_python_distribution_install_inspector_reads_real_installed_distribution():
    transport = PythonDistributionInstallationTransport(
        target_id="ci-python",
        distribution_name="jsonschema",
    )
    observation = transport.observe("ignored-by-read-only-inspector")

    assert observation.available is True
    assert observation.observed_version
    assert observation.location_ref
    assert observation.file_count > 0
    assert observation.installation_digest is not None
    assert len(observation.installation_digest) == 64
    assert "jsonschema" in observation.import_roots
