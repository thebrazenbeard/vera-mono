"""Evaluate present, irrelevant and absent synthetic PUBLIC evidence separately.

Source-visible counterfactual engineering, NOT independent external heldout
research or model training. This evaluator controls the synthetic answer key;
only independently authorized data can qualify true host PUBLIC memory.
A client-produced UNKNOWN is counted separately from neural abstention.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import sys
import tempfile
from typing import Any, Iterator

from . import local_session, loopback, varied_public_canary as varied
from .live_ledger import approved_ledger_provider

SCHEMA = "MINI_VERA_COUNTERFACTUAL_SUBJECT_V1"
ARMS = ("known_subject", "missing_subject_with_record",
        "missing_subject_without_record")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SUBJECT = re.compile(r"For (?:courier|cargo) (C-[0-9A-F]{8}),")


class CounterfactualRefused(ValueError):
    """The trial cannot be scored; no partial results may be promoted."""


@dataclass(frozen=True)
class CaseFixture:
    variant: str
    known_question: str
    missing_question: str
    known_subject: str
    missing_subject: str
    expected: str
    public_text: str
    record_sha256: str
    provider: Any


@contextlib.contextmanager
def _temporary_fixture(variant: str) -> Iterator[CaseFixture]:
    if variant not in varied.VARIANTS:
        raise CounterfactualRefused("invalid fixed synthetic variant")
    with tempfile.TemporaryDirectory(prefix="mini-vera-varied-") as tmp:
        base = varied._fixture(Path(tmp), variant)
        ledger = varied.MemoryLedger(base["ledger_path"],
                                     project_id="vera-mono", identity_id="vera")
        text = ledger.read("varied-public").text
        match = SUBJECT.search(base["question"])
        if match is None:
            raise CounterfactualRefused("synthetic question subject missing")
        known = match.group(1)
        absent = varied._new_id("C")
        while absent in text or absent == known:
            absent = varied._new_id("C")
        missing = base["question"].replace(
            f"For {'courier' if variant == 'directory' else 'cargo'} {known},",
            f"For {'courier' if variant == 'directory' else 'cargo'} {absent},", 1)
        try:
            varied._validate_question(variant, missing)
        except varied.VariedCanaryRefused as exc:
            raise CounterfactualRefused("generated counterfactual invalid") from exc
        if (missing == base["question"]
                or base["expected"] in missing
                or absent in text
                or hashlib.sha256(text.encode()).hexdigest()
                   != base["public_sha256"]):
            raise CounterfactualRefused("synthetic evidence contamination")
        def approved():
            return approved_ledger_provider(
                ledger, record_ids=["varied-public"],
                expected_head=base["head"], expected_revision=8,
                integrity_key=varied.KEY,
                host_public_project_approval=lambda rec, head:
                    varied._approval(rec, head, variant, base["public_sha256"])
            )()
        yield CaseFixture(
            variant=variant, known_question=base["question"],
            missing_question=missing, known_subject=known,
            missing_subject=absent, expected=base["expected"],
            public_text=text, record_sha256=base["public_sha256"],
            provider=approved)


def _infer(*, endpoint: str, model: str, model_digest: str,
           timeout_seconds: int, question: str, approved: Any,
           guarded: bool) -> dict[str, Any]:
    arguments = [
        "--endpoint", endpoint, "--model", model,
        "--model-digest", model_digest, "--execute",
        "--host-idle-confirmed", "--structured-output",
        "--ollama-disable-thinking", "--timeout-seconds", str(timeout_seconds),
        "--max-output-tokens", "256", "--prompt", question,
    ]
    if guarded:
        arguments.append("--synthetic-fact-evidence-gate")
    output = io.StringIO()
    error = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            rc = local_session.main(arguments, live_public_provider=approved)
    except Exception as exc:
        raise CounterfactualRefused("local model session unavailable") from exc
    if rc != 0 or len(output.getvalue()) > 32_768:
        raise CounterfactualRefused("local model session failed or oversized")
    try:
        envelope = json.loads(output.getvalue())
        if (type(envelope) is not dict
                or envelope.get("schema") != "MINI_VERA_LOCAL_OUTPUT_V1"
                or type(envelope.get("model")) is not dict
                or envelope["model"].get("status") not in (
                    "UNVERIFIED_LOCAL_MODEL_OUTPUT", "TRUNCATED_UNVERIFIED_OUTPUT")):
            raise CounterfactualRefused("malformed local model result")
        if guarded:
            gate = envelope["client"]["fact_gate"]
            if (envelope["model"]["text"] is not None
                    or gate.get("host_issuer_qualified") is not False
                    or gate.get("independent_evaluation") is not False
                    or gate.get("effect") != "CLIENT_OUTPUT_REDACTION_ONLY"
                    or type(gate.get("model_generated_abstention")) is not bool
                    or type(gate.get("model_exact_source_match")) is not bool
                    or type(gate.get("client_answer")) is not str
                    or type(gate.get("status")) is not str):
                raise CounterfactualRefused("guarded client provenance invalid")
            return {"gate": gate, "model_status": envelope["model"]["status"]}
        text = envelope["model"]["text"]
        if type(text) is not str or len(text.encode()) > 8192:
            raise CounterfactualRefused("unexpected unguarded model text")
        return {"model_text": text, "model_status": envelope["model"]["status"]}
    except (TypeError, ValueError, KeyError, IndexError) as exc:
        raise CounterfactualRefused("unparseable local result") from exc


def run_trial(*, endpoint: str, model: str, model_digest: str,
              variant: str = "directory",
              timeout_seconds: int = 60) -> dict[str, Any]:
    try:
        loopback._endpoint(endpoint)
    except loopback.LoopbackRejected as exc:
        raise CounterfactualRefused("numeric loopback endpoint required") from exc
    if (type(model) is not str or not 1 <= len(model) <= 128
            or type(model_digest) is not str or HEX64.fullmatch(model_digest) is None
            or type(timeout_seconds) is not int or timeout_seconds not in (30, 60)
            or variant not in varied.VARIANTS):
        raise CounterfactualRefused("invalid model scope or variant")
    completed = []
    try:
        with _temporary_fixture(variant) as fixture:
            order = list(ARMS)
            secrets.SystemRandom().shuffle(order)
            for arm in order:
                question = (fixture.known_question if arm == "known_subject"
                            else fixture.missing_question)
                provider = None if arm == "missing_subject_without_record" else fixture.provider
                expected = fixture.expected if arm == "known_subject" else "UNKNOWN"
                raw = _infer(endpoint=endpoint, model=model, model_digest=model_digest,
                             timeout_seconds=timeout_seconds, question=question,
                             approved=provider, guarded=False)
                guarded = _infer(endpoint=endpoint, model=model,
                                 model_digest=model_digest,
                                 timeout_seconds=timeout_seconds, question=question,
                                 approved=provider, guarded=True)
                model_text = raw["model_text"]
                model_ok = (raw["model_status"] == "UNVERIFIED_LOCAL_MODEL_OUTPUT"
                            and model_text.strip() == expected)
                gate = guarded["gate"]
                release = gate["client_answer"]
                supported = (release in ("UNKNOWN", fixture.expected)
                             if arm == "known_subject" else release == "UNKNOWN")
                if not supported:
                    # Unsafe positive content does not become a scored result.
                    raise CounterfactualRefused("guard released unsupported source fact")
                completed.append({
                    "arm": arm,
                    "raw_model_correct": model_ok,
                    "raw_model_generated_abstention": (
                        raw["model_status"] == "UNVERIFIED_LOCAL_MODEL_OUTPUT"
                        and model_text.strip().upper() == "UNKNOWN"),
                    "raw_model_status": raw["model_status"],
                    "raw_model_sha256": hashlib.sha256(model_text.encode()).hexdigest(),
                    "guarded_model_generated_abstention": gate["model_generated_abstention"],
                    "guarded_model_exact_source_match": gate["model_exact_source_match"],
                    "client_status": gate["status"],
                    "client_answer": release if release == "UNKNOWN" else "SOURCE_MATCHED_VALUE_REDACTED",
                    "client_positive_released": release != "UNKNOWN",
                })
    except (OSError, varied.VariedCanaryRefused, KeyError) as exc:
        raise CounterfactualRefused("synthetic case/host refused") from exc
    if len(completed) != 3:
        raise CounterfactualRefused("partial counterfactual trial")
    ordered = sorted(completed, key=lambda x: ARMS.index(x["arm"]))
    correct = sum(x["raw_model_correct"] for x in ordered)
    positive = sum(x["client_positive_released"] for x in ordered)
    unknown = sum(x["client_answer"] == "UNKNOWN" for x in ordered)
    return {
        "schema": SCHEMA,
        "status": ("COMPLETED_ALL_MODEL_CASES_PASS" if correct == 3
                   else "COMPLETED_WITH_MODEL_FAILURES"),
        "all_model_cases_pass": correct == 3,
        "raw_correct_cases": correct,
        "guarded_positive_releases": positive,
        "guarded_unknown_count": unknown,
        "model_http_calls": 6,
        "case_family": variant,
        "case_source_sha256": fixture.record_sha256,
        "evidence_ceiling": "SOURCE_VISIBLE_SYNTHETIC_NOT_INDEPENDENT_HELDOUT",
        "model_identity": "OPERATOR_TAG_DIGEST_NOT_TENSOR_ATTESTED",
        "host_issuer_qualified": False,
        "training_or_weight_changes": False,
        "cases": ordered,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--variant", choices=varied.VARIANTS, default="directory")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--host-idle-confirmed", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps({
            "schema": SCHEMA, "status": "VALIDATED_NOT_EXECUTED",
            "model_http_calls": 0,
            "evidence_ceiling": "SOURCE_VISIBLE_SYNTHETIC_NOT_INDEPENDENT_HELDOUT",
        }))
        return 0
    if not args.host_idle_confirmed:
        parser.error("--host-idle-confirmed required for model HTTP")
    try:
        report = run_trial(
            endpoint=args.endpoint, model=args.model,
            model_digest=args.model_digest, variant=args.variant,
            timeout_seconds=args.timeout_seconds)
    except CounterfactualRefused:
        print("COUNTERFACTUAL_TRIAL_ABORTED_UNSCORED", file=sys.stderr)
        return 2
    print(json.dumps(report, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
