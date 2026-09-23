import hashlib
import json
import re


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ProjectRunnerProofError(ValueError):
    pass


def _canonical_digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_exact_fields(value, fields, label):
    if not isinstance(value, dict):
        raise ProjectRunnerProofError(f"{label} must be an object")
    expected = set(fields)
    actual = set(value)
    if actual != expected:
        raise ProjectRunnerProofError(
            f"{label} fields mismatch: missing={sorted(expected - actual)} "
            f"extra={sorted(actual - expected)}"
        )


def _require_nonempty_string(value, label):
    if not isinstance(value, str) or not value:
        raise ProjectRunnerProofError(f"{label} must be a nonempty string")


def _require_sha256(value, label):
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ProjectRunnerProofError(f"{label} must be lowercase SHA-256 hex")


def _require_position(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProjectRunnerProofError(
            f"{label} must be a nonnegative integer and not a boolean"
        )


def validate_currentness_exhaustion_receipt(receipt, primitive):
    _require_exact_fields(receipt, primitive["required_fields"], "currentness receipt")

    for field in (
        "inventory_owner_subject",
        "inventory_artifact_subject",
        "inventory_revision",
        "observed_at",
        "claim_ceiling",
    ):
        _require_nonempty_string(receipt[field], field)

    if receipt["claim_ceiling"] not in primitive["claim_ceiling_domain"]:
        raise ProjectRunnerProofError("claim_ceiling is outside the exact allowed domain")

    required_ids = receipt["required_surface_ids"]
    if not isinstance(required_ids, list) or any(
        not isinstance(surface_id, str) or not surface_id for surface_id in required_ids
    ):
        raise ProjectRunnerProofError("required_surface_ids must be a string array")
    if required_ids != sorted(required_ids):
        raise ProjectRunnerProofError("required_surface_ids must be lexicographically sorted")
    if len(required_ids) != len(set(required_ids)):
        raise ProjectRunnerProofError("required_surface_ids must be unique")

    expected_inventory_digest = _canonical_digest(
        {
            "inventory_owner_subject": receipt["inventory_owner_subject"],
            "inventory_artifact_subject": receipt["inventory_artifact_subject"],
            "inventory_revision": receipt["inventory_revision"],
            "required_surface_ids": required_ids,
        }
    )
    if receipt["required_surface_inventory_digest"] != expected_inventory_digest:
        raise ProjectRunnerProofError("required_surface_inventory_digest mismatch")

    surface_receipts = receipt["surface_receipts"]
    if not isinstance(surface_receipts, list):
        raise ProjectRunnerProofError("surface_receipts must be an array")

    seen = []
    all_complete = True
    for index, surface in enumerate(surface_receipts):
        _require_exact_fields(
            surface,
            primitive["surface_receipt_exact_fields"],
            f"surface_receipts[{index}]",
        )
        surface_id = surface["surface_id"]
        _require_nonempty_string(surface_id, f"surface_receipts[{index}].surface_id")
        for field in (
            "query_or_scope",
            "observed_generation_or_head",
            "frontier_or_pagination_state",
            "result_digest",
        ):
            _require_nonempty_string(surface[field], f"surface_receipts[{index}].{field}")
        if isinstance(surface["result_count"], bool) or not isinstance(surface["result_count"], int) or surface["result_count"] < 0:
            raise ProjectRunnerProofError(
                f"surface_receipts[{index}].result_count must be a nonnegative integer"
            )
        if surface["status"] not in primitive["allowed_statuses"]:
            raise ProjectRunnerProofError(
                f"surface_receipts[{index}].status is outside the allowed domain"
            )
        seen.append(surface_id)
        all_complete = all_complete and surface["status"] == "COMPLETE"

    if len(seen) != len(set(seen)):
        raise ProjectRunnerProofError("duplicate surface receipt")
    if set(seen) != set(required_ids):
        missing = sorted(set(required_ids) - set(seen))
        foreign = sorted(set(seen) - set(required_ids))
        raise ProjectRunnerProofError(
            f"surface coverage mismatch: missing={missing} foreign={foreign}"
        )

    derived = "COMPLETE" if all_complete else "PARTIAL"
    if receipt["overall_completeness"] != derived:
        raise ProjectRunnerProofError(
            f"overall_completeness must be derived as {derived}"
        )
    return derived


def validate_prospective_freeze_receipt(receipt, primitive):
    _require_exact_fields(receipt, primitive["required_fields"], "freeze receipt")

    for field in (
        "frozen_subject",
        "freeze_artifact_subject",
        "freeze_observed_at",
        "outcome_visibility_frontier",
        "execution_frontier",
        "holdout_or_randomization_commitment",
        "chronology_domain_subject",
    ):
        _require_nonempty_string(receipt[field], field)
    _require_sha256(receipt["freeze_artifact_digest"], "freeze_artifact_digest")

    anchors = {}
    for name in ("freeze_anchor", "outcome_visibility_anchor", "execution_anchor"):
        anchor = receipt[name]
        _require_exact_fields(anchor, primitive["chronology_anchor_exact_fields"], name)
        _require_nonempty_string(anchor["chronology_domain_subject"], f"{name}.chronology_domain_subject")
        _require_nonempty_string(anchor["evidence_subject"], f"{name}.evidence_subject")
        _require_sha256(anchor["evidence_digest"], f"{name}.evidence_digest")
        _require_position(anchor["monotonic_position"], f"{name}.monotonic_position")
        if anchor["chronology_domain_subject"] != receipt["chronology_domain_subject"]:
            raise ProjectRunnerProofError(f"{name} chronology domain mismatch")
        anchors[name] = anchor

    if anchors["freeze_anchor"]["evidence_subject"] != receipt["freeze_artifact_subject"]:
        raise ProjectRunnerProofError("freeze anchor subject mismatch")
    if anchors["freeze_anchor"]["evidence_digest"] != receipt["freeze_artifact_digest"]:
        raise ProjectRunnerProofError("freeze anchor digest mismatch")
    if anchors["outcome_visibility_anchor"]["evidence_subject"] != receipt["outcome_visibility_frontier"]:
        raise ProjectRunnerProofError("outcome anchor subject mismatch")
    if anchors["execution_anchor"]["evidence_subject"] != receipt["execution_frontier"]:
        raise ProjectRunnerProofError("execution anchor subject mismatch")

    proof_payload = {
        "frozen_subject": receipt["frozen_subject"],
        "freeze_artifact_subject": receipt["freeze_artifact_subject"],
        "freeze_artifact_digest": receipt["freeze_artifact_digest"],
        "freeze_observed_at": receipt["freeze_observed_at"],
        "holdout_or_randomization_commitment": receipt["holdout_or_randomization_commitment"],
        "chronology_domain_subject": receipt["chronology_domain_subject"],
        "freeze_anchor": anchors["freeze_anchor"],
        "outcome_visibility_anchor": anchors["outcome_visibility_anchor"],
        "execution_anchor": anchors["execution_anchor"],
    }
    expected_proof_digest = _canonical_digest(proof_payload)
    if receipt["chronology_proof_digest"] != expected_proof_digest:
        raise ProjectRunnerProofError("chronology_proof_digest mismatch")

    freeze_position = anchors["freeze_anchor"]["monotonic_position"]
    outcome_position = anchors["outcome_visibility_anchor"]["monotonic_position"]
    execution_position = anchors["execution_anchor"]["monotonic_position"]
    relation_holds = (
        freeze_position < outcome_position and freeze_position < execution_position
    )
    derived = (
        "PROSPECTIVE_VERIFIED_BY_BOUND_CHRONOLOGY"
        if relation_holds
        else "UNPROVEN"
    )
    if receipt["chronology_status"] != derived:
        raise ProjectRunnerProofError(f"chronology_status must be derived as {derived}")
    return derived
