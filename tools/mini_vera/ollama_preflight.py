"""Conservative, opt-in Lappy Ollama 0.8B preflight and Mini-Vera launcher.

Only GET /api/tags and GET /api/ps are used during preflight. Neither loads
weights. An explicit --execute can hand off to the existing bounded local
session, but the checks are estimates, NOT a lock/lease or weight attestation.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import ctypes
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import io
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import time
from collections.abc import Callable
from typing import Any

from . import local_session, loopback


GIB = 1024 ** 3
MAX_JSON = 65_536
MAX_08B_MODEL_BYTES = 2 * GIB
WARM_FREE_BYTES = 1 * GIB
COLD_HEADROOM_BYTES = 2 * GIB
DEFAULT_ENDPOINT = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen3.5:0.8b"


class PreflightRefused(ValueError):
    """A read-only observation cannot authorize an inference attempt."""


def _receipt_target(path: Path) -> tuple[Path, tuple[int, int]]:
    """Validate a *non-secret* receipt destination before model execution.

    This is not an ACL, hostile-directory or host-ownership attestation. The
    caller must supply a trusted, private parent when that distinction matters.
    """
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise PreflightRefused("receipt output must be an absolute file path")
    if ".." in path.parts:
        raise PreflightRefused("receipt output must not traverse parent aliases")
    try:
        parent = path.parent
        # A textual comparison with Path.resolve() is invalid on Windows:
        # a legitimate 8.3 short pathname such as RUNNER~1 may resolve to its
        # long spelling, although no link or junction exists. Inspect each
        # actual ancestor instead, rejecting symlinks and Windows reparse
        # points (including junctions) without requiring string equality.
        for ancestor in (parent, *parent.parents):
            entry = os.lstat(ancestor)
            if (stat.S_ISLNK(entry.st_mode)
                    or getattr(entry, "st_file_attributes", 0) & 0x400):
                raise PreflightRefused("receipt parent contains a symlink or reparse point")
        parent_stat = os.stat(parent, follow_symlinks=False)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise PreflightRefused("receipt parent is not a directory")
        if path.exists() or path.is_symlink():
            raise PreflightRefused("receipt already exists; refusing inference")
    except OSError as exc:
        raise PreflightRefused("receipt parent unavailable") from exc
    return parent, (parent_stat.st_dev, parent_stat.st_ino)


def _commit_receipt_atomically(path: Path, payload: dict[str, Any],
                               parent_identity: tuple[int, int]) -> None:
    """Publish a complete but explicitly UNQUALIFIED JSON observation.

    The final filename is absent until its complete fsynced content exists.
    No path-based cleanup is attempted: between stat and unlink, a shared
    parent owner could substitute another actor's file. Orphaned `.incomplete`
    names require a separate, authorized host-owned cleanup operation.
    """
    parent = path.parent
    data = _receipt_bytes(payload)
    temporary = parent / f".{path.name}.{secrets.token_hex(12)}.incomplete"
    fd: int | None = None
    temp_identity: tuple[int, int] | None = None
    try:
        # Windows CRT defaults os.open to O_TEXT: os.write then silently
        # transforms our canonical terminal LF into CRLF, so the printed
        # SHA-256 no longer matches the bytes on disk. Force raw byte writes.
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0) |
                     getattr(os, "O_BINARY", 0), 0o600)
        opened = os.fstat(fd)
        temp_identity = (opened.st_dev, opened.st_ino)
        remaining = memoryview(data)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("incomplete receipt write")
            remaining = remaining[written:]
        os.fsync(fd)
        os.close(fd)
        fd = None
        # O_EXCL is required for the temporary filename; os.link is required
        # for atomic no-overwrite publication of the *final* filename.
        # The temporary path was created as an exclusive regular file; no
        # follow_symlinks keyword is needed for Windows hard-link portability.
        os.link(temporary, path)
        final_stat = os.stat(path, follow_symlinks=False)
        parent_stat = os.stat(parent, follow_symlinks=False)
        if ((final_stat.st_dev, final_stat.st_ino) != temp_identity
                or (parent_stat.st_dev, parent_stat.st_ino) != parent_identity):
            raise PreflightRefused("receipt path custody changed after publication")
        # A success-shaped receipt cannot survive an observed metadata-sync
        # error. Sync the *published final name* before claiming success. The
        # temporary unlink below may remain pending after a sudden power loss.
        if os.name != "nt":
            parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    except (OSError, ValueError) as exc:
        raise PreflightRefused("atomic receipt publication failed or was contested") from exc
    finally:
        if fd is not None:
            os.close(fd)
        # Deliberately DO NOT unlink the temporary path. Even fstat + stat
        # identity checks would leave an exploitable check-to-unlink gap in a
        # parent directory whose exclusive ownership has not been qualified.
    # Windows/Python exposes no equivalent directory-entry fsync through
    # os.open; the receipt marks this as unqualified instead of claiming it.


def _receipt_bytes(payload: dict[str, Any]) -> bytes:
    """Exact canonical newline-terminated bytes committed to the receipt file."""
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n").encode("utf-8")


def windows_free_physical_bytes() -> int:
    """Actual Windows free physical memory; fail closed on other hosts."""
    if sys.platform != "win32":
        raise PreflightRefused("Windows physical RAM probe unavailable on this host")

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    try:
        success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError) as exc:
        raise PreflightRefused("Windows RAM probe failed") from exc
    if not success:
        raise PreflightRefused("Windows RAM probe failed")
    return int(status.ullAvailPhys)


def _read_ollama_json(host: str, port: int, path: str) -> dict[str, Any]:
    """A capped local GET; redirects, auth headers and arbitrary URLs forbidden."""
    if path not in {"/api/tags", "/api/ps"}:
        raise PreflightRefused("unsupported local Ollama probe path")
    # HTTPConnection(timeout=2) is only a per-read socket timeout: a local
    # server that trickles one byte every 0.4 seconds can keep the response
    # alive indefinitely. Reuse the existing loopback absolute-deadline
    # transport for headers and body, including the connection phase.
    conn = loopback._DeadlineConnection(host, port, timeout=2)
    try:
        conn.request("GET", path, headers={"Accept": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            raise PreflightRefused(f"Ollama {path} status {response.status}")
        raw = response.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise PreflightRefused("oversized Ollama probe response")
        return loopback._parse_object(raw)
    except (OSError, HTTPException, TimeoutError, UnicodeError) as exc:
        raise PreflightRefused(f"Ollama {path} unavailable") from exc
    except loopback.LoopbackRejected as exc:
        raise PreflightRefused(f"malformed Ollama {path} response") from exc
    finally:
        conn.close()


def _model_entry(data: dict[str, Any], field: str, model: str, *,
                 reject_foreign: bool = False) -> dict[str, Any] | None:
    if type(data) is not dict:
        raise PreflightRefused("invalid Ollama inventory object")
    models = data.get(field)
    if type(models) is not list or len(models) > 256:
        raise PreflightRefused(f"invalid Ollama {field} inventory")
    result: dict[str, Any] | None = None
    for entry in models:
        if type(entry) is not dict:
            raise PreflightRefused(f"invalid Ollama {field} item")
        alias = entry.get("name", entry.get("model"))
        if type(alias) is not str or loopback.MODEL.fullmatch(alias) is None:
            raise PreflightRefused(f"invalid Ollama {field} alias")
        if alias == model:
            if result is not None:
                raise PreflightRefused("duplicate selected Ollama model alias")
            result = entry
        elif reject_foreign:
            # /api/ps must have NO other models resident. An available-memory
            # counter does not entitle us to evict or compete with them.
            raise PreflightRefused("foreign Ollama model resident; no shared model disruption")
    return result


def probe(*, endpoint: str = DEFAULT_ENDPOINT, model: str = DEFAULT_MODEL,
          expected_tag_digest: str | None = None,
          memory_probe: Callable[[], int] = windows_free_physical_bytes,
          get_json: Callable[[str, int, str], dict[str, Any]] = _read_ollama_json,
          allow_cold_load: bool = False) -> dict[str, Any]:
    """Return a bounded observation; rejection is never execution authority."""
    host, port, _ = loopback._endpoint(endpoint)
    if type(model) is not str or loopback.MODEL.fullmatch(model) is None:
        raise PreflightRefused("invalid selected model alias")
    if (expected_tag_digest is not None and
            (type(expected_tag_digest) is not str or
             loopback.HEX64.fullmatch(expected_tag_digest) is None)):
        raise PreflightRefused("invalid expected Ollama tag digest")
    available = memory_probe()
    if type(available) is not int or available < 0:
        raise PreflightRefused("invalid host free-memory reading")
    tags = get_json(host, port, "/api/tags")
    resident = get_json(host, port, "/api/ps")
    # Both inventory GETs have bounded, but nonzero, network deadlines. The
    # initial RAM reading can be stale after them; require the lower of two
    # independent physical-memory observations before returning readiness.
    # This narrows TOCTOU; it is still neither a lease nor execution authority.
    latest_available = memory_probe()
    if type(latest_available) is not int or latest_available < 0:
        raise PreflightRefused("invalid host free-memory reading")
    available = min(available, latest_available)
    tag = _model_entry(tags, "models", model)
    if tag is None:
        raise PreflightRefused("selected Ollama model not installed")
    size, digest = tag.get("size"), tag.get("digest")
    if (type(size) is not int or not 0 < size <= MAX_08B_MODEL_BYTES or
            type(digest) is not str or loopback.HEX64.fullmatch(digest) is None):
        raise PreflightRefused("model size or tag digest unavailable/over 0.8B budget")
    if expected_tag_digest is not None and digest != expected_tag_digest:
        raise PreflightRefused("Ollama tag digest changed since expected inventory")
    active = _model_entry(resident, "models", model, reject_foreign=True)
    warm = active is not None
    if warm:
        if active.get("digest") != digest:
            raise PreflightRefused("resident model tag digest mismatch")
        required = WARM_FREE_BYTES
    else:
        required = size + COLD_HEADROOM_BYTES
    if available < required:
        raise PreflightRefused("insufficient free physical RAM for bounded local inference")
    # For cold loads, a separate affirmative operator choice is required. No
    # process or model eviction, auto-download, or service startup is performed.
    if not warm and not allow_cold_load:
        status = "COLD_MODEL_NOT_AUTHORIZED_TO_LOAD"
    else:
        status = "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE"
    return {
        "schema": "MINI_VERA_08B_PREFLIGHT_V1",
        "status": status,
        "model": model,
        "ollama_tag_digest": digest,
        "digest_evidence": "SERVER_DECLARED_NOT_WEIGHT_ATTESTATION",
        "identity_provenance": "REVIEWED_CODE_SHA_PINS_NOT_HOST_ATTESTED",
        "model_size_bytes": size,
        "model_resident": warm,
        "available_physical_ram_bytes": available,
        "required_physical_ram_bytes": required,
        "exclusive_host_lease": False,
        "http_methods": ["GET /api/tags", "GET /api/ps"],
        "model_inference_calls": 0,
    }


def main(argv: list[str] | None = None, *,
         memory_probe: Callable[[], int] = windows_free_physical_bytes,
         get_json: Callable[[str, int, str], dict[str, Any]] = _read_ollama_json) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--expected-tag-digest", help="Pin Ollama tag manifest digest")
    parser.add_argument("--prompt", help="A bounded Mini-Vera local-session turn")
    parser.add_argument("--execute", action="store_true", help="Opt in to one actual local inference")
    parser.add_argument("--host-idle-confirmed", action="store_true",
                        help="Fresh operator host resource qualification, not an automated lease")
    parser.add_argument("--allow-cold-load", action="store_true",
                        help="Explicitly permit loading a nonresident model if RAM permits")
    parser.add_argument("--receipt-output", type=Path,
                        help="Optional absolute output for a no-overwrite, hash-only real-trial receipt")
    args = parser.parse_args(argv)
    if args.prompt is not None and not args.execute:
        parser.error("--prompt requires --execute; omit it for a read-only preflight")
    if args.execute and (not args.host_idle_confirmed or not args.prompt):
        parser.error("--execute needs --host-idle-confirmed and --prompt")
    if args.receipt_output is not None and not args.execute:
        parser.error("--receipt-output requires --execute")
    receipt_parent_identity: tuple[int, int] | None = None
    if args.receipt_output is not None:
        try:
            _, receipt_parent_identity = _receipt_target(args.receipt_output)
        except PreflightRefused as exc:
            print(json.dumps({"schema": "MINI_VERA_08B_PREFLIGHT_V1",
                              "status": "REFUSED", "reason": str(exc),
                              "model_inference_calls": 0}), file=sys.stderr)
            return 2
    try:
        receipt = probe(endpoint=args.endpoint, model=args.model,
                        expected_tag_digest=args.expected_tag_digest,
                        memory_probe=memory_probe, get_json=get_json,
                        allow_cold_load=args.allow_cold_load)
    except (PreflightRefused, loopback.LoopbackRejected) as exc:
        print(json.dumps({"schema": "MINI_VERA_08B_PREFLIGHT_V1",
                          "status": "REFUSED", "reason": str(exc),
                          "model_inference_calls": 0}), file=sys.stderr)
        return 2
    if not args.execute:
        # Probe mode does not send a chat completion or perform model loading.
        print(json.dumps(receipt, sort_keys=True))
        return 0
    if receipt["status"] != "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE":
        print("Model is cold; --allow-cold-load required before inference", file=sys.stderr)
        return 2
    # The inventory and physical-RAM estimates can drift between the first
    # preflight and actual request composition. Recheck immediately before the
    # session handoff, with the exact original model-tag digest pinned; a
    # residency transition is also grounds to refuse. This still provides no
    # exclusive host lease and cannot close the final check-to-use race.
    try:
        final_receipt = probe(
            endpoint=args.endpoint, model=args.model,
            expected_tag_digest=receipt["ollama_tag_digest"],
            memory_probe=memory_probe, get_json=get_json,
            allow_cold_load=args.allow_cold_load,
        )
        if (final_receipt["status"] != "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE"
                or final_receipt["model_resident"] != receipt["model_resident"]):
            raise PreflightRefused("Ollama residency or host readiness changed before handoff")
    except (PreflightRefused, loopback.LoopbackRejected) as exc:
        print(json.dumps({"schema": "MINI_VERA_08B_PREFLIGHT_V1",
                          "status": "REFUSED", "reason": str(exc),
                          "model_inference_calls": 0}), file=sys.stderr)
        return 2
    print(json.dumps(final_receipt, sort_keys=True))
    # A race still remains after this final read-only observation. The digest
    # forwarded to the composer is server-declared, never weight attestation.
    session_args = [
        "--endpoint", args.endpoint, "--model", args.model,
        "--model-digest", final_receipt["ollama_tag_digest"],
        "--execute", "--host-idle-confirmed", "--ollama-disable-thinking",
        "--prompt", args.prompt,
    ]
    if args.receipt_output is None:
        return local_session.main(session_args)

    # The local-session CLI does not expose an authenticated raw model result.
    # Capture its *displayed* reply only; the receipt records a hash, never
    # prompt text or model text. This is not raw provider attestation.
    emitted = io.StringIO()
    began = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    with redirect_stdout(emitted):
        result_code = local_session.main(session_args)
    duration_ms = round((time.monotonic() - began) * 1000, 3)
    displayed = emitted.getvalue()
    if result_code != 0 or not displayed.startswith(("Vera> ", "Vera [incomplete reply]> ")):
        # A failed/ambiguous call may have reached the model. There is no
        # success receipt and *no* claim that the call count was zero.
        if displayed:
            print(displayed, end="")
        print("Mini-Vera receipt withheld: failed or ambiguous local call; "
              "model call count unknown", file=sys.stderr)
        return 2
    displayed_text = displayed.split("> ", 1)[1].rstrip("\n")
    complete_reply = displayed.startswith("Vera> ")
    trial_receipt = {
        "schema": "MINI_VERA_HASH_ONLY_TRIAL_RECEIPT_V1",
        "status": ("CLIENT_OBSERVED_LOCAL_SESSION_OUTPUT" if complete_reply else
                   "CLIENT_OBSERVED_TRUNCATED_LOCAL_SESSION_OUTPUT") +
                  "_PUBLICATION_UNQUALIFIED",
        "evidence_class": "CLIENT_WRAPPER_OBSERVED_OUTPUT_NOT_WEIGHT_ATTESTATION",
        "publication_custody": "UNQUALIFIED_NOT_A_DURABLE_COMMIT_RECORD",
        "started_at_utc": started_at,
        "delegated_session_duration_ms": duration_ms,
        "endpoint": args.endpoint,
        "model_alias": args.model,
        "server_declared_tag_digest": final_receipt["ollama_tag_digest"],
        "model_weights_verified": False,
        "receipt_file_fsynced": True,
        # This field is written *before* any publication or parent fsync.
        # A persisted receipt can never self-attest its own final fsync.
        "receipt_directory_metadata_fsynced": False,
        "exclusive_host_lease": False,
        "host_free_ram_bytes_before_handoff": final_receipt["available_physical_ram_bytes"],
        "cold_load_authorized": args.allow_cold_load,
        "identity_source_sha256_code_pin": local_session.PINNED_IDENTITY_SHA256,
        "behavior_source_sha256_code_pin": local_session.PINNED_BEHAVIOR_SHA256,
        "input_prompt_sha256": hashlib.sha256(args.prompt.encode("utf-8")).hexdigest(),
        "displayed_reply_sha256": hashlib.sha256(displayed_text.encode("utf-8")).hexdigest(),
        "displayed_reply_bytes": len(displayed_text.encode("utf-8")),
        "reply_complete": complete_reply,
        "model_inference_calls": "ONE_SUCCESSFUL_DELEGATED_SESSION_EXPECTED_NOT_ATTESTED",
        "composed_request_sha256": None,
        "raw_response_sha256": None,
    }
    assert receipt_parent_identity is not None
    try:
        _commit_receipt_atomically(args.receipt_output, trial_receipt,
                                   receipt_parent_identity)
    except PreflightRefused as exc:
        print(f"Mini-Vera receipt withheld: {exc}; model call already attempted",
              file=sys.stderr)
        return 2
    print(displayed, end="")
    print(json.dumps({"receipt_status": "PUBLISHED_HASH_ONLY_CUSTODY_UNQUALIFIED",
                      "receipt_path": str(args.receipt_output),
                      "receipt_sha256": hashlib.sha256(
                          _receipt_bytes(trial_receipt)).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
