import hashlib
import json
from pathlib import Path

import jsonschema
import vera_core
from vera_core.behavior_attestation import BehaviorAttestationReceipt


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _receipt(index: int) -> BehaviorAttestationReceipt:
    provider_id = "third-party-environment-attestor"
    provider_key_id = "external-key-1"
    provider_key_digest = _digest("external-key")
    declaration_digest = _digest("external-environment-behavior")
    behavior_receipt_digest = _digest(f"behavior-{index}")
    return BehaviorAttestationReceipt(
        sequence=index + 1,
        task_id=f"external-task-{index}",
        packet_digest=_digest(f"packet-{index}"),
        consumer_id="external-environment-eval",
        probe_id="external-env-hidden-1",
        evidence_kind="BEHAVIOR",
        expected_declaration_digest=declaration_digest,
        expected_provider_id=provider_id,
        expected_provider_key_id=provider_key_id,
        expected_provider_key_digest=provider_key_digest,
        expected_effect_subject_digest=None,
        behavior_effect_receipt_digest=behavior_receipt_digest,
        observed_behavior_effect_receipt_digest=behavior_receipt_digest,
        observed_declaration_digest=declaration_digest,
        observed_process_instance_id=f"external-process-{index}",
        observed_runtime_state_digest=_digest(f"runtime-{index}"),
        observed_stimulus_digest=_digest(f"stimulus-{index}"),
        observed_outcome_digest=_digest(f"outcome-{index}"),
        observed_raw_response_digest=_digest(f"raw-response-{index}"),
        observed_provider_id=provider_id,
        observed_provider_key_id=provider_key_id,
        observed_provider_key_digest=provider_key_digest,
        observed_attestation_nonce=f"nonce-{index}",
        observed_attestation_subject_digest=_digest(f"subject-{index}"),
        observed_attestation_signature=_digest(f"signature-{index}"),
        observed_signature_valid=True,
        observed_external_effect_id=None,
        observed_external_effect_receipt_digest=None,
        observed_external_effect_subject_digest=None,
        observed_external_evidence_digest=_digest(f"evidence-{index}"),
        evidence_ref=f"external://evidence/{index}",
        status="PASS",
        predecessor_digest=_digest(f"predecessor-{index}"),
        receipt_digest=_digest(f"receipt-{index}"),
    )


def test_external_environment_measurement_binds_signed_receipts_and_stays_partial():
    attempt_type = getattr(vera_core, "ExternalEnvironmentAttempt", None)
    qualify = getattr(vera_core, "qualify_external_environment", None)
    assert callable(attempt_type), "external environment attempt API is missing"
    assert callable(qualify), "external environment qualification API is missing"

    outcomes = ("SUCCESS", "SUCCESS", "FAILURE", "SUCCESS")
    interventions = (0, 1, 2, 0)
    attempts = tuple(
        attempt_type(
            attempt_id=f"attempt-{index}",
            environment_id="public-third-party-env-v1",
            environment_owner="independent-third-party",
            environment_declaration_digest=_digest(
                "public-third-party-env-v1"
            ),
            environment_authorship="NON_VERA_THIRD_PARTY",
            attestation=_receipt(index),
            outcome_state=outcome,
            intervention_count=intervention,
        )
        for index, (outcome, intervention) in enumerate(
            zip(outcomes, interventions, strict=True)
        )
    )

    result = qualify(
        attempts,
        min_attempts=4,
        min_task_success_rate=0.75,
        max_mean_interventions=1.0,
        max_unresolved_rate=0.25,
        repository="thebrazenbeard/vera-mono",
        exact_head="1" * 40,
        runtime_binding="QUALIFIED_RUNTIME",
        probe_id="external-env-hidden-1",
        items_digest="a" * 64,
        curator_independence="INDEPENDENT_MODEL",
        training_overlap="NONE_KNOWN",
        developer_item_access=False,
        tool_access=("provider:third-party-environment",),
        claim_ceiling="EXTERNAL_ENVIRONMENT_MEASUREMENT_ONLY_NOT_AGI",
    )

    assert result.metrics.attempted == 4
    assert result.metrics.task_success_rate == 0.75
    assert result.metrics.mean_interventions == 0.75
    assert result.metrics.unresolved_rate == 0.0
    assert result.metrics.invalid_attestation_count == 0
    assert result.packet["probe"]["family"] == "EXTERNAL_ENVIRONMENT"
    assert result.packet["dimension_states"] == {
        "EXTERNAL_GENERALIZATION": "PARTIAL",
    }
    assert result.packet["independent_review"] is None

    artifact = json.loads(result.qualification_artifact_json)
    assert artifact["environment"]["authorship"] == "NON_VERA_THIRD_PARTY"
    assert len(artifact["attempts"]) == 4
    assert all(
        item["attestation"]["observed_raw_response_digest"]
        for item in artifact["attempts"]
    )
    assert all(
        item["attestation"]["observed_external_evidence_digest"]
        for item in artifact["attempts"]
    )

    schema = json.loads(
        Path(
            "architecture/schemas/"
            "VERA_AGI_EVALUATION_PACKET_V1.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.validate(result.packet, schema)
