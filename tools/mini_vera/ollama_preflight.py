"""Conservative, opt-in Lappy Ollama 0.8B preflight and Mini-Vera launcher.

Only GET /api/tags and GET /api/ps are used during preflight. Neither loads
weights. An explicit --execute can hand off to the existing bounded local
session, but the checks are estimates, NOT a lock/lease or weight attestation.
"""

from __future__ import annotations

import argparse
import ctypes
from http.client import HTTPException
import json
import sys
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
    args = parser.parse_args(argv)
    if args.prompt is not None and not args.execute:
        parser.error("--prompt requires --execute; omit it for a read-only preflight")
    if args.execute and (not args.host_idle_confirmed or not args.prompt):
        parser.error("--execute needs --host-idle-confirmed and --prompt")
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
    print(json.dumps(receipt, sort_keys=True))
    if not args.execute:
        # Probe mode does not send a chat completion or perform model loading.
        return 0
    if receipt["status"] != "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE":
        print("Model is cold; --allow-cold-load required before inference", file=sys.stderr)
        return 2
    # TOCTOU remains: this is an immediate guard against known busy conditions,
    # not coordination with unrelated inference/training processes. The digest
    # forwarded to the composer is a declared tag, never a weight proof.
    return local_session.main([
        "--endpoint", args.endpoint, "--model", args.model,
        "--model-digest", receipt["ollama_tag_digest"],
        "--execute", "--host-idle-confirmed", "--prompt", args.prompt,
    ])


if __name__ == "__main__":
    raise SystemExit(main())
