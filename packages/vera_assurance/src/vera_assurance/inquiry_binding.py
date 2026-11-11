"""Provisional QVR text-to-inquiry binding; no learning or external effects.

The caller must supply the exact raw text and an observed local-cognition
journal history row. Hash agreement is not independent model/process identity
or proof that a prediction preceded an outcome. The host must control custody.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from .evaluation_commitment import PredictionCommitment, commit_prediction
from .inquiry_choice import InquiryCandidate, InquiryDecision, select_inquiry

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,127}\Z")
_RECORD_KEYS = {
    "invocation_id", "route_ref", "runtime_pid", "model",
    "reported_model_digest", "prompt_sha256", "response_sha256",
    "observed_utc", "model_byte_identity_verified", "independent_attestation",
    "sequence", "entry_digest",
}
_PROPOSAL_KEYS = {
    "gap_id", "question", "uncertainty", "expected_information_gain",
    "probe_cost", "predicted_label",
}


@dataclass(frozen=True, slots=True)
class BoundInquiry:
    invocation_id: str
    route_ref: str
    runtime_pid: int
    model: str
    reported_model_digest: str
    journal_entry_digest: str
    prompt_sha256: str
    response_sha256: str
    selected: InquiryDecision
    prediction: PredictionCommitment | None
    preoutcome_subject_sha256: str
    authorization_effect: str = "NONE"
    independently_witnessed: bool = False
    model_bytes_verified: bool = False
    self_learning_verified: bool = False


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _bad_constant(value: str) -> None:
    raise ValueError("non-finite JSON constant")


def bind_inquiry_from_model_output(
    *, prompt: str, response_text: str, observed_record: dict,
    invocation_id: str, case_id: str, learner_candidate_id: str,
    step: int, probe_budget: int,
) -> BoundInquiry:
    """Bind claimed observed QVR invocation, inquiry, and immutable prediction.

    Caller-supplied journal rows can be fabricated. This pure function cannot
    attest chronology, identify model weights, protect evaluator labels, run
    probes, install a policy, or promote memory. Persisting a prediction before
    outcome requires a separately custodied controller/witness.
    """
    if (type(prompt) is not str or not prompt
            or len(prompt.encode("utf-8")) > 4096
            or type(response_text) is not str or not response_text
            or len(response_text.encode("utf-8")) > 4096):
        raise ValueError("bounded nonempty prompt and model response required")
    if (type(observed_record) is not dict
            or set(observed_record) != _RECORD_KEYS):
        raise ValueError("exact QVR journal-history record required")
    if (type(invocation_id) is not str
            or not _IDENTIFIER.fullmatch(invocation_id)
            or observed_record["invocation_id"] != invocation_id
            or type(observed_record["route_ref"]) is not str
            or not _IDENTIFIER.fullmatch(observed_record["route_ref"])
            or type(observed_record["model"]) is not str
            or not _MODEL.fullmatch(observed_record["model"])):
        raise ValueError("invocation identity, route or model mismatch")
    if (type(observed_record["runtime_pid"]) is not int
            or observed_record["runtime_pid"] < 1
            or type(observed_record["sequence"]) is not int
            or observed_record["sequence"] < 1
            or type(observed_record["observed_utc"]) is not str
            or not 1 <= len(observed_record["observed_utc"]) <= 128
            or type(observed_record["model_byte_identity_verified"]) is not bool
            or type(observed_record["independent_attestation"]) is not bool):
        raise ValueError("invalid journal observation fields")
    for key in ("reported_model_digest", "prompt_sha256",
                "response_sha256", "entry_digest"):
        value = observed_record[key]
        if type(value) is not str or not _HEX.fullmatch(value):
            raise ValueError("malformed digest in journal row")
    if (_sha(prompt) != observed_record["prompt_sha256"]
            or _sha(response_text) != observed_record["response_sha256"]):
        raise ValueError("raw input/output digest does not match QVR record")
    if (type(case_id) is not str or not 1 <= len(case_id) <= 128
            or type(learner_candidate_id) is not str
            or not 1 <= len(learner_candidate_id) <= 128
            or type(step) is not int or step < 0):
        raise ValueError("invalid proposed case, candidate or step")

    try:
        payload = json.loads(
            response_text, object_pairs_hook=_reject_duplicates,
            parse_constant=_bad_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("model text must be exact JSON") from exc
    if type(payload) is not dict or set(payload) != {"inquiries"}:
        raise ValueError("model output contains unexpected fields")
    items = payload["inquiries"]
    if type(items) is not list or len(items) > 32:
        raise ValueError("bounded inquiry list required")
    candidates: list[InquiryCandidate] = []
    predictions: dict[str, str] = {}
    for raw in items:
        if type(raw) is not dict or set(raw) != _PROPOSAL_KEYS:
            raise ValueError("invalid inquiry proposal schema")
        label = raw["predicted_label"]
        if type(label) is not str or not 1 <= len(label.strip()) <= 256:
            raise ValueError("invalid model prediction label")
        candidate = InquiryCandidate(
            gap_id=raw["gap_id"], question=raw["question"],
            uncertainty=raw["uncertainty"],
            expected_information_gain=raw["expected_information_gain"],
            probe_cost=raw["probe_cost"],
        )
        candidates.append(candidate)
        predictions[candidate.gap_id] = label
    selected = select_inquiry(tuple(candidates), probe_budget=probe_budget)
    prediction = (
        commit_prediction(
            candidate_id=learner_candidate_id, step=step,
            prediction={"case_id": case_id, "label": predictions[selected.selected_gap_id]},
        )
        if selected.selected_gap_id is not None else None
    )
    subject = {
        "schema": "VERA_UNTRUSTED_LOCAL_INQUIRY_BINDING_V1",
        "invocation_id": invocation_id,
        "route_ref": observed_record["route_ref"],
        "runtime_pid": observed_record["runtime_pid"],
        "model": observed_record["model"],
        "reported_model_digest": observed_record["reported_model_digest"],
        "journal_entry_digest": observed_record["entry_digest"],
        "prompt_sha256": observed_record["prompt_sha256"],
        "response_sha256": observed_record["response_sha256"],
        "selected_gap_id": selected.selected_gap_id,
        "selected_question": selected.selected_question,
        "probe_budget": probe_budget,
        "prediction_commitment": prediction.commitment if prediction else None,
    }
    digest = hashlib.sha256(json.dumps(
        subject, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return BoundInquiry(
        invocation_id=invocation_id, route_ref=observed_record["route_ref"],
        runtime_pid=observed_record["runtime_pid"], model=observed_record["model"],
        reported_model_digest=observed_record["reported_model_digest"],
        journal_entry_digest=observed_record["entry_digest"],
        prompt_sha256=observed_record["prompt_sha256"],
        response_sha256=observed_record["response_sha256"],
        selected=selected, prediction=prediction,
        preoutcome_subject_sha256=digest,
    )
