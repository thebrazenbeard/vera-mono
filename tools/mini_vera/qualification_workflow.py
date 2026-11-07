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
import stat
import sys
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


def _opened_final_path(fd: int) -> Path:
    """Identify the *opened file*, not a separately resolved pathname.

    On Windows the handle is the authority: GetFinalPathNameByHandleW returns
    the actual DOS target after reparse resolution. On Linux /proc/self/fd
    names the opened inode. Other platforms fail closed until a comparable
    native handle witness exists. This prevents a path accepted by _external
    from being replaced with an in-repository symlink before _read opens it.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        method = kernel.GetFinalPathNameByHandleW
        method.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        method.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32_768)
        length = method(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
        final = buffer.value
        # Reject UNC/device/volume-identifier inputs until their containment
        # relationship can be established as strongly as the DOS drive case.
        if not length or length >= len(buffer) or not final.startswith("\\\\?\\") or \
                final.startswith("\\\\?\\UNC\\"):
            raise loopback.LoopbackRejected("Windows external file handle path not attestable")
        return Path(final[4:])
    if sys.platform.startswith("linux"):
        final = os.readlink(f"/proc/self/fd/{fd}")
        if not final.startswith("/") or final.endswith(" (deleted)"):
            raise loopback.LoopbackRejected("Linux external file handle path not attestable")
        return Path(final)
    raise loopback.LoopbackRejected("no supported native external-file witness")


def _read_bytes(path: Path, maximum: int) -> bytes:
    """Read bounded bytes from one descriptor after final-target provenance."""
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size > maximum:
            raise loopback.LoopbackRejected("missing or oversized external evaluation file")
        final_path = _opened_final_path(fd)
        if not final_path.is_absolute() or final_path.is_relative_to(ROOT):
            raise loopback.LoopbackRejected("opened external evaluation file resolves into source repository")
        # Descriptor stays open through the read; pathname replacement after
        # the final-target check cannot redirect these bytes.
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(maximum + 1)
    except OSError as exc:
        raise loopback.LoopbackRejected("external evaluation file cannot be read safely") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > maximum:
        raise loopback.LoopbackRejected("oversized external evaluation file")
    return raw


def _read(path: Path, maximum: int) -> dict[str, Any]:
    return loopback._parse_object(_read_bytes(path, maximum))


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
        scenario = withheld_dialogue.validate_scenario(
            _read(_external(Path(row["scenario_path"])), withheld_dialogue.MAX_SCENARIO_BYTES)
        )
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


def _external_key_commitments(
    schedule: dict[str, Any], scheduled_case_ids: set[str], *,
    commitment: dict[str, Any] | None, expected_sha256: str | None,
) -> dict[str, str] | None:
    """Bind key bytes to an independently supplied exact SHA commitment.

    The caller must have frozen ``expected_sha256`` outside this mutable
    ledger *before ratings*. This function checks consistency, not chronology,
    custody, human independence, or the authority of the caller's digest.
    """
    if commitment is None and expected_sha256 is None:
        return None
    if type(commitment) is not dict or expected_sha256 is None:
        raise loopback.LoopbackRejected("external pre-rating key commitment and pinned SHA required together")
    if loopback.sha256(loopback.canonical(commitment)) != _hex64(expected_sha256):
        raise loopback.LoopbackRejected("external pre-rating key commitment drift")
    if (set(commitment) != {"schema", "schedule_sha256", "key_sha256_by_case"}
            or commitment["schema"] != "MINI_VERA_EXTERNAL_PRE_RATING_KEY_COMMITMENTS_V1"
            or commitment["schedule_sha256"] != loopback.sha256(loopback.canonical(schedule))):
        raise loopback.LoopbackRejected("external pre-rating key commitment schedule mismatch")
    pinned = commitment["key_sha256_by_case"]
    if (type(pinned) is not dict or not set(pinned).issubset(scheduled_case_ids)
            or any(type(case_id) is not str or type(digest) is not str
                   for case_id, digest in pinned.items())):
        raise loopback.LoopbackRejected("invalid external pre-rating key commitment case inventory")
    for digest in pinned.values():
        _hex64(digest)
    return pinned


def _external_rating_commitments(
    schedule: dict[str, Any], scheduled_case_ids: set[str], *,
    commitment: dict[str, Any] | None, expected_sha256: str | None,
) -> dict[str, list[str]] | None:
    """Check caller-pinned post-rating, pre-unblinding receipt SHA manifest.

    This is a consistency check conditional on an *independent external* SHA
    anchor. The tool cannot attest rater authorship, signature or chronology.
    """
    if commitment is None and expected_sha256 is None:
        return None
    if type(commitment) is not dict or expected_sha256 is None:
        raise loopback.LoopbackRejected("external rating commitments and pinned SHA required together")
    if loopback.sha256(loopback.canonical(commitment)) != _hex64(expected_sha256):
        raise loopback.LoopbackRejected("external rating receipt commitment drift")
    if (set(commitment) != {"schema", "schedule_sha256", "rating_sha256_by_case"}
            or commitment["schema"] != "MINI_VERA_EXTERNAL_POST_RATING_RECEIPT_COMMITMENTS_V1"
            or commitment["schedule_sha256"] != loopback.sha256(loopback.canonical(schedule))):
        raise loopback.LoopbackRejected("external rating receipt schedule mismatch")
    pinned = commitment["rating_sha256_by_case"]
    if (type(pinned) is not dict or not set(pinned).issubset(scheduled_case_ids)
            or any(type(case_id) is not str or type(digests) is not list
                   or not 1 <= len(digests) <= 8
                   or any(type(digest) is not str for digest in digests)
                   or len(digests) != len(set(digests))
                   for case_id, digests in pinned.items())):
        raise loopback.LoopbackRejected("invalid external rating receipt inventory")
    for digests in pinned.values():
        for digest in digests:
            _hex64(digest)
    return pinned


def _external_aborted_receipt_commitments(
    schedule: dict[str, Any], scheduled_case_ids: set[str], *,
    commitment: dict[str, Any] | None, expected_sha256: str | None,
) -> dict[str, str] | None:
    """Check a caller-supplied external pin for observed aborted attempts.

    Unlike completed trial key commitments, this protects the attempted-case
    denominator when an ABORTED receipt is later deleted from a mutable ledger.
    The caller must hold the expected digest outside the mutable ledger; these
    checks cannot attest independent custody, time or observed model calls.
    """
    if commitment is None and expected_sha256 is None:
        return None
    if type(commitment) is not dict or expected_sha256 is None:
        raise loopback.LoopbackRejected("external aborted receipts and pinned SHA required together")
    if loopback.sha256(loopback.canonical(commitment)) != _hex64(expected_sha256):
        raise loopback.LoopbackRejected("external aborted receipt commitment drift")
    if (set(commitment) != {"schema", "schedule_sha256", "aborted_receipt_sha256_by_case"}
            or commitment["schema"] != "MINI_VERA_EXTERNAL_ABORTED_RECEIPT_COMMITMENTS_V1"
            or commitment["schedule_sha256"] != loopback.sha256(loopback.canonical(schedule))):
        raise loopback.LoopbackRejected("external aborted receipt schedule mismatch")
    pinned = commitment["aborted_receipt_sha256_by_case"]
    if (type(pinned) is not dict or not set(pinned).issubset(scheduled_case_ids)
            or any(type(case_id) is not str or type(digest) is not str
                   for case_id, digest in pinned.items())):
        raise loopback.LoopbackRejected("invalid external aborted receipt case inventory")
    for digest in pinned.values():
        _hex64(digest)
    return pinned


def aggregate(schedule: dict[str, Any], ledger: dict[str, Any], *,
              pre_rating_key_commitments: dict[str, Any] | None = None,
              expected_pre_rating_key_commitment_sha256: str | None = None,
              post_rating_receipt_commitments: dict[str, Any] | None = None,
              expected_post_rating_receipt_commitment_sha256: str | None = None,
              aborted_receipt_commitments: dict[str, Any] | None = None,
              expected_aborted_receipt_commitment_sha256: str | None = None) -> dict[str, Any]:
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
    pinned_keys = _external_key_commitments(
        schedule, set(scheduled_by_id), commitment=pre_rating_key_commitments,
        expected_sha256=expected_pre_rating_key_commitment_sha256,
    )
    pinned_ratings = _external_rating_commitments(
        schedule, set(scheduled_by_id), commitment=post_rating_receipt_commitments,
        expected_sha256=expected_post_rating_receipt_commitment_sha256,
    )
    pinned_aborts = _external_aborted_receipt_commitments(
        schedule, set(scheduled_by_id), commitment=aborted_receipt_commitments,
        expected_sha256=expected_aborted_receipt_commitment_sha256,
    )
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
    completed_ids = {case_id for case_id, row in results.items()
                     if row.get("status") == "COMPLETED"}
    if pinned_keys is not None and set(pinned_keys) != completed_ids:
        raise loopback.LoopbackRejected(
            "externally committed completed trial key must remain COMPLETED in result ledger"
        )
    if pinned_ratings is not None:
        if set(pinned_ratings) != completed_ids:
            raise loopback.LoopbackRejected(
                "externally committed rated case must remain COMPLETED in result ledger"
            )
    aborted_ids = {case_id for case_id, row in results.items()
                   if row.get("status") == "ABORTED"}
    if pinned_aborts is not None and set(pinned_aborts) != aborted_ids:
        raise loopback.LoopbackRejected(
            "externally committed aborted receipt must remain ABORTED in result ledger"
        )

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
            if (pinned_aborts is not None and
                    loopback.sha256(loopback.canonical(receipt)) != pinned_aborts.get(case_id)):
                raise loopback.LoopbackRejected("aborted attempt receipt differs from external commitment")
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
        if pinned_keys is not None and pinned_keys.get(case_id) != row["private_key_sha256"]:
            raise loopback.LoopbackRejected("completed key differs from external pre-rating commitment")
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
        if (pinned_ratings is not None and
                sorted(receipt_hashes) != sorted(pinned_ratings.get(case_id, []))):
            raise loopback.LoopbackRejected("completed ratings differ from external pre-unblinding receipts")
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
        "external_pre_rating_key_custody": {
            "mode": ("EXACT_SHA_PINNED_EXTERNALLY_OPERATOR_SUPPLIED"
                     if pinned_keys is not None else "NOT_PROVIDED"),
            "commitment_sha256": expected_pre_rating_key_commitment_sha256,
            "timestamp_and_immutability": "NOT_ATTESTED_BY_THIS_TOOL",
        },
        "external_post_rating_receipt_custody": {
            "mode": ("EXACT_SHA_PINNED_EXTERNALLY_OPERATOR_SUPPLIED"
                     if pinned_ratings is not None else "NOT_PROVIDED"),
            "commitment_sha256": expected_post_rating_receipt_commitment_sha256,
            "rater_authorship_and_timestamp": "NOT_ATTESTED_BY_THIS_TOOL",
        },
        "external_aborted_attempt_custody": {
            "mode": ("EXACT_SHA_PINNED_EXTERNALLY_OPERATOR_SUPPLIED"
                     if pinned_aborts is not None else "NOT_PROVIDED"),
            "commitment_sha256": expected_aborted_receipt_commitment_sha256,
            "observation_timestamp_and_immutability": "NOT_ATTESTED_BY_THIS_TOOL",
        },
        "external_joint_custody_scope": (
            "KEYS_AND_RATINGS_CALLER_SHA_PINNED_BUT_NOT_AUTHENTICATED"
            if pinned_keys is not None and pinned_ratings is not None else
            "KEYS_ONLY_RATINGS_MUTABLE" if pinned_keys is not None else
            "RATINGS_ONLY_KEYS_MUTABLE" if pinned_ratings is not None else
            "NO_EXTERNAL_PINNED_CUSTODY"
        ),
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


def _windows_create_in_parent(parent: Path, name: str) -> int:
    """Exclusively create child relative to a verified, pinned Windows parent.

    A joined absolute CreateFileW child path would permit an ancestor-junction
    swap after _external checked it. We use NtCreateFile RootDirectory on a
    parent handle whose final path is checked *before* child creation.
    """
    if os.name != "nt" or sys.platform != "win32" or not name or \
            name in {".", ".."} or any(c in name for c in "/\\:\0") or \
            name.endswith((".", " ")):
        raise loopback.LoopbackRejected("Windows external output path unsupported")
    import ctypes
    from ctypes import wintypes
    import msvcrt

    class UnicodeString(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", ctypes.c_wchar_p)]

    class ObjectAttributes(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.POINTER(UnicodeString)),
                    ("Attributes", wintypes.ULONG), ("SecurityDescriptor", ctypes.c_void_p),
                    ("SecurityQualityOfService", ctypes.c_void_p)]

    class IoStatusUnion(ctypes.Union):
        _fields_ = [("Status", wintypes.LONG), ("Pointer", ctypes.c_void_p)]

    class IoStatusBlock(ctypes.Structure):
        _fields_ = [("u", IoStatusUnion), ("Information", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    native = ctypes.WinDLL("ntdll")
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                   wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    native.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                    ctypes.POINTER(ObjectAttributes),
                                    ctypes.POINTER(IoStatusBlock), ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    native.NtCreateFile.restype = wintypes.LONG
    # Existing parent: share read/write but *not delete/rename* while held.
    parent_handle = kernel.CreateFileW(
        "\\\\?\\" + str(parent), 0x0080 | 0x0020 | 0x00100000, 0x3,
        None, 3, 0x02000000, None)
    if not parent_handle or parent_handle == ctypes.c_void_p(-1).value:
        raise loopback.LoopbackRejected("Windows exclusive output parent open refused")
    parent_fd = -1
    new_handle = wintypes.HANDLE()
    try:
        parent_fd = msvcrt.open_osfhandle(parent_handle, os.O_RDONLY | os.O_BINARY)
        parent_handle = 0
        if _opened_final_path(parent_fd) != parent:
            raise loopback.LoopbackRejected("Windows external output parent changed before open")
        raw = ctypes.create_unicode_buffer(name)
        length = len(name.encode("utf-16-le"))
        if length > 510:
            raise loopback.LoopbackRejected("Windows external output name too long")
        u = UnicodeString(length, length + 2, ctypes.cast(raw, ctypes.c_wchar_p))
        attrs = ObjectAttributes(ctypes.sizeof(ObjectAttributes),
                                 wintypes.HANDLE(msvcrt.get_osfhandle(parent_fd)),
                                 ctypes.pointer(u), 0x40, None, None)
        ios = IoStatusBlock()
        status = native.NtCreateFile(
            ctypes.byref(new_handle), 0x0001 | 0x0002 | 0x0080 | 0x00100000,
            ctypes.byref(attrs), ctypes.byref(ios), None,
            0x80, 0, 2, 0x40 | 0x20, None, 0)
        if status != 0 or not new_handle.value:
            raise loopback.LoopbackRejected(
                f"Windows exclusive external output refused (NTSTATUS 0x{status & 0xffffffff:08x})")
        fd = msvcrt.open_osfhandle(new_handle.value, os.O_RDWR | os.O_BINARY)
        new_handle = wintypes.HANDLE()
        return fd
    finally:
        if new_handle.value:
            kernel.CloseHandle(new_handle)
        if parent_fd >= 0:
            os.close(parent_fd)
        if parent_handle:
            kernel.CloseHandle(wintypes.HANDLE(parent_handle))


def _exclusive_output(path: Path, payload: dict[str, Any]) -> None:
    """Create once relative to an attested parent; read back same descriptor."""
    path = _external(path)
    fd = -1
    parent_fd = -1
    expected = loopback.canonical(payload) + b"\n"
    try:
        if os.name == "nt":
            fd = _windows_create_in_parent(path.parent, path.name)
        elif sys.platform.startswith("linux"):
            parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if _opened_final_path(parent_fd) != path.parent:
                raise loopback.LoopbackRejected("external output parent changed before open")
            fd = os.open(path.name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent_fd)
        else:
            raise loopback.LoopbackRejected("safe native external output creation unsupported")
        with os.fdopen(fd, "r+b", closefd=False) as handle:
            handle.write(expected)
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            if handle.read(len(expected) + 1) != expected:
                raise loopback.LoopbackRejected("output descriptor readback mismatch")
    except OSError as exc:
        raise loopback.LoopbackRejected("safe external output creation failed") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if parent_fd >= 0:
            os.close(parent_fd)


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
    analyze.add_argument("--pre-rating-key-commitments", type=Path)
    analyze.add_argument("--expected-pre-rating-key-commitment-sha256")
    analyze.add_argument("--post-rating-receipt-commitments", type=Path)
    analyze.add_argument("--expected-post-rating-receipt-commitment-sha256")
    analyze.add_argument("--aborted-receipt-commitments", type=Path)
    analyze.add_argument("--expected-aborted-receipt-commitment-sha256")
    analyze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "schedule":
        case_list = _read(_external(args.case_list), MAX_MANIFEST_BYTES)
        seed_path = _external(args.secret_seed_file)
        seed = _read_bytes(seed_path, 32)
        if len(seed) != 32:
            raise loopback.LoopbackRejected("secret seed file must contain 32 bytes")
        result = prepare_schedule(case_list, secret_seed=seed)
    else:
        source = _read(_external(args.schedule), MAX_MANIFEST_BYTES)
        ledger = _read(_external(args.result_ledger), MAX_MANIFEST_BYTES)
        pre_rating = (_read(_external(args.pre_rating_key_commitments), MAX_MANIFEST_BYTES)
                      if args.pre_rating_key_commitments is not None else None)
        post_rating = (_read(_external(args.post_rating_receipt_commitments), MAX_MANIFEST_BYTES)
                       if args.post_rating_receipt_commitments is not None else None)
        aborted_receipts = (_read(_external(args.aborted_receipt_commitments), MAX_MANIFEST_BYTES)
                            if args.aborted_receipt_commitments is not None else None)
        result = aggregate(
            source, ledger, pre_rating_key_commitments=pre_rating,
            expected_pre_rating_key_commitment_sha256=args.expected_pre_rating_key_commitment_sha256,
            post_rating_receipt_commitments=post_rating,
            expected_post_rating_receipt_commitment_sha256=args.expected_post_rating_receipt_commitment_sha256,
            aborted_receipt_commitments=aborted_receipts,
            expected_aborted_receipt_commitment_sha256=args.expected_aborted_receipt_commitment_sha256,
        )
    _exclusive_output(args.output, result)
    print(json.dumps({"status": result.get("status", "PRIVATE_SCHEDULE_PREPARED"),
                      "output_sha256": loopback.sha256(loopback.canonical(result)),
                      "model_calls": 0, "human_scoring": "IMPORTED_NOT_GENERATED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
