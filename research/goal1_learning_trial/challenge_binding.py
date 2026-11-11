"""No-effect join of a public evaluator challenge to claimed QVR model bytes.

This source-only binder validates consistent caller-supplied QVR history; it
does NOT authenticate model/host identity, pre-feedback order or label custody.
The independent evaluator must control challenge, dispatch and chronology.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from .revision_context import TrialPromptReceipt

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,127}\Z")
_RECORD_KEYS = frozenset({
    "invocation_id", "route_ref", "runtime_pid", "model",
    "reported_model_digest", "prompt_sha256", "response_sha256",
    "observed_utc", "model_byte_identity_verified",
    "independent_attestation", "sequence", "entry_digest",
})
_FROZEN_PREFIX = "Predict a label for this synthetic case using only its visible evidence. "
_REVISED_PREFIX = (
    _FROZEN_PREFIX
    + "A prior correction has provisionally supplied this rule; treat it as a testable "
    "hypothesis, not a guaranteed truth: "
)

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _strict_text(value: object, maximum: int) -> bool:
    return type(value) is str and 0 < len(value) <= maximum and all(
        32 <= ord(ch) <= 126 for ch in value
    )

def format_case_task(challenge_view: dict[str, str]) -> str:
    """A deterministic, exact-label-free public challenge rendering."""
    if (type(challenge_view) is not dict
            or set(challenge_view) != {"challenge_id", "features"}):
        raise ValueError("exact evaluator public case is required")
    cid = challenge_view["challenge_id"]
    features = challenge_view["features"]
    if (not _strict_text(cid, 100) or _ID.fullmatch(cid) is None
            or not _strict_text(features, 400)):
        raise ValueError("invalid public case identifier/features")
    return (f"Challenge id={cid}. Visible features: {features}. "
            "Return ONLY the literal token A, B, or ABSTAIN. No explanation or other text.")

@dataclass(frozen=True, slots=True)
class BoundTrialPrediction:
    challenge_id: str
    challenge_view_digest: str
    model_prompt_sha256: str
    model_response_sha256: str
    prediction: str
    arm: str
    revision_id: str | None
    invocation_id: str
    qvr_journal_entry_digest: str
    route_ref: str
    runtime_pid: int
    model: str
    registry_reported_model_digest: str
    subject_digest: str
    authorization_effect: str = "NONE"
    evidence_class: str = "CALLER_SUPPLIED_QVR_JOURNAL"
    independently_attested: bool = False
    model_bytes_verified: bool = False
    model_consumption_independently_verified: bool = False
    pre_feedback_order_verified: bool = False
    learning_verified: bool = False

def bind_observed_trial_prediction(
    *,
    challenge_view: dict[str, str],
    trial_prompt: TrialPromptReceipt,
    raw_model_response: str,
    observed_record: dict | None,
    arm: str,
    invocation_id: str,
) -> BoundTrialPrediction:
    """Validate congruent bytes; never treat hash agreement as attestation."""
    task = format_case_task(challenge_view)
    if type(trial_prompt) is not TrialPromptReceipt:
        raise ValueError("exact TrialPromptReceipt required")
    if trial_prompt.case_id != challenge_view["challenge_id"]:
        raise ValueError("case identity mismatch")
    if arm not in ("FROZEN", "LEARNED") or type(arm) is not str:
        raise ValueError("unsupported arm in this two-condition bridge")
    expected_condition = "FROZEN" if arm == "FROZEN" else "REVISED"
    if trial_prompt.condition != expected_condition:
        raise ValueError("arm/condition mismatch")
    if type(trial_prompt.prompt) is not str or not 1 <= len(trial_prompt.prompt.encode("utf-8")) <= 2048:
        raise ValueError("invalid bounded actual model prompt")
    if (type(trial_prompt.prompt_sha256) is not str
            or _HEX.fullmatch(trial_prompt.prompt_sha256) is None
            or _sha(trial_prompt.prompt) != trial_prompt.prompt_sha256):
        raise ValueError("actual model prompt digest mismatch")
    if arm == "FROZEN":
        if (trial_prompt.revision_id is not None
                or trial_prompt.prompt != _FROZEN_PREFIX + task):
            raise ValueError("frozen arm case/prompt/revision mismatch")
    else:
        if (type(trial_prompt.revision_id) is not str
                or _HEX.fullmatch(trial_prompt.revision_id) is None
                or not trial_prompt.review_evidence_ref
                or not trial_prompt.later_use_evidence_id):
            raise ValueError("revised arm revision identity is missing")
        if not (trial_prompt.prompt.startswith(_REVISED_PREFIX)
                and trial_prompt.prompt.endswith(" Case: " + task)):
            raise ValueError("revised arm case/prompt mismatch")
    if (type(raw_model_response) is not str
            or not 1 <= len(raw_model_response.encode("utf-8")) <= 256
            or raw_model_response.strip() not in ("A", "B", "ABSTAIN")):
        raise ValueError("model response must contain one exact prediction")
    if type(observed_record) is not dict or set(observed_record) != _RECORD_KEYS:
        raise ValueError("exact observed QVR journal entry required")
    if (type(invocation_id) is not str
            or _ID.fullmatch(invocation_id) is None
            or observed_record["invocation_id"] != invocation_id):
        raise ValueError("invocation mismatch")
    if (type(observed_record["route_ref"]) is not str
            or _ID.fullmatch(observed_record["route_ref"]) is None
            or type(observed_record["model"]) is not str
            or _MODEL.fullmatch(observed_record["model"]) is None
            or type(observed_record["runtime_pid"]) is not int
            or observed_record["runtime_pid"] < 1
            or type(observed_record["sequence"]) is not int
            or observed_record["sequence"] < 1
            or type(observed_record["observed_utc"]) is not str
            or not _strict_text(observed_record["observed_utc"], 128)
            or type(observed_record["independent_attestation"]) is not bool
            or type(observed_record["model_byte_identity_verified"]) is not bool):
        raise ValueError("malformed QVR journal observation")
    for key in ("entry_digest", "reported_model_digest",
                "prompt_sha256", "response_sha256"):
        val = observed_record[key]
        if type(val) is not str or _HEX.fullmatch(val) is None:
            raise ValueError("malformed QVR digest")
    if observed_record["prompt_sha256"] != trial_prompt.prompt_sha256:
        raise ValueError("journal prompt hash mismatch")
    response_sha = _sha(raw_model_response)
    if observed_record["response_sha256"] != response_sha:
        raise ValueError("journal response hash mismatch")
    view_sha = hashlib.sha256(json.dumps(
        challenge_view, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()).hexdigest()
    subject = {
        "schema": "VERA_GOAL1_QVR_TRIAL_BINDING_V1",
        "challenge_id": challenge_view["challenge_id"],
        "challenge_view_digest": view_sha,
        "model_prompt_sha256": trial_prompt.prompt_sha256,
        "model_response_sha256": response_sha,
        "prediction": raw_model_response.strip(), "arm": arm,
        "revision_id": trial_prompt.revision_id,
        "invocation_id": invocation_id,
        "qvr_journal_entry_digest": observed_record["entry_digest"],
        "route_ref": observed_record["route_ref"],
        "runtime_pid": observed_record["runtime_pid"],
        "model": observed_record["model"],
        "registry_reported_model_digest": observed_record["reported_model_digest"],
    }
    digest = hashlib.sha256(json.dumps(
        subject, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return BoundTrialPrediction(
        challenge_id=challenge_view["challenge_id"],
        challenge_view_digest=view_sha,
        model_prompt_sha256=trial_prompt.prompt_sha256,
        model_response_sha256=response_sha,
        prediction=raw_model_response.strip(), arm=arm,
        revision_id=trial_prompt.revision_id, invocation_id=invocation_id,
        qvr_journal_entry_digest=observed_record["entry_digest"],
        route_ref=observed_record["route_ref"],
        runtime_pid=observed_record["runtime_pid"],
        model=observed_record["model"],
        registry_reported_model_digest=observed_record["reported_model_digest"],
        subject_digest=digest,
    )


def controller_commit_parameters(binding: BoundTrialPrediction) -> dict[str, object]:
    """Untrusted, minimal candidate parameters for evaluator #87.

    This does not dispatch a model, reserve a transport attempt, release
    feedback, authenticate identity, or attest pre-feedback chronology.
    The separately controlled evaluator must validate the public challenge,
    uniqueness, sequencing, actual transport witness and feedback custody.
    budget_units=1 is a protocol counter, NOT measured model usage.
    """
    if type(binding) is not BoundTrialPrediction:
        raise ValueError("exact untrusted binding required")
    if (
        binding.authorization_effect != "NONE"
        or binding.independently_attested
        or binding.model_bytes_verified
        or binding.model_consumption_independently_verified
        or binding.pre_feedback_order_verified
        or binding.learning_verified
        or binding.evidence_class != "CALLER_SUPPLIED_QVR_JOURNAL"
    ):
        raise ValueError("cannot promote unsupported evidence claims")
    if (
        type(binding.challenge_id) is not str
        or _ID.fullmatch(binding.challenge_id) is None
        or binding.arm not in ("LEARNED", "FROZEN")
        or binding.prediction not in ("A", "B", "ABSTAIN")
    ):
        raise ValueError("invalid challenge arm or prediction")
    for digest in (
        binding.challenge_view_digest,
        binding.model_prompt_sha256,
        binding.model_response_sha256,
        binding.subject_digest,
    ):
        if type(digest) is not str or _HEX.fullmatch(digest) is None:
            raise ValueError("invalid binding digest")
    # Detect post-binding field edits, including a syntactically valid
    # substituted challenge-view hash. A fully rewritten/self-hashed object
    # can still be forged; this is integrity consistency, not attestation.
    subject = {
        "schema": "VERA_GOAL1_QVR_TRIAL_BINDING_V1",
        "challenge_id": binding.challenge_id,
        "challenge_view_digest": binding.challenge_view_digest,
        "model_prompt_sha256": binding.model_prompt_sha256,
        "model_response_sha256": binding.model_response_sha256,
        "prediction": binding.prediction,
        "arm": binding.arm,
        "revision_id": binding.revision_id,
        "invocation_id": binding.invocation_id,
        "qvr_journal_entry_digest": binding.qvr_journal_entry_digest,
        "route_ref": binding.route_ref,
        "runtime_pid": binding.runtime_pid,
        "model": binding.model,
        "registry_reported_model_digest": binding.registry_reported_model_digest,
    }
    computed = hashlib.sha256(json.dumps(
        subject, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    if computed != binding.subject_digest:
        raise ValueError("inconsistent untrusted subject digest")
    return {
        "arm": binding.arm,
        "challenge_id": binding.challenge_id,
        "prediction": binding.prediction,
        "challenge_view_digest": binding.challenge_view_digest,
        "model_prompt_sha256": binding.model_prompt_sha256,
        "model_response_sha256": binding.model_response_sha256,
        "budget_units": 1,
    }
