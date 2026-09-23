from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _duration(*, status: str, value: float | None, reasons: list[str]) -> dict[str, Any]:
    return {
        "lower_bound_seconds": None,
        "reasons": reasons,
        "status": status,
        "upper_bound_seconds": None,
        "value_seconds": value,
    }


def build_proof_artifact() -> dict[str, Any]:
    """Build the deterministic, storage-neutral host-fixture proof artifact."""
    accepted_uncertainty = ["endpoint uncertainty accepted at threshold 0.001s"]
    binding_conflict = ["assistant causal binding does not match inbound.message_id"]

    return {
        "artifact": "TUL Instrumented Host Fixture Proof",
        "contract_baseline": "TUL Host Capability Requirement v0.1.3",
        "fixture_version": "0.1.0",
        "generated_at": "deterministic-fixture",
        "negative_cases": {
            "causal_binding_mismatch": {
                "capability": "PARTIAL",
                "causal_binding": "CONFLICTED",
                "inbound_to_assistant": _duration(
                    status="CONFLICTED", value=None, reasons=binding_conflict
                ),
                "inbound_to_generation": _duration(
                    status="CONFLICTED", value=None, reasons=binding_conflict
                ),
                "reasons": binding_conflict,
            },
            "codex_turn_metadata_rejected": _duration(
                status="CONFLICTED",
                value=None,
                reasons=[
                    "MESSAGE_CREATION requires PLATFORM_MESSAGE_METADATA or TRUSTED_BRIDGE",
                    "CODEX_TURN_METADATA cannot establish message creation or generation invocation",
                ],
            ),
            "documented_approximation": _duration(
                status="APPROXIMATE",
                value=7.0,
                reasons=[
                    "documented approximation method: fixture_cross_clock_calibration",
                    "error model: declared maximum error ±0.25 seconds",
                ],
            ),
            "missing_inbound_creation": _duration(
                status="UNAVAILABLE",
                value=None,
                reasons=["one or both temporal endpoints are unavailable"],
            ),
        },
        "positive_full_lifecycle": {
            "assistant": {
                "capture_mode": "POST_RESPONSE",
                "clock_domain": "fixture:deterministic-clock",
                "in_response_to_message_id": "msg-user-ceed094c-7e2a-4678-8fc8-687c1accdea4",
                "message_id": "msg-assistant-e7147f89-25da-4809-b6af-fa59cedaa855",
                "resolution_seconds": 0.000001,
                "speaker": "ASSISTANT",
                "time_semantics": "MESSAGE_CREATION",
                "timestamp": "2026-07-29T20:00:05.000000Z",
                "timestamp_source": "TRUSTED_BRIDGE",
                "uncertainty_seconds": 0.0005,
            },
            "evaluation": {
                "capability": "FULL",
                "causal_binding": "EXACT",
                "inbound_to_assistant": _duration(
                    status="EXACT", value=5.0, reasons=accepted_uncertainty
                ),
                "inbound_to_generation": _duration(
                    status="EXACT", value=2.0, reasons=accepted_uncertainty
                ),
                "reasons": [],
            },
            "generation": {
                "clock_domain": "fixture:deterministic-clock",
                "generation_event_definition": "PRE_MODEL_INVOCATION",
                "in_response_to_message_id": "msg-user-ceed094c-7e2a-4678-8fc8-687c1accdea4",
                "resolution_seconds": 0.000001,
                "time_semantics": "GENERATION_INVOCATION_START",
                "timestamp": "2026-07-29T20:00:02.000000Z",
                "timestamp_source": "HOST_RUNTIME_CLOCK",
                "uncertainty_seconds": 0.0005,
            },
            "inbound": {
                "clock_domain": "fixture:deterministic-clock",
                "message_id": "msg-user-ceed094c-7e2a-4678-8fc8-687c1accdea4",
                "resolution_seconds": 0.000001,
                "speaker": "USER",
                "time_semantics": "MESSAGE_CREATION",
                "timestamp": "2026-07-29T20:00:00.000000Z",
                "timestamp_source": "TRUSTED_BRIDGE",
                "uncertainty_seconds": 0.0005,
            },
            "semantic_payload_included": False,
        },
        "proof_classification": "FULL",
        "scope": {
            "host_controlled_fixture": True,
            "native_chatgpt_support_proven": False,
            "native_codex_support_proven": False,
            "semantic_payload_stored": False,
            "storage_used": False,
        },
    }


def write_proof_artifact(path: Path) -> dict[str, Any]:
    artifact = build_proof_artifact()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return artifact
