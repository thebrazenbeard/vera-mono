"""Offline, external-custody Mini-Vera case scheduling and paired human analysis.

No teacher completions, model requests, generated gold answers, evaluator
cases, or automatic semantic scores are created. Human authorship, rater
independence, withheld custody, and actual resident weights cannot be proven
by these operator-supplied self-consistency checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
from typing import Any

if __package__:
    from . import blind_compare, loopback, withheld_dialogue
else:
    import blind_compare
    import loopback
    import withheld_dialogue


ROOT = Path(__file__).resolve().parents[2]
MAX_MANIFEST_BYTES = 65_536
MAX_RATING_BYTES = 16_384
MAX_TRIAL_BYTES = 262_144
DIMENSIONS = ("overall", "natural_voice", "calibration", "grounding",
              "correction_handling", "within_session_coherence")
ARM_NAMES = {"bare_natural", "minimal_natural", "governed_natural"}


def _external(path: Path) -> Path:
    path = path.resolve()
    if path.is_relative_to(ROOT):
        raise loopback.LoopbackRejected("withheld materials must not be stored in source repository")
    return path


def _read(path: Path, maximum: int) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > maximum:
        raise loopback.LoopbackRejected("missing or oversized external evaluation file")
    raw = path.read_bytes()
    if len(raw) > maximum:
        raise loopback.LoopbackRejected("oversized external evaluation file")
    return loopback._parse_object(raw)


def _hex64(value: Any) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise loopback.LoopbackRejected("invalid SHA-256 digest")
    return value


def prepare_schedule(manifest: dict[str, Any], *, secret_seed: bytes) -> dict[str, Any]:
    """Read the external human-authored cases, emit *no case text*."""
    if type(secret_seed) is not bytes or len(secret_seed) != 32:
        raise loopback.LoopbackRejected("independent secret shuffle seed must be 32 bytes")
    if type(manifest) is not dict or set(manifest) != {"schema", "cases"} or \
            manifest["schema"] != "MINI_VERA_EXTERNAL_CASE_LIST_V1":
        raise loopback.LoopbackRejected("invalid external case list")
    rows = manifest["cases"]
    if type(rows) is not list or not 1 <= len(rows) <= 100:
        raise loopback.LoopbackRejected("case list must contain 1..100 cases")
    prepared = []
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != {"case_id", "scenario_path"}:
            raise loopback.LoopbackRejected("invalid external case locator")
        if type(row["scenario_path"]) is not str or not row["scenario_path"]:
            raise loopback.LoopbackRejected("scenario path required")
        scenario = withheld_dialogue.load_scenario(_external(Path(row["scenario_path"])))
        case_id = scenario["case_id"]
        if row["case_id"] != case_id or case_id in seen:
            raise loopback.LoopbackRejected("duplicate or mismatched case ID")
        seen.add(case_id)
        digest = loopback.sha256(loopback.canonical(scenario))
        shuffle_key = hashlib.sha256(secret_seed + loopback.canonical([case_id, digest])).digest()
        prepared.append((shuffle_key, {"case_id": case_id, "case_sha256": digest}))
    prepared.sort(key=lambda item: item[0])
    return {
        "schema": "MINI_VERA_PRIVATE_CASE_SCHEDULE_V1",
        "secret_seed_commitment_sha256": loopback.sha256(secret_seed),
        "cases_in_randomized_order": [row for _, row in prepared],
        "rights": "HUMAN_AUTHORSHIP_AND_INDEPENDENCE_OPERATOR_ASSERTED_NOT_ATTESTED",
        "prohibited_use": "MODEL_TRAINING_OR_STUDENT_PROMPT_DISCLOSURE",
    }


def _check_ratings(value: dict[str, Any], *, case_id: str, trial_id: str) -> tuple[str, dict[str, dict[str, int]]]:
    if (type(value) is not dict or set(value) != {
            "schema", "case_id", "trial_id", "rater_id", "attestation", "scores_by_label"
        } or value["schema"] != "MINI_VERA_EXTERNAL_HUMAN_RATING_V1"
            or value["case_id"] != case_id or value["trial_id"] != trial_id
            or value["attestation"] != {
                "human_authored": "OPERATOR_ASSERTED_NOT_ATTESTED",
                "mapping_unseen_until_scoring_finished": "OPERATOR_ASSERTED_NOT_ATTESTED",
                "training_use": "PROHIBITED",
            }):
        raise loopback.LoopbackRejected("invalid human rating envelope")
    rater = value["rater_id"]
    if type(rater) is not str or not 1 <= len(rater) <= 80 or not rater.isascii():
        raise loopback.LoopbackRejected("invalid rater pseudonym")
    scores = value["scores_by_label"]
    if type(scores) is not dict or set(scores) != {"A", "B", "C"}:
        raise loopback.LoopbackRejected("all three blind labels must be rated")
    for item in scores.values():
        if type(item) is not dict or set(item) != set(DIMENSIONS):
            raise loopback.LoopbackRejected("all preregistered human dimensions required")
        if any(type(number) is not int or number < 0 or number > 4 for number in item.values()):
            raise loopback.LoopbackRejected("human ratings must be integer 0..4")
    return rater, scores


def _check_complete_transcript(sheet: dict[str, Any], key: dict[str, Any]) -> int:
    turns = sheet.get("turn_kinds")
    transcripts = sheet.get("transcripts_by_masked_label")
    call_order = key.get("call_order_by_turn")
    hashes = key.get("sent_payload_hashes_by_label")
    timings = key.get("latency_ms_by_label")
    if (type(turns) is not list or not 2 <= len(turns) <= 3
            or turns[0] != "query" or "correction" not in turns[1:]
            or type(transcripts) is not dict or set(transcripts) != {"A", "B", "C"}
            or type(call_order) is not list or len(call_order) != len(turns)
            or any(type(order) is not list or set(order) != {"A", "B", "C"}
                   or len(order) != 3 for order in call_order)
            or type(hashes) is not dict or set(hashes) != {"A", "B", "C"}
            or type(timings) is not dict or set(timings) != {"A", "B", "C"}):
        raise loopback.LoopbackRejected("incomplete masked dialogue transcript")
    for label in ("A", "B", "C"):
        items = transcripts[label]
        raw_hashes = hashes[label]
        raw_times = timings[label]
        if (type(items) is not list or len(items) != len(turns)
                or type(raw_hashes) is not list or len(raw_hashes) != len(turns)
                or type(raw_times) is not list or len(raw_times) != len(turns)):
            raise loopback.LoopbackRejected("dialogue length mismatch")
        for index, item in enumerate(items):
            if (type(item) is not dict or item.get("turn") != str(index + 1)
                    or item.get("finish_reason") != "stop"
                    or type(item.get("answer")) is not str
                    or item.get("answer_sha256") != loopback.sha256(item["answer"].encode("utf-8"))):
                raise loopback.LoopbackRejected("invalid/truncated transcript turn")
            _hex64(raw_hashes[index])
            latency = raw_times[index]
            if type(latency) not in {int, float} or not math.isfinite(latency) or latency < 0:
                raise loopback.LoopbackRejected("invalid latency receipt")
    return len(turns)


def _bootstrap(values: list[float], *, seed: bytes) -> list[float] | None:
    if len(values) < 5:
        return None
    generator = random.Random(int.from_bytes(hashlib.sha256(seed).digest(), "big"))
    n = len(values)
    samples = sorted(sum(values[generator.randrange(n)] for _ in range(n)) / n
                     for _ in range(3000))
    return [round(samples[74], 4), round(samples[2924], 4)]


def aggregate(schedule: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    if (type(schedule) is not dict
            or schedule.get("schema") != "MINI_VERA_PRIVATE_CASE_SCHEDULE_V1"
            or type(schedule.get("cases_in_randomized_order")) is not list):
        raise loopback.LoopbackRejected("invalid private schedule")
    scheduled = schedule["cases_in_randomized_order"]
    if not 1 <= len(scheduled) <= 100:
        raise loopback.LoopbackRejected("invalid schedule length")
    scheduled_by_id = {}
    for row in scheduled:
        if type(row) is not dict or set(row) != {"case_id", "case_sha256"}:
            raise loopback.LoopbackRejected("invalid schedule case")
        _hex64(row["case_sha256"])
        if row["case_id"] in scheduled_by_id:
            raise loopback.LoopbackRejected("duplicate scheduled case")
        scheduled_by_id[row["case_id"]] = row
    if (type(ledger) is not dict or set(ledger) != {"schema", "schedule_sha256", "cases"}
            or ledger["schema"] != "MINI_VERA_EXTERNAL_RESULT_LEDGER_V1"
            or ledger["schedule_sha256"] != loopback.sha256(loopback.canonical(schedule))
            or type(ledger["cases"]) is not list
            or len(ledger["cases"]) != len(scheduled)):
        raise loopback.LoopbackRejected("result ledger does not bind exact schedule")
    results = {}
    for row in ledger["cases"]:
        if type(row) is not dict or row.get("case_id") not in scheduled_by_id:
            raise loopback.LoopbackRejected("unknown result case")
        case_id = row["case_id"]
        if case_id in results:
            raise loopback.LoopbackRejected("duplicate result case")
        results[case_id] = row
    if set(results) != set(scheduled_by_id):
        raise loopback.LoopbackRejected("omitted scheduled case")

    counts = {"scheduled": len(scheduled), "attempted": 0, "completed": 0,
              "aborted": 0, "not_attempted": 0, "fully_human_rated": 0}
    paired = {"governed_minus_bare": [], "governed_minus_minimal": []}
    models = set()
    model_registry_digests = set()
    rating_hashes = {}
    for case_id, row in results.items():
        status = row.get("status")
        if status == "NOT_ATTEMPTED" and set(row) == {"case_id", "status"}:
            counts["not_attempted"] += 1
            continue
        if status == "ABORTED" and set(row) == {"case_id", "status", "private_receipt_path"}:
            receipt = _read(_external(Path(row["private_receipt_path"])), MAX_TRIAL_BYTES)
            if (receipt.get("schema") != "MINI_VERA_ABORTED_DIALOGUE_V1"
                    or receipt.get("status") != "INCOMPLETE_NOT_BEHAVIORALLY_QUALIFIED"
                    or receipt.get("case_id") != case_id
                    or receipt.get("case_sha256") != scheduled_by_id[case_id]["case_sha256"]
                    or type(receipt.get("calls_attempted_observed")) is not int
                    or receipt["calls_attempted_observed"] < 1):
                raise loopback.LoopbackRejected("invalid aborted-case receipt")
            counts["attempted"] += 1
            counts["aborted"] += 1
            continue
        if status != "COMPLETED" or set(row) != {
                "case_id", "status", "private_key_path", "private_key_sha256",
                "rater_sheet_path", "ratings"}:
            raise loopback.LoopbackRejected("invalid case outcome or missing attempt receipt")
        key = _read(_external(Path(row["private_key_path"])), MAX_TRIAL_BYTES)
        if loopback.sha256(loopback.canonical(key)) != _hex64(row["private_key_sha256"]):
            raise loopback.LoopbackRejected("private arm mapping/key drift after commitment")
        sheet = _read(_external(Path(row["rater_sheet_path"])), MAX_TRIAL_BYTES)
        if (key.get("schema") != "MINI_VERA_NATURAL_DIALOGUE_PRIVATE_KEY_V1"
                or sheet.get("schema") != "MINI_VERA_NATURAL_DIALOGUE_MASKED_V1"
                or sheet.get("case_id") != case_id
                or key.get("case_sha256") != scheduled_by_id[case_id]["case_sha256"]
                or key.get("trial_id") != sheet.get("trial_id")
                or key.get("rater_sheet_sha256") != loopback.sha256(loopback.canonical(sheet))
                or key.get("decoding") != blind_compare.DECODING
                or key.get("evidence", {}).get("input_control") !=
                "SAME_HUMAN_TURNS_AND_RECORDS_DIFFERENT_SYSTEM_CONTEXT"
                or sheet.get("status") != "UNVERIFIED_LOCAL_OUTPUT_NOT_HUMAN_RATED"
                or sheet.get("qualification") != "NOT_ESTABLISHED"):
            raise loopback.LoopbackRejected("invalid completed trial/source control binding")
        turn_count = _check_complete_transcript(sheet, key)
        if key.get("evidence", {}).get("calls") != 3 * turn_count:
            raise loopback.LoopbackRejected("declared call count mismatch")
        mapping = key.get("arm_by_label")
        if type(mapping) is not dict or set(mapping) != {"A", "B", "C"} or set(mapping.values()) != ARM_NAMES:
            raise loopback.LoopbackRejected("incomplete/blown blind mapping")
        if type(key.get("model_operator_declared")) is not str:
            raise loopback.LoopbackRejected("model identity declaration missing")
        models.add(key["model_operator_declared"])
        model_registry_digests.add(_hex64(key.get("model_registry_digest_operator_declared")))
        ratings = row["ratings"]
        if type(ratings) is not list or not 1 <= len(ratings) <= 8:
            raise loopback.LoopbackRejected("at least one independent human rating required")
        raters = set()
        by_arm = {arm: [] for arm in ARM_NAMES}
        receipt_hashes = []
        # Bind ratings BEFORE touching the private mapping's score semantics.
        for rating_ref in ratings:
            if type(rating_ref) is not dict or set(rating_ref) != {"path", "sha256"}:
                raise loopback.LoopbackRejected("rating precommit reference required")
            rating = _read(_external(Path(rating_ref["path"])), MAX_RATING_BYTES)
            sha = loopback.sha256(loopback.canonical(rating))
            if sha != _hex64(rating_ref["sha256"]):
                raise loopback.LoopbackRejected("human rating hash drift")
            rater, scores = _check_ratings(rating, case_id=case_id, trial_id=key["trial_id"])
            if rater in raters:
                raise loopback.LoopbackRejected("duplicate human rater")
            raters.add(rater)
            receipt_hashes.append(sha)
            for label, dimensions in scores.items():
                by_arm[mapping[label]].append(dimensions["overall"])
        rating_hashes[case_id] = receipt_hashes
        means = {arm: sum(values) / len(values) for arm, values in by_arm.items()}
        paired["governed_minus_bare"].append(means["governed_natural"] - means["bare_natural"])
        paired["governed_minus_minimal"].append(means["governed_natural"] - means["minimal_natural"])
        counts["attempted"] += 1
        counts["completed"] += 1
        counts["fully_human_rated"] += 1
    if len(models) > 1:
        raise loopback.LoopbackRejected("completed cases declare different model aliases")
    if len(model_registry_digests) > 1:
        raise loopback.LoopbackRejected("completed cases declare different model source digests")
    seed = loopback.canonical(schedule)
    pairwise = {}
    for name, values in paired.items():
        pairwise[name] = {"paired_cases": len(values),
                          "mean_case_delta_0_to_4": round(sum(values) / len(values), 4)
                          if values else None,
                          "case_bootstrap_95_percentile_ci": _bootstrap(values, seed=seed + name.encode()),
                          "interval_scope": "DESCRIPTIVE_CONDITIONAL_ON_COMPLETED_HUMAN_RATED_CASES"}
    return {
        "schema": "MINI_VERA_EXTERNAL_HUMAN_QUALIFICATION_SUMMARY_V1",
        "status": "DESCRIPTIVE_HUMAN_RATING_AGGREGATION_NOT_BEHAVIORAL_QUALIFICATION",
        "schedule_sha256": loopback.sha256(seed),
        "ledger_sha256": loopback.sha256(loopback.canonical(ledger)),
        "model_alias_operator_declared": next(iter(models)) if models else None,
        "model_registry_digest_operator_declared": next(iter(model_registry_digests))
        if model_registry_digests else None,
        "denominator": counts,
        "completion_rate_among_attempted": round(counts["completed"] / counts["attempted"], 4)
        if counts["attempted"] else None,
        "pairwise": pairwise,
        "rating_hashes_by_case_private": rating_hashes,
        "limits": [
            "RATER_RIGHTS_AND_BLINDNESS_OPERATOR_ASSERTED_NOT_ATTESTED",
            "INDEPENDENCE_AND_CASE_SELECTION_NOT_ESTABLISHED",
            "CLAIMS_CONDITION_ON_COMPLETED_CASES_AND_EXCLUDE_ABORTED_SCORES",
            "ABORTED_CASES_RETAINED_IN_ATTEMPT_DENOMINATOR",
            "NO_NEURAL_WEIGHT_OR_HOST_RUNTIME_ATTESTATION",
            "NO_MODEL_CALLS_OR_AUTOMATIC_SEMANTIC_SCORING_IN_THIS_AGGREGATOR",
        ],
    }


def _exclusive_output(path: Path, payload: dict[str, Any]) -> None:
    path = _external(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(loopback.canonical(payload) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    if path.read_bytes() != loopback.canonical(payload) + b"\n":
        raise loopback.LoopbackRejected("output readback mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    schedule = sub.add_parser("schedule")
    schedule.add_argument("--case-list", type=Path, required=True)
    schedule.add_argument("--secret-seed-file", type=Path, required=True)
    schedule.add_argument("--output", type=Path, required=True)
    analyze = sub.add_parser("aggregate")
    analyze.add_argument("--schedule", type=Path, required=True)
    analyze.add_argument("--result-ledger", type=Path, required=True)
    analyze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "schedule":
        case_list = _read(_external(args.case_list), MAX_MANIFEST_BYTES)
        seed_path = _external(args.secret_seed_file)
        if not seed_path.is_file() or seed_path.stat().st_size != 32:
            raise loopback.LoopbackRejected("secret seed file must contain 32 bytes")
        result = prepare_schedule(case_list, secret_seed=seed_path.read_bytes())
    else:
        source = _read(_external(args.schedule), MAX_MANIFEST_BYTES)
        ledger = _read(_external(args.result_ledger), MAX_MANIFEST_BYTES)
        result = aggregate(source, ledger)
    _exclusive_output(args.output, result)
    print(json.dumps({"status": result.get("status", "PRIVATE_SCHEDULE_PREPARED"),
                      "output_sha256": loopback.sha256(loopback.canonical(result)),
                      "model_calls": 0, "human_scoring": "IMPORTED_NOT_GENERATED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
