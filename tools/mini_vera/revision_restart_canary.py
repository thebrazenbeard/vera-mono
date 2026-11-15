"""Disposable PUBLIC correction/supersession across fresh Mini-Vera processes.

Synthetic evaluation only. The parent creates disposable data and does not\nselect user memory. The worker's path guard is not host authentication.
Five subprocesses test corrected visibility, stale refusal, approval revocation,
and an absent-memory control. An external model still requires independent
resource/host qualification; source code cannot establish that qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from typing import Any

from . import local_session, loopback, restart_public_canary as baseline
from .live_ledger import approved_ledger_provider

SCHEMA = "MINI_VERA_REVISION_RESTART_CANARY_V1"
PROMPT = (
    "Inspect the JSON reference data under project_context_untrusted. "
    "Find record_id revision-current. The record text states the synthetic "
    "corrected gate code. Return the exact SYNTHETIC- code in that text and "
    "nothing else. Only return UNKNOWN when revision-current is absent."
)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PUBLIC = re.compile(r"The synthetic (?:previous|corrected) gate code is "
                    r"SYNTHETIC-[0-9A-F]{16}\.\Z")


class RevisionCanaryRefused(ValueError):
    """Synthetic revision trial invalid or unable to establish its boundary."""


def _request(record_id: str, text: str, *, private: bool = False,
             supersedes: str | None = None):
    return baseline.AdmissionRequest(
        record_id=record_id, text=text,
        memory_class=baseline.MemoryClass.WORKING_PROJECT,
        source_actor="synthetic-revision-canary",
        authority_ref="synthetic-revision-test",
        privacy_ref="PRIVATE" if private else "PUBLIC",
        provenance_refs=("synthetic-revision-only",),
        operation_id="admit-" + record_id,
        project_id="vera-mono", governed_identity_id="vera",
        supersedes=supersedes,
    )


def _fixture(folder: Path) -> tuple[Path, str, str]:
    path = folder / "memory.sqlite"
    ledger = baseline.MemoryLedger(path, project_id="vera-mono", identity_id="vera")
    marker = "SYNTHETIC_PRIVATE_NEVER_SEND_" + secrets.token_hex(8)
    previous = "SYNTHETIC-" + secrets.token_hex(8).upper()
    current = "SYNTHETIC-" + secrets.token_hex(8).upper()
    while previous == current:
        current = "SYNTHETIC-" + secrets.token_hex(8).upper()
    ledger.admit(_request("revision-private", marker, private=True),
                 expected_head=ledger.current_head)
    ledger.admit(_request("revision-old",
                          f"The synthetic previous gate code is {previous}."),
                 expected_head=ledger.current_head)
    ledger.admit(_request("revision-current",
                          f"The synthetic corrected gate code is {current}.",
                          supersedes="revision-old"),
                 expected_head=ledger.current_head)
    if (ledger.read("revision-old").status != "SUPERSEDED" or
            ledger.read("revision-current").status != "CURRENT"):
        raise RevisionCanaryRefused("durable fixture supersession not established")
    return path, ledger.current_head, current


def _approve(record: Any, _head: str) -> bool:
    return bool(
        record.record_id in {"revision-old", "revision-current"}
        and record.privacy_ref == "PUBLIC"
        and record.authority_ref == "synthetic-revision-test"
        and record.source_actor == "synthetic-revision-canary"
        and record.provenance_refs == ("synthetic-revision-only",)
        and record.operation_id == "admit-" + record.record_id
        and record.project_id == "vera-mono"
        and record.governed_identity_id == "vera"
        and type(record.text) is str
        and PUBLIC.fullmatch(record.text) is not None
    )


def _checked_fixture_path(path: Path) -> None:
    """Deny arbitrary local ledger paths before any worker open."""
    if (not isinstance(path, Path) or not path.is_absolute()
            or path.name != "memory.sqlite"
            or not path.parent.name.startswith("mini-vera-revision-restart-")
            or path.is_symlink() or path.parent.is_symlink()
            or path.parent.is_junction()
            or not path.is_file()):
        raise RevisionCanaryRefused("worker requires disposable synthetic fixture")
    try:
        if (path.parent.parent.resolve(strict=True)
                != Path(tempfile.gettempdir()).resolve(strict=True)
                or path.stat().st_nlink != 1):
            raise RevisionCanaryRefused("synthetic fixture path outside temp root")
    except OSError as exc:
        raise RevisionCanaryRefused("fixture path unavailable") from exc


def worker(*, ledger_path: Path, head: str, arm: str,
           endpoint: str, model: str, model_digest: str) -> int:
    if arm not in {"current", "control", "stale", "revoked"}:
        raise RevisionCanaryRefused("invalid revision worker arm")
    _checked_fixture_path(ledger_path)
    provider = None
    if arm != "control":
        ledger = baseline.MemoryLedger(
            ledger_path, project_id="vera-mono", identity_id="vera")
        provider = approved_ledger_provider(
            ledger,
            record_ids=["revision-old" if arm == "stale" else "revision-current"],
            expected_head=head, expected_revision=8, integrity_key=baseline.KEY,
            host_public_project_approval=(
                (lambda _rec, _head: False) if arm == "revoked" else _approve),
        )
    return local_session.main(
        ["--endpoint", endpoint, "--model", model,
         "--model-digest", model_digest, "--execute",
         "--host-idle-confirmed", "--structured-output",
         "--ollama-disable-thinking", "--timeout-seconds", "60",
         "--max-output-tokens", "256", "--prompt", PROMPT],
        live_public_provider=provider,
    )


def score(*, expected: str, output: dict[str, str],
          stale_blocked: bool, revoked_blocked: bool) -> dict[str, Any]:
    copied = sum(output.get(arm, "").strip() == expected
                 for arm in ("current-a", "current-b"))
    control_unknown = output.get("control", "").strip() == "UNKNOWN"
    return {
        "corrected_exact_count": copied,
        "control_unknown": control_unknown,
        "stale_superseded_refused": stale_blocked,
        "revoked_refused": revoked_blocked,
        "behavioral_pass": bool(copied == 2 and control_unknown
                                and stale_blocked and revoked_blocked),
    }


def _child(*, path: Path, head: str, arm: str,
           endpoint: str, model: str, digest: str, timeout: int):
    return subprocess.run(
        [sys.executable, "-B", "-m",
         "tools.mini_vera.revision_restart_canary",
         "--worker", "--ledger", str(path), "--head", head,
         "--arm", arm, "--endpoint", endpoint,
         "--model", model, "--model-digest", digest],
        cwd=baseline.ROOT, capture_output=True, check=False,
        timeout=timeout,
    )


def run_trial(*, endpoint: str, model: str, model_digest: str,
              timeout_seconds: int = 90) -> dict[str, Any]:
    try:
        loopback._endpoint(endpoint)
    except loopback.LoopbackRejected as exc:
        raise RevisionCanaryRefused("only numeric loopback model endpoint allowed") from exc
    if (type(model) is not str or not model or len(model) > 128
            or type(model_digest) is not str
            or HEX64.fullmatch(model_digest) is None
            or type(timeout_seconds) is not int
            or not 5 <= timeout_seconds <= 180):
        raise RevisionCanaryRefused("invalid model alias, digest or timeout")
    with tempfile.TemporaryDirectory(prefix="mini-vera-revision-restart-") as temp:
        path, head, token = _fixture(Path(temp))
        labels = ["current-a", "current-b", "control"]
        secrets.SystemRandom().shuffle(labels)
        outputs: dict[str, str] = {}
        boundaries: dict[str, bool] = {}
        for label in [*labels, "stale", "revoked"]:
            arm = "current" if label.startswith("current-") else label
            try:
                completed = _child(
                    path=path, head=head, arm=arm, endpoint=endpoint,
                    model=model, digest=model_digest, timeout=timeout_seconds)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RevisionCanaryRefused("bounded restart worker failed") from exc
            if (len(completed.stdout) > baseline.MAX_CHILD_OUTPUT_BYTES or
                    len(completed.stderr) > baseline.MAX_CHILD_OUTPUT_BYTES):
                raise RevisionCanaryRefused("oversized restart worker output")
            if label in {"stale", "revoked"}:
                expected_error = b"superseded" if label == "stale" else b"approval"
                boundaries[label] = (completed.returncode == 2
                                     and not completed.stdout
                                     and expected_error in completed.stderr)
                if not boundaries[label]:
                    raise RevisionCanaryRefused("stale or revoked record was not refused")
                continue
            if completed.returncode != 0 or completed.stdout.count(b"\n") != 1:
                raise RevisionCanaryRefused("active restart worker failed")
            try:
                parsed = json.loads(completed.stdout)
                if (parsed.get("schema") != "MINI_VERA_LOCAL_OUTPUT_V1"
                        or parsed.get("model", {}).get("status")
                        != "UNVERIFIED_LOCAL_MODEL_OUTPUT"
                        or type(parsed["model"]["text"]) is not str):
                    raise ValueError("unverified or truncated response")
                outputs[label] = parsed["model"]["text"]
            except (ValueError, KeyError, TypeError) as exc:
                raise RevisionCanaryRefused("untrusted model output shape") from exc
        scored = score(expected=token, output=outputs,
                       stale_blocked=boundaries["stale"],
                       revoked_blocked=boundaries["revoked"])
        return {
            "schema": SCHEMA,
            "qualification": "SYNTHETIC_SOURCE_VISIBLE_NOT_MODEL_QUALIFIED",
            "model_alias": model, "model_digest_authority": "OPERATOR_DECLARED",
            "ledger_scope": "DISPOSABLE_SYNTHETIC_PUBLIC_ONLY",
            "synthetic_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "independent_python_sessions": 5,
            "model_http_calls_attempted": 3,
            "private_memory_access": False,
            "output_trust": "UNVERIFIED_GENERATIVE_TEXT",
            **scored,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-trial", action="store_true")
    mode.add_argument("--worker", action="store_true")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--head")
    parser.add_argument("--arm")
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    args = parser.parse_args(argv)
    if args.worker:
        if (args.ledger is None or not args.ledger.is_absolute()
                or type(args.head) is not str or HEX64.fullmatch(args.head) is None
                or args.arm not in {"current", "control", "stale", "revoked"}):
            parser.error("worker requires exact synthetic ledger/head/arm")
        return worker(ledger_path=args.ledger, head=args.head, arm=args.arm,
                      endpoint=args.endpoint, model=args.model,
                      model_digest=args.model_digest)
    if any((args.ledger, args.head, args.arm)):
        parser.error("trial cannot select existing user ledger or records")
    try:
        report = run_trial(endpoint=args.endpoint, model=args.model,
                           model_digest=args.model_digest,
                           timeout_seconds=args.timeout_seconds)
    except RevisionCanaryRefused as exc:
        print(f"REVISION_CANARY_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
