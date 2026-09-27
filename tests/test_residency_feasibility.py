from vera_assurance.residency_feasibility import (
    ResidencyEnvelope,
    SpecialistResidency,
    evaluate_residency_sequence,
)


def test_logical_pool_can_exceed_ceiling_while_each_modeled_step_fits():
    gib = 1024 ** 3
    mib = 1024 ** 2
    envelope = ResidencyEnvelope(
        resident_ceiling_bytes=4 * gib,
        shared_core_bytes=256 * mib,
        specialists=(
            SpecialistResidency(
                specialist_id="code",
                weight_bytes=int(2.5 * gib),
                runtime_bytes=384 * mib,
            ),
            SpecialistResidency(
                specialist_id="reason",
                weight_bytes=int(2.4 * gib),
                runtime_bytes=384 * mib,
            ),
            SpecialistResidency(
                specialist_id="vision",
                weight_bytes=int(2.3 * gib),
                runtime_bytes=384 * mib,
            ),
        ),
    )

    report = evaluate_residency_sequence(
        envelope,
        ("code", "reason", "vision", "code"),
    )

    assert report.logical_pool_exceeds_ceiling is True
    assert report.all_modeled_steps_within_ceiling is True
    assert report.hardware_measurement_performed is False
    assert report.qualification == "ANALYTICAL_FEASIBILITY_ONLY"
    assert report.authorization_effect == "NONE"
    assert len(report.input_sha256) == 64
