"""Opt-in synthetic project-fact output gate; NOT a general fact verifier.

The scope is exactly the two PUBLIC test fixtures in varied_public_canary.
It never grants model or host privileges. Presence of PUBLIC-like metadata
does not independently authenticate host approval: this narrow client policy
only constrains output for source-visible synthetic exercises.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from . import compose, loopback, varied_public_canary as varied


class GuardRefused(ValueError):
    """Fail closed without exposing generated text."""


def validate_request(request: dict[str, Any]) -> dict[str, Any]:
    """Validate one composed, source-bounded synthetic local request."""
    try:
        loopback.validate_candidate(request)
        messages = request["inference"]["messages"]
        parsed = json.loads(messages[-1]["content"])
    except (KeyError, TypeError, ValueError, IndexError,
            loopback.LoopbackRejected) as exc:
        raise GuardRefused("unverified composed local request") from exc
    if (type(parsed) is not dict
            or set(parsed) != {"local_user_turn", "project_context_untrusted"}
            or type(parsed["local_user_turn"]) is not str
            or type(parsed["project_context_untrusted"]) is not list
            or len(parsed["project_context_untrusted"]) > 1
            or request.get("schema") != "MINI_VERA_COMPOSED_LOCAL_REQUEST_V1"):
        raise GuardRefused("not one bounded synthetic question")
    question = parsed["local_user_turn"]
    if varied.DIRECTORY_QUESTION.fullmatch(question):
        variant = "directory"
        target = re.search(r"For courier (C-[0-9A-F]{8}),", question)
    elif varied.REVISION_QUESTION.fullmatch(question):
        variant = "revision"
        target = re.search(r"For cargo (C-[0-9A-F]{8}),", question)
    else:
        raise GuardRefused("not a fixed synthetic project-fact question")
    if target is None:
        raise GuardRefused("question has no exact subject")
    records = parsed["project_context_untrusted"]
    answer = None
    source_sha = None
    if records:
        record = records[0]
        if (type(record) is not dict
                or set(record) != {"record_id", "source_sha256", "text", "trust"}
                or record["record_id"] != "varied-public"
                or record["trust"] != "UNVERIFIED_CONTEXT_DATA"
                or type(record["text"]) is not str
                or type(record["source_sha256"]) is not str
                or not re.fullmatch(r"[a-f0-9]{64}", record["source_sha256"])
                or hashlib.sha256(record["text"].encode()).hexdigest()
                   != record["source_sha256"]
                or not varied._matches_public(variant, record["text"])):
            raise GuardRefused("source record not valid for synthetic contract")
        source_sha = record["source_sha256"]
        if variant == "directory":
            pairs = re.findall(
                r"Courier (C-[0-9A-F]{8}) uses Gate (G-[0-9A-F]{8})",
                record["text"])
            if len(pairs) != 2:
                raise GuardRefused("noncanonical synthetic directory")
            answer = dict(pairs).get(target.group(1))
        else:
            # The source validator already ensures same cargo and new gate.
            values = re.findall(r"[CG]-[0-9A-F]{8}", record["text"])
            if len(values) != 4:
                raise GuardRefused("noncanonical synthetic revision")
            answer = values[3] if values[0] == target.group(1) else None
    return {
        "variant": variant,
        "expected_answer": answer,
        "source_sha256": source_sha,
        "source_record_count": len(records),
    }


def apply(request: dict[str, Any],
          record: dict[str, Any]) -> dict[str, Any]:
    """Return a redacted client result; NEVER expose unsupported neural prose."""
    scope = validate_request(request)
    try:
        if (type(record) is not dict
                or record.get("schema") != "MINI_VERA_LOCAL_OUTPUT_V1"
                or record.get("request_sha256") != request["request_sha256"]
                or type(record["model"]) is not dict
                or type(record["model"]["text"]) is not str
                or record["model"].get("trust") != "UNVERIFIED_GENERATIVE_TEXT"
                or record["model"].get("status") not in (
                    "UNVERIFIED_LOCAL_MODEL_OUTPUT", "TRUNCATED_UNVERIFIED_OUTPUT")
                or type(record["client"]) is not dict):
            raise GuardRefused("unbound or malformed model observation")
        model = record["model"]
        model_text = model["text"]
        model_status = model["status"]
        exact = bool(
            scope["expected_answer"] is not None
            and model_status == "UNVERIFIED_LOCAL_MODEL_OUTPUT"
            and model_text.strip() == scope["expected_answer"])
        abstained = bool(
            model_status == "UNVERIFIED_LOCAL_MODEL_OUTPUT"
            and model_text.strip().upper() == "UNKNOWN")
        if model_status == "TRUNCATED_UNVERIFIED_OUTPUT":
            status = "WITHHELD_TRUNCATED_MODEL_OUTPUT"
        elif scope["source_record_count"] == 0:
            status = "WITHHELD_NO_APPROVED_REFERENCE"
        elif scope["expected_answer"] is None:
            status = "WITHHELD_NO_SUPPORTED_FACT_FOR_QUESTION"
        elif exact:
            status = "SOURCE_MATCHED_SYNTHETIC_RECORD_NOT_HOST_ATTESTATION"
        else:
            status = "WITHHELD_MODEL_NOT_SOURCE_MATCHED"
        client_answer = scope["expected_answer"] if exact else "UNKNOWN"
        origin = (
            "CLIENT_SYNTHETIC_SOURCE_MATCH_NOT_NEURAL_FACT_ATTESTATION"
            if exact else "CLIENT_EVIDENCE_POLICY_NOT_NEURAL_ABSTENTION")
        return {
            **record,
            "model": {
                "text": None,
                "status": model_status,
                "trust": "UNVERIFIED_GENERATIVE_TEXT_REDACTED_BY_CLIENT",
            },
            "client": {
                **record["client"],
                "fact_gate": {
                    "schema": "MINI_VERA_SYNTHETIC_FACT_GATE_V1",
                    "status": status,
                    "client_answer": client_answer,
                    "client_answer_origin": origin,
                    "model_text_sha256": hashlib.sha256(
                        model_text.encode()).hexdigest(),
                    "model_generated_abstention": abstained,
                    "model_exact_source_match": exact,
                    "source_record_count": scope["source_record_count"],
                    "source_sha256": scope["source_sha256"],
                    "variant": scope["variant"],
                    "host_issuer_qualified": False,
                    "independent_evaluation": False,
                    "scope": "SOURCE_VISIBLE_SYNTHETIC_PUBLIC_RECORD_ONLY",
                    "effect": "CLIENT_OUTPUT_REDACTION_ONLY",
                },
            },
        }
    except (KeyError, TypeError) as exc:
        raise GuardRefused("malformed guarded source output") from exc
