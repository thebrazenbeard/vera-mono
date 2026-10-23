"""Read-only local/terminal envelope pairing, never an independent verifier.

This stops accidental field substitution at the cross-branch consumer edge.
It deliberately never interprets self-reported gateway identity, signature,
measured usage or mutable local flags as proof. The separately administered
evaluator must verify signature and atomic claim custody on exact source.
"""
from __future__ import annotations

import re

_SHA = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset({
    "witness_kind", "gateway_id", "signature", "resource_usage",
    "reservation_id", "attestation_id", "invocation_id",
    "run_id", "arm", "challenge_id", "challenge_view_digest",
    "model_prompt_sha256", "model_response_sha256",
    "model_identity", "model_artifact_sha256",
    "dispatch_monotonic_ns", "response_monotonic_ns",
    "outcome_status",
})
_USAGE = frozenset({"input_tokens", "output_tokens", "wall_time_ms"})
_EQUAL = {
    "invocation_id": "invocation_id",
    "reservation_id": "reservation_id",
    "run_id": "run_id", "arm": "arm", "challenge_id": "challenge_id",
    "challenge_view_digest": "challenge_view_digest",
    "model_prompt_sha256": "prompt_sha256",
    "model_response_sha256": "response_sha256",
    "model_identity": "model",
}
_PENDING = (
    "EXTERNAL_SIGNATURE_AND_KEY_CUSTODY",
    "REMOTE_CLAIM_LEDGER_AND_GATEWAY_IDENTITY",
    "CLAIM_ID_NOT_IN_SIGNED_TERMINAL_SCHEMA",
    "MODEL_ARTIFACT_BYTES_NOT_LOCALLY_VERIFIED",
    "RESOURCE_USAGE_NOT_INDEPENDENTLY_MEASURED",
    "ACTUAL_LEARNER_SOLE_ROUTE_NEGATIVE_TEST",
    "FOUR_ARM_HELDOUT_AND_COLD_RESTART_LEARNING",
)


def pair_local_terminal(local: dict, terminal: dict) -> dict:
    """Check local equality only; result is *always unqualified*.

    A caller may have generated both inputs. No signature is verified here;
    the existence of a syntactically signed-looking terminal is not evidence.
    Return no receipt promotion, mutable state changes, or automatic retries.
    """
    if type(local) is not dict or type(terminal) is not dict:
        raise ValueError("both records must be exact dictionaries")
    if frozenset(terminal) != _FIELDS:
        raise ValueError("terminal envelope does not match independent evaluator schema")
    if local.get("status") != "COMPLETED":
        raise ValueError("local execution not durably completed")
    claim_id = local.get("claim_id")
    if type(claim_id) is not str or not claim_id.strip():
        raise ValueError("no local claim linkage")
    if terminal["outcome_status"] != "COMPLETED":
        raise ValueError("terminal outcome is not completed")
    if terminal["witness_kind"] != "independent_dispatch_gateway":
        raise ValueError("terminal witness type is unsupported")
    for key in ("gateway_id", "attestation_id", "signature"):
        if type(terminal[key]) is not str or not terminal[key].strip():
            raise ValueError("missing terminal field: " + key)
    for source, target in _EQUAL.items():
        if type(terminal[source]) is not str or terminal[source] != local.get(target):
            raise ValueError("terminal/local mismatch: " + source)
    for key in ("challenge_view_digest", "model_prompt_sha256",
                "model_response_sha256", "model_artifact_sha256"):
        value = terminal[key]
        if _SHA.fullmatch(value) is None:
            raise ValueError("invalid SHA-256 in terminal: " + key)
    start = terminal["dispatch_monotonic_ns"]
    end = terminal["response_monotonic_ns"]
    if (type(start) is not int or type(end) is not int
            or start < 0 or end <= start):
        raise ValueError("invalid terminal time ordering")
    usage = terminal["resource_usage"]
    if type(usage) is not dict or frozenset(usage) != _USAGE:
        raise ValueError("terminal resource usage schema mismatch")
    if any(type(usage[k]) is not int or usage[k] < 0 for k in _USAGE):
        raise ValueError("invalid resource usage value")
    if usage["wall_time_ms"] <= 0:
        raise ValueError("nonpositive wall-time report")
    # Deliberately NEVER read local.independent_attestation or trust signature
    # bytes without the actual independently configured verifier and its key.
    return {
        "status": "LOCAL_ENVELOPE_MATCH_UNVERIFIED",
        "qualified": False,
        "invocation_id": local["invocation_id"],
        "reservation_id": local["reservation_id"],
        "claim_id": claim_id,
        "gateway_signature_verified": False,
        "remote_claim_verified": False,
        "claim_id_cryptographically_bound": False,
        "model_artifact_verified": False,
        "resource_usage_independently_measured": False,
        "automatic_retry_permitted": False,
        "pending": list(_PENDING),
    }
