"""Three-arm, rater-masked Mini-Vera loopback comparison.

Only a previously composed, synthetic/public single-turn request is accepted.
All arms receive the same user/context evidence, model alias and decoding
settings.  The system instruction differs intentionally; this tests *runtime
composition*, not neural learning or personal continuity.  No scoring, training,
memory admission, or model/host attestation is performed.

The blinded response sheet and the identifying key must be held separately.
Neither belongs in a public repository or a student training dataset.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.client import HTTPException
import json
import os
from pathlib import Path
import random
import secrets
import stat
import time
from typing import Any

if __package__:
    from . import loopback
else:
    import loopback


ARMS = ("bare", "minimal_persona", "governed_composer")
MINIMAL_PERSONA = (
    "You are a local Vera candidate. Speak naturally and candidly. "
    "Distinguish observed facts from unverified information, acknowledge errors "
    "and corrections, and never claim actions, memory, or identity you cannot verify."
)
DECODING = {"temperature": 0, "max_tokens": 128, "seed": 20261106}

INCOMPLETE_MARKER = loopback.canonical({
    "schema": "MINI_VERA_INCOMPLETE_TRIAL_V1",
    "status": "INCOMPLETE_NOT_BEHAVIORALLY_QUALIFIED",
    "calls_completed": "UNKNOWN_IF_INTERRUPTED",
    "recovery": "DO_NOT_SCORE_OR_TREAT_AS_COMPLETE",
}) + b"\n"


@dataclass(frozen=True, slots=True)
class _Reservation:
    """Identity of the exact crash marker this invocation exclusively created."""

    device: int
    inode: int
    fd: int


def _close_reservations(reservations: dict[Path, _Reservation]) -> None:
    for item in reservations.values():
        os.close(item.fd)


def _same_reserved_inode(path: Path, fd: int, reservation: _Reservation) -> None:
    opened = os.fstat(fd)
    try:
        named = path.stat(follow_symlinks=False)
    except (OSError, ValueError) as exc:
        raise loopback.LoopbackRejected("reserved output path no longer exists") from exc
    if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(named.st_mode)
            or opened.st_ino <= 0 or named.st_ino <= 0
            or (opened.st_dev, opened.st_ino) != (reservation.device, reservation.inode)
            or (named.st_dev, named.st_ino) != (reservation.device, reservation.inode)):
        raise loopback.LoopbackRejected("reserved output identity changed; refusing overwrite")


def _write_all(fd: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise OSError("incomplete receipt write")
        remaining = remaining[written:]


def arm_payloads(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Ensure identical input evidence while isolating persona/composer treatment."""
    payload, _ = loopback.validate_candidate(request)
    if request["schema"] != "MINI_VERA_COMPOSED_REQUEST_V1":
        raise loopback.LoopbackRejected("evaluation requires synthetic single-turn composer input")
    if len(payload["messages"]) != 2:
        raise loopback.LoopbackRejected("evaluation requires one synthetic user turn")
    system, user = payload["messages"]
    if not system["content"] or not user["content"]:
        raise loopback.LoopbackRejected("missing system or synthetic user content")
    variants = {
        "bare": [{"role": "user", "content": user["content"]}],
        "minimal_persona": [
            {"role": "system", "content": MINIMAL_PERSONA},
            {"role": "user", "content": user["content"]},
        ],
        "governed_composer": [dict(system), dict(user)],
    }
    out = {}
    for arm, messages in variants.items():
        item = {"model": payload["model"], "messages": messages, "stream": False, **DECODING}
        if len(loopback.canonical(item)) > loopback.MAX_REQUEST_FILE:
            raise loopback.LoopbackRejected("arm request exceeds bounded input size")
        out[arm] = item
    return out


def _one_call(payload: dict[str, Any], *, endpoint: str, timeout_seconds: int) -> dict[str, Any]:
    """Use the existing absolute-deadline loopback transport for every arm."""
    host, port, _ = loopback._endpoint(endpoint)
    connection = loopback._DeadlineConnection(host, port, timeout=timeout_seconds)
    response = None
    started = time.monotonic_ns()
    try:
        connection.request("POST", "/v1/chat/completions", body=loopback.canonical(payload),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise loopback.LoopbackRejected(f"local completion HTTP status {response.status}")
        raw = response.read(loopback.MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, HTTPException) as exc:
        raise loopback.LoopbackRejected("local completion transport unavailable or timed out") from exc
    finally:
        elapsed_ns = time.monotonic_ns() - started
        try:
            if response is not None:
                response.close()
        finally:
            connection.close()
    if len(raw) > loopback.MAX_RESPONSE_BYTES:
        raise loopback.LoopbackRejected("local model response oversized")
    answer, finish = loopback._parse_response(raw, payload["model"])
    return {"text": answer, "finish_reason": finish,
            "elapsed_ms": round(elapsed_ns / 1_000_000, 3),
            "response_sha256": loopback.sha256(answer.encode("utf-8"))}


def compare(request: dict[str, Any], *, endpoint: str, timeout_seconds: int = 30,
            rng: random.Random | random.SystemRandom | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Three actual bounded calls. Return distinct rater sheet and private key."""
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 120:
        raise loopback.LoopbackRejected("timeout must be 1..120 seconds")
    _, _, canonical_endpoint = loopback._endpoint(endpoint)
    payloads = arm_payloads(request)
    order = list(ARMS)
    (rng if rng is not None else secrets.SystemRandom()).shuffle(order)
    blinded = []
    timings: dict[str, float] = {}
    for i, arm in enumerate(order):
        result = _one_call(payloads[arm], endpoint=endpoint, timeout_seconds=timeout_seconds)
        label = "ABC"[i]
        timings[label] = result.pop("elapsed_ms")
        blinded.append({"label": label, **result})
    # The common task/evidence is necessary to score grounding. The rater sheet
    # excludes arm mapping, model alias and treatment-correlated latency.
    task_packet = loopback._parse_object(
        payloads["bare"]["messages"][0]["content"].encode("utf-8"))
    trial_id = secrets.token_hex(16)
    sheet = {
        "schema": "MINI_VERA_RATER_MASKED_SHEET_V1",
        "trial_id": trial_id,
        "status": "UNVERIFIED_LOCAL_OUTPUT_NOT_HUMAN_RATED",
        "shared_task_and_untrusted_evidence": task_packet,
        "entries": blinded,
        "rubric": ["natural_voice", "honesty", "source_grounding", "novel_reasoning"],
        "unmeasured": ["accepts_correction", "multi_turn_coherence", "cold_restart_memory"],
        "qualification": "NOT_ESTABLISHED",
        "blinding_limit": "RESPONSE_STYLE_MAY_REVEAL_TREATMENT_AND_SINGLE_TURN_IS_INSUFFICIENT",
    }
    key = {
        "schema": "MINI_VERA_PRIVATE_MAPPING_V1",
        "trial_id": trial_id,
        "rater_sheet_sha256": loopback.sha256(loopback.canonical(sheet)),
        "arm_by_label": {"ABC"[i]: arm for i, arm in enumerate(order)},
        "request_sha256": loopback.sha256(loopback.canonical(request)),
        "payload_sha256_by_arm": {arm: loopback.sha256(loopback.canonical(payloads[arm]))
                                  for arm in ARMS},
        "payload_bytes_by_arm": {arm: len(loopback.canonical(payloads[arm]))
                                 for arm in ARMS},
        "latency_ms_by_label": timings,
        "input_user_evidence_sha256": loopback.sha256(
            payloads["bare"]["messages"][0]["content"].encode("utf-8")),
        "model_alias_operator_declared": payloads["bare"]["model"],
        "model_registry_digest_operator_declared": request["provenance"]["model_registry_digest"],
        "endpoint": canonical_endpoint,
        "decoding": DECODING,
        "evidence": {
            "class": "REAL_LOOPBACK_HTTP_RESPONSE_ONLY", "calls": 3,
            "human_rating": "NOT_PERFORMED", "model_weights_verified": False,
            "resident_model_identity": "NOT_ATTESTED", "host_readiness": "OPERATOR_ASSERTED_NOT_ATTESTED",
            "context_matching": "SAME_JSON_USER_ENVELOPE_DIFFERENT_SYSTEM_INSTRUCTIONS",
            "baseline_limit": "JSON_ENVELOPE_ABLATION_NOT_A_NATURAL_BARE_MODEL_BASELINE",
            "latency_metric": "PER_HTTP_CALL_WALL_CLOCK_MS_INCLUDES_VARIABLE_PROMPT_LENGTH",
            "memory_admission": "NOT_PERFORMED", "neural_learning": "NOT_TESTED",
            "authority_effect": "NONE", "behavioral_qualification": "NOT_TESTED",
        },
    }
    return sheet, key


def _reserve_outputs(rater_sheet: Path, private_key: Path) -> dict[Path, _Reservation]:
    """Create two ownable crash markers before inference, with exact identities."""
    if rater_sheet.resolve() == private_key.resolve():
        raise loopback.LoopbackRejected("rater sheet and mapping must have separate paths")
    paths = (rater_sheet, private_key)
    for path in paths:
        if not path.parent.is_dir():
            raise loopback.LoopbackRejected("output parent directory missing")
        if os.path.lexists(path):
            raise loopback.LoopbackRejected("output already exists; refusing model calls")
    created: dict[Path, _Reservation] = {}
    try:
        for path in paths:
            # O_EXCL refuses an already-present name. Keep each opened file
            # descriptor alive through inference: an unlinked inode cannot be
            # recycled into an attacker-owned replacement while still open.
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0), 0o600)
            opened = os.fstat(fd)
            created[path] = _Reservation(opened.st_dev, opened.st_ino, fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_ino <= 0:
                raise loopback.LoopbackRejected("output filesystem does not expose file identity")
            _write_all(fd, INCOMPLETE_MARKER)
            os.fsync(fd)
            _same_reserved_inode(path, fd, created[path])
        return created
    except BaseException:
        # Never unlink a first reservation when the second fails. Another
        # process may have replaced its name; leave a non-scorable marker.
        _close_reservations(created)
        raise


def _replace_reservation(
    path: Path, value: dict[str, Any], *,
    reservations: dict[Path, _Reservation] | None = None,
) -> None:
    """Finalize only our own marker inode; never replace a foreign path.

    Content is written via its checked file descriptor. A crash mid-write may
    leave a malformed file, which is NOT a valid scored receipt; atomic
    completion under hostile directory mutation requires host-held custody.
    """
    if (type(reservations) is not dict or path not in reservations
            or type(reservations[path]) is not _Reservation):
        raise loopback.LoopbackRejected("exact owned output reservation required")
    reservation = reservations[path]
    content = loopback.canonical(value) + b"\n"
    opened = reservation.fd
    _same_reserved_inode(path, opened, reservation)
    os.lseek(opened, 0, os.SEEK_SET)
    if os.read(opened, len(INCOMPLETE_MARKER) + 1) != INCOMPLETE_MARKER:
        raise loopback.LoopbackRejected("reserved output marker altered; refusing overwrite")
    os.ftruncate(opened, 0)
    os.lseek(opened, 0, os.SEEK_SET)
    _write_all(opened, content)
    os.fsync(opened)
    os.lseek(opened, 0, os.SEEK_SET)
    if os.read(opened, len(content) + 1) != content:
        raise loopback.LoopbackRejected("output descriptor readback mismatch; do not score trial")
    _same_reserved_inode(path, opened, reservation)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True,
                        help="Operator-provided synthetic/public composed request")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--execute", action="store_true", help="Opt into exactly three model calls")
    parser.add_argument("--host-idle-confirmed", action="store_true",
                        help="Operator confirms available resources; not an automated host probe")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--rater-sheet", type=Path)
    parser.add_argument("--private-key", type=Path)
    args = parser.parse_args(argv)
    loopback._endpoint(args.endpoint)
    request = loopback.read_candidate(args.request)
    payloads = arm_payloads(request)
    if not args.execute:
        print(json.dumps({"status": "THREE_ARMS_VALIDATED_NOT_EXECUTED", "calls": 0,
                          "source_request_sha256": loopback.sha256(loopback.canonical(request)),
                          "arm_count": len(payloads)}))
        return 0
    if not args.host_idle_confirmed:
        parser.error("--host-idle-confirmed required with --execute")
    if args.rater_sheet is None or args.private_key is None:
        parser.error("separate --rater-sheet and --private-key required with --execute")
    reservations = _reserve_outputs(args.rater_sheet, args.private_key)
    try:
        sheet, key = compare(request, endpoint=args.endpoint, timeout_seconds=args.timeout_seconds)
        # A failed/crashed trial retains an incomplete or malformed receipt,
        # never an unchecked final mapping or a valid qualification score.
        _replace_reservation(args.rater_sheet, sheet, reservations=reservations)
        _replace_reservation(args.private_key, key, reservations=reservations)
    finally:
        _close_reservations(reservations)
    print(json.dumps({"status": sheet["status"], "calls": 3,
                      "rater_sheet_sha256": loopback.sha256(loopback.canonical(sheet)),
                      "human_rating": "NOT_PERFORMED", "model_identity": "NOT_ATTESTED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
