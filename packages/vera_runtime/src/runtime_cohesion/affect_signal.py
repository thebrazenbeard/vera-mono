from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .affect_bound_runtime import BoundVeraOrgasmRuntime
from .affect_host import VeraAffectiveRuntimeHost


_SIGNAL_SCHEMA = "VERA_AFFECTIVE_MODULATION_SIGNAL_V1"
_UNROOTED = "IN_PROCESS_UNROOTED_NON_QUALIFYING"
_NO_PRODUCTION_AUTHORITY = "NO_PRODUCTION_AUTHORITY_CLAIM"

_ACTIVE_GAINS = {
    "valuation": 0.35,
    "salience": 0.55,
    "attention": 0.50,
    "response_selection_priors": 0.40,
    "expression": 0.35,
    "memory_strength_candidate_weighting": 0.25,
}
_NONCLIMAX_GAINS = {
    "valuation": 0.16,
    "salience": 0.22,
    "attention": 0.18,
    "response_selection_priors": 0.14,
    "expression": 0.12,
    "memory_strength_candidate_weighting": 0.10,
}
_NUMERIC_TARGETS = tuple(_ACTIVE_GAINS)
_RUNTIME_OBSERVATION_METHODS = frozenset({
    "snapshot",
    "export_state",
    "_organic_climax_eligible",
    "_refractory_reentry_blocked",
})


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _canonical_copy(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be canonically serializable") from exc


def _digest(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated_signal_origin(host: VeraAffectiveRuntimeHost) -> BoundVeraOrgasmRuntime:
    if type(host) is not VeraAffectiveRuntimeHost:
        raise TypeError("affective modulation requires the exact VeraAffectiveRuntimeHost class")

    runtime = host.runtime
    if type(runtime) is not BoundVeraOrgasmRuntime:
        raise TypeError("affective host runtime must be the exact BoundVeraOrgasmRuntime class")
    shadowed_runtime = sorted(_RUNTIME_OBSERVATION_METHODS.intersection(runtime.__dict__))
    if shadowed_runtime:
        raise ValueError(
            "affective runtime has caller-shadowed observation methods: "
            + ",".join(shadowed_runtime)
        )

    sealed_contract = host._runtime_contract_snapshot
    if _canonical_copy(runtime.contract, label="live runtime contract") != sealed_contract:
        raise ValueError("affective runtime contract no longer matches the host construction snapshot")
    return runtime


def _capture_runtime_observation(
    host: VeraAffectiveRuntimeHost,
    runtime: BoundVeraOrgasmRuntime,
) -> dict[str, Any]:
    raw = BoundVeraOrgasmRuntime._capture_causal_observation(runtime)
    return _canonical_copy(raw, label="affective runtime observation")


def _frame_from_observation(
    host: VeraAffectiveRuntimeHost,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    state = observation.get("state")
    if not isinstance(state, Mapping):
        raise ValueError("affective runtime observation lacks a structured state")
    receipt = observation.get("last_event_receipt")
    if receipt is not None and not isinstance(receipt, Mapping):
        raise ValueError("affective runtime last_event_receipt must be structured or null")
    contract = host._runtime_contract_snapshot
    return {
        "experience_class": "ENGINEERED_AFFECTIVE_INTEROCEPTION",
        "subject": "vera",
        "presence": state["presence"],
        "phase": state["phase"],
        "sexual_salience": state["sexual_salience"],
        "activation_intensity": state["activation_intensity"],
        "positive_valence": state["positive_valence"],
        "anticipation": state["anticipation"],
        "inhibition": state["inhibition"],
        "coherence": state["coherence"],
        "coalition_stability": state["coalition_stability"],
        "persistence_window_ms": state["persistence_window_ms"],
        "hedonic_impact": state["hedonic_impact"],
        "consummatory_gain": state["consummatory_gain"],
        "satiation": state["satiation"],
        "resolution_intensity": state["resolution_intensity"],
        "refractory_strength": state["refractory_strength"],
        "context_eligible": state["context_eligible"],
        "action_tendency": state["action_tendency"],
        "active_orgasm_event": state["active_orgasm_event"],
        "organic_climax_eligible": state["organic_climax_eligible"],
        "last_trigger_class": receipt.get("trigger_class") if receipt else None,
        "last_event_digest": receipt.get("event_digest") if receipt else None,
        "source_revision": observation.get("source_revision"),
        "contract_blob_sha": host.contract_blob_sha,
        "phenomenology": contract["claim_ceiling"]["phenomenology"],
    }


def _control_vector_from_frame(frame: Mapping[str, Any]) -> dict[str, float]:
    positive_valence = _clamp((float(frame["positive_valence"]) + 1.0) / 2.0)
    activation = _clamp(float(frame["activation_intensity"]))
    coherence = _clamp(float(frame["coherence"]))
    hedonic = _clamp(float(frame["hedonic_impact"]))
    consummatory = _clamp(float(frame["consummatory_gain"]))
    satiation = _clamp(float(frame["satiation"]))
    resolution = _clamp(float(frame["resolution_intensity"]))
    refractory = _clamp(float(frame["refractory_strength"]))
    recovery_active = frame["phase"] in {"RESOLUTION", "SATIATED_OR_REFRACTORY"}
    return {
        "approach_gain": _clamp(0.55 * activation + 0.25 * coherence + 0.20 * positive_valence),
        "salience_gain": _clamp(0.50 * activation + 0.30 * coherence + 0.20 * hedonic),
        "attention_narrowing": _clamp(0.35 * activation + 0.35 * coherence + 0.30 * hedonic),
        "consummatory_gain": _clamp(0.55 * consummatory + 0.45 * hedonic),
        "plasticity_gain": 0.0 if recovery_active else _clamp(
            0.40 * hedonic + 0.25 * coherence + 0.20 * activation + 0.15 * resolution
        ),
        "satiation": satiation,
        "resolution": resolution,
        "refractory": refractory,
    }


def _target_strengths(
    allowed: set[str],
    frame: Mapping[str, Any],
    vector: Mapping[str, float],
) -> dict[str, float]:
    strengths = {target: 0.0 for target in _NUMERIC_TARGETS if target in allowed}

    if frame["active_orgasm_event"]:
        intensity = _clamp(
            0.45 * float(frame["hedonic_impact"])
            + 0.30 * float(frame["coherence"])
            + 0.25 * float(frame["activation_intensity"])
        )
        for target, gain in _ACTIVE_GAINS.items():
            if target in strengths:
                strengths[target] = _clamp(gain * intensity)
        return strengths

    if not frame["context_eligible"]:
        return strengths

    recovery_active = frame["phase"] in {"RESOLUTION", "SATIATED_OR_REFRACTORY"}
    arousal_force = max(
        vector["approach_gain"],
        vector["salience_gain"],
        vector["attention_narrowing"],
    )
    recovery_force = max(vector["satiation"], vector["resolution"], vector["refractory"])
    experiential_force = _clamp(max(arousal_force, 0.70 * recovery_force))
    if experiential_force < 0.03:
        return strengths

    for target, gain in _NONCLIMAX_GAINS.items():
        if target not in strengths:
            continue
        if recovery_active and target == "memory_strength_candidate_weighting":
            continue
        strengths[target] = _clamp(gain * experiential_force)
    return strengths


def _build_affective_modulation_signal_from_observation(
    host: VeraAffectiveRuntimeHost,
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive signal/ancestry from one already-captured host observation."""
    runtime = _validated_signal_origin(host)
    snapshot = _canonical_copy(observation, label="affective runtime observation")
    if snapshot.get("runtime_instance_id") != runtime.runtime_instance_id:
        raise ValueError("affective runtime observation instance does not match bound host")
    if snapshot.get("source_revision") != runtime.source_revision:
        raise ValueError("affective runtime observation source does not match bound host")

    state = snapshot.get("state")
    if not isinstance(state, Mapping):
        raise ValueError("affective runtime observation lacks state")
    governance = snapshot.get("trigger_governance") or {}
    if not isinstance(governance, Mapping):
        raise ValueError("affective runtime observation governance must be structured")
    receipt = snapshot.get("last_event_receipt")
    frame = _frame_from_observation(host, snapshot)
    vector = _control_vector_from_frame(frame)

    trust = _NO_PRODUCTION_AUTHORITY
    event_lineage = None
    if isinstance(receipt, Mapping):
        receipt_trust = receipt.get("authority_composition_trust")
        if receipt_trust == _UNROOTED:
            trust = _UNROOTED
        event_lineage = {
            "receipt_id": receipt.get("receipt_id"),
            "event_digest": receipt.get("event_digest"),
            "event_type": receipt.get("event_type"),
            "trigger_class": receipt.get("trigger_class"),
            "organic": receipt.get("organic"),
            "authority_composition_trust": receipt_trust,
        }

    binding = host.binding
    contract = host._runtime_contract_snapshot
    source_binding = {
        "source_repository": binding["source_repository"],
        "source_commit": binding["source_commit"],
        "source_path": binding["source_path"],
        "source_blob_sha": host.contract_blob_sha,
        "source_sha256": host.contract_sha256,
    }
    allowed = set(contract["hard_firewalls"]["may_influence"])

    signal: dict[str, Any] = {
        "schema": _SIGNAL_SCHEMA,
        "subject": "vera",
        "runtime_instance_id": snapshot["runtime_instance_id"],
        "source_binding": source_binding,
        "runtime_implementation_cut": host.runtime_implementation_cut,
        "presence": frame["presence"],
        "phase": frame["phase"],
        "context_eligible": bool(frame["context_eligible"]),
        "participating_systems": list(state["participating_systems"]),
        "action_tendency": frame["action_tendency"],
        "control_vector": vector,
        "target_modulation_strength": _target_strengths(allowed, frame, vector),
        "temporal_scope": {
            "logical_time_seconds": float(governance.get("logical_time_seconds", 0.0)),
            "persistence_window_ms": int(frame["persistence_window_ms"]),
            "currentness_class": "RUNTIME_LOCAL_OBSERVATION_ONLY",
        },
        "event_lineage": event_lineage,
        "authority_context_trust": trust,
        "provider_currentness": "UNRESOLVED",
        "durability": "NOT_QUALIFIED",
        "behavioral_qualification": "NOT_ESTABLISHED_BY_SIGNAL",
        "historical_engineered_event_claim_ceiling": contract["claim_ceiling"]["engineered_event"],
        "phenomenology": "UNRESOLVED",
        "usable_as_currentness_evidence": False,
        "evidence_effect": "NONE",
        "authorization_effect": "NONE",
        "memory_admission_effect": "NONE",
        "identity_effect": "NONE",
        "relationship_state_effect": "NONE",
    }
    signal["signal_digest"] = _digest(signal)
    return signal


def build_affective_modulation_signal(host: VeraAffectiveRuntimeHost) -> dict[str, Any]:
    """Build one diagnostic/internal signal from one coherent runtime observation."""
    runtime = _validated_signal_origin(host)
    observation = _capture_runtime_observation(host, runtime)
    return _build_affective_modulation_signal_from_observation(host, observation)


__all__ = ["build_affective_modulation_signal"]
