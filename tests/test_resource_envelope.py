from vera_assurance.resource_envelope import (
    FixedResourceEnvelope,
    ResourceUsage,
    adjudicate_resource_envelope,
)


def test_resource_envelope_fails_closed_when_measurement_is_missing():
    envelope = FixedResourceEnvelope(
        max_resident_memory_bytes=100,
        max_durable_state_bytes=200,
        max_update_cpu_seconds=0.1,
        max_query_cpu_seconds=0.2,
        max_shadow_auditions=0,
    )

    report = adjudicate_resource_envelope(
        envelope,
        ResourceUsage(
            resident_memory_bytes=None,
            durable_state_bytes=50,
            update_cpu_seconds=0.01,
            query_cpu_seconds=0.02,
            shadow_auditions=0,
        ),
    )

    assert report.valid is False
    assert "resident_memory_bytes:UNMEASURED" in report.violations
    assert report.authorization_effect == "NONE"


def test_resource_envelope_distinguishes_measured_zero_from_unknown():
    envelope = FixedResourceEnvelope(
        max_resident_memory_bytes=100,
        max_durable_state_bytes=200,
        max_update_cpu_seconds=0.1,
        max_query_cpu_seconds=0.2,
        max_shadow_auditions=0,
    )

    report = adjudicate_resource_envelope(
        envelope,
        ResourceUsage(
            resident_memory_bytes=0,
            durable_state_bytes=0,
            update_cpu_seconds=0.0,
            query_cpu_seconds=0.0,
            shadow_auditions=0,
        ),
    )

    assert report.valid is True
    assert report.violations == ()
