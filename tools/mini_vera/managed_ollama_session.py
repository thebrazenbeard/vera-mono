"""Opt-in owned, CPU-only Ollama lifecycle for the guarded local 4B console.

No downloads, no model registration or weight change, no system-service edits.
Only an already-installed Ollama binary and existing model registry may be used.
The preflight is a RAM snapshot, never a host lease or neural attestation.
"""
from __future__ import annotations

import argparse
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time

from . import conversation_console, ollama_preflight
from .windows_owned_job import KillOnCloseJob, JobRefused

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_MIN_START_FREE_BYTES = 8 * ollama_preflight.GIB


class ManagedSessionRefused(ValueError):
    """Fail closed before, during or after owned service startup."""


def _safe_existing_path(path: Path, *, directory: bool) -> Path:
    """Reject explicit filesystem redirections and missing source assets."""
    for part in (path, *path.parents):
        try:
            info = os.lstat(part)
        except OSError as exc:
            raise ManagedSessionRefused("missing Ollama asset path") from exc
        if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0) & 0x400):
            raise ManagedSessionRefused("symlink or junction asset path refused")
    if not (path.is_dir() if directory else path.is_file()):
        raise ManagedSessionRefused("Ollama executable or model registry missing")
    return path.resolve(strict=True)


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conn:
        conn.settimeout(0.6)
        return conn.connect_ex(("127.0.0.1", port)) == 0


def wait_ready(port: int, proc: subprocess.Popen, timeout_seconds: float = 20) -> bool:
    """Only trust readiness while the newly owned process remains alive."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        connection = HTTPConnection("127.0.0.1", port, timeout=0.9)
        try:
            connection.request("GET", "/api/version")
            response = connection.getresponse()
            data = response.read(1025)
            if response.status == 200 and len(data) <= 1024:
                result = json.loads(data)
                if type(result) is dict and type(result.get("version")) is str:
                    return True
        except (OSError, ValueError):
            pass
        finally:
            connection.close()
        time.sleep(0.25)
    return False


def _terminate_owned(proc: subprocess.Popen) -> None:
    """Stop only this handle; never enumerate or kill shared Ollama processes."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-exe", type=Path, required=True,
                        help="Explicit existing local Ollama executable (no install)")
    parser.add_argument("--models-root", type=Path, required=True,
                        help="Explicit pre-existing isolated Ollama model registry")
    parser.add_argument("--port", type=int, required=True,
                        help="Unused private numeric loopback port, never 11434")
    parser.add_argument("--model", required=True,
                        help="Already-installed model alias in that registry")
    parser.add_argument("--expected-tag-digest", required=True,
                        help="Exact preobserved Ollama registry tag digest (not tensors)")
    parser.add_argument("--start-owned-server", action="store_true",
                        help="Explicitly permit a new owned local Ollama server process")
    parser.add_argument("--confirm-host-idle", action="store_true",
                        help="Freshly confirmed exclusive operator willingness to use free RAM")
    parser.add_argument("--allow-cold-load", action="store_true",
                        help="Explicitly permit this server to load a cold 4B model")
    parser.add_argument("--compact-dialogue", action="store_true",
                        help="Explicit compact Vera prompt (also managed 4B default)")
    parser.add_argument("--full-governed-dialogue", action="store_true",
                        help="Diagnostic opt-out of managed compact default; full prompt may be verbose")
    parser.add_argument("--ollama-disable-thinking", action="store_true")
    parser.add_argument("--prompt", help="One turn; omit for interactive session")
    args = parser.parse_args(argv)

    if args.compact_dialogue and args.full_governed_dialogue:
        print("Refused: conflicting dialogue modes; select only one.",
              file=sys.stderr)
        return 2
    if not (args.start_owned_server and args.confirm_host_idle
            and args.allow_cold_load):
        print("Refused: all three explicit start, idle, cold-load permissions required.",
              file=sys.stderr)
        return 2
    if (not 1024 < args.port <= 65535 or args.port == 11434
            or _DIGEST.fullmatch(args.expected_tag_digest) is None
            or _MODEL.fullmatch(args.model) is None):
        print("Refused: invalid dedicated port, model name or expected tag digest.",
              file=sys.stderr)
        return 2
    try:
        exe = _safe_existing_path(args.ollama_exe, directory=False)
        models = _safe_existing_path(args.models_root, directory=True)
        if _port_open(args.port):
            raise ManagedSessionRefused("chosen loopback port already has a listener")
        # This early check is separate from the exact model-size + RAM preflight
        # performed by conversation_console after Ollama becomes responsive.
        available = min(ollama_preflight.windows_free_physical_bytes(),
                        ollama_preflight.windows_free_physical_bytes())
        if available < _MIN_START_FREE_BYTES:
            raise ManagedSessionRefused("insufficient free physical RAM before server start")
    except (ManagedSessionRefused, OSError, ValueError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env.update({
        "OLLAMA_HOST": f"127.0.0.1:{args.port}",
        "OLLAMA_MODELS": str(models),
        "OLLAMA_NO_CLOUD": "true",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NUM_PARALLEL": "1",
        "CUDA_VISIBLE_DEVICES": "-1",
        "ROCR_VISIBLE_DEVICES": "-1",
    })
    if sys.platform != "win32":
        print("Refused: managed session currently supports Windows only.",
              file=sys.stderr)
        return 2

    proc = None
    job = None
    result = 2
    try:
        # If the controller is forcibly terminated, Windows closes this
        # non-inherited job handle and kills only the associated process tree.
        job = KillOnCloseJob()
        proc = subprocess.Popen(
            [str(exe), "serve"], env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        job.bind(proc.pid)
        if not wait_ready(args.port, proc):
            raise ManagedSessionRefused("owned Ollama failed readiness or exited")
        options = [
            "--endpoint", f"http://127.0.0.1:{args.port}/v1",
            "--model", args.model,
            "--expected-tag-digest", args.expected_tag_digest,
            "--candidate-4b", "--max-output-tokens", "128",
            "--confirm-host-idle", "--allow-cold-load",
        ]
        # A real experimenter-authored 4B pilot observed severe truncation and
        # a false persistence claim under the full prompt (3/4 incomplete),
        # versus four completed replies with the existing compact prompt.
        # Scope this default to the owned 4B launcher; other modes unchanged.
        if not args.full_governed_dialogue:
            options.append("--compact-dialogue")
        if args.ollama_disable_thinking:
            options.append("--ollama-disable-thinking")
        if args.prompt is not None:
            options.extend(["--prompt", args.prompt])
        # Existing console owns independent model-tag, RAM, resident-process,
        # and right-before-handoff checks. The client owns no model privilege.
        result = conversation_console.main(options)
    except (OSError, ManagedSessionRefused) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        result = 2
    finally:
        try:
            if proc is not None:
                _terminate_owned(proc)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"Owned process cleanup failed: {exc}", file=sys.stderr)
            result = 2
        finally:
            if job is not None:
                job.close()  # KILL_ON_JOB_CLOSE also guards abrupt parent death.
        if proc is not None and _port_open(args.port):
            print("Warning: loopback port remains occupied after owned server cleanup; "
                  "ownership of remaining listener UNKNOWN.", file=sys.stderr)
            result = 2
    return result


if __name__ == "__main__":
    raise SystemExit(main())
