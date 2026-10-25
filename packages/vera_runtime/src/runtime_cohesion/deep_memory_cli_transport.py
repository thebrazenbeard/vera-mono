"""Opt-in, read-only CLI transport for a *pinned* DeepMemoryStorage checkout.

The transport is an explicitly supplied dependency of DeepMemoryEvidenceAdapter.
It is not an installed provider, a current-memory writer, or an authority source.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .deep_memory_evidence import (
    EVIDENCE_SEARCH,
    EvidenceAuthorizationError,
    EvidenceContractError,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MAX_SOURCE_FILES = 5_000
_MAX_SOURCE_BYTES = 64_000_000


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceContractError(f"duplicate provider JSON key: {key}")
        result[key] = value
    return result


class PinnedDeepMemoryCLITransport:
    """Execute only the scoped search CLI of one operator-selected source cut.

    The caller must separately authorize exact privacy scopes through
    EvidenceSearchRequest. Archive-wide audit is deliberately unsupported here.
    Dirty, moved, or unpinned source trees are rejected before subprocess launch.
    """

    def __init__(
        self,
        source_root: Path,
        *,
        source_repository: str,
        source_commit: str,
        timeout_seconds: float = 15.0,
        max_results: int = 10,
        max_result_bytes: int = 2_000_000,
    ) -> None:
        if not isinstance(source_repository, str) or not source_repository.strip():
            raise ValueError(
                "source_repository must identify the exact configured provider"
            )
        if not isinstance(source_commit, str) or not _SHA.fullmatch(source_commit):
            raise ValueError("source_commit must be an exact lowercase SHA-1 commit")
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError("timeout_seconds must be in (0, 60]")
        if type(max_results) is not int or not 0 < max_results <= 100:
            raise ValueError("max_results must be an integer in [1, 100]")
        if (
            type(max_result_bytes) is not int
            or not 1024 <= max_result_bytes <= 10_000_000
        ):
            raise ValueError("max_result_bytes must be in [1024, 10000000]")
        self._source_root = Path(source_root).resolve(strict=True)
        self._source_repository = source_repository
        self._source_commit = source_commit
        self._timeout_seconds = float(timeout_seconds)
        self._max_results = max_results
        self._max_result_bytes = max_result_bytes

    def _git(self, *arguments: str) -> bytes:
        # Ignore ambient Git identities/config and explicitly disable fsmonitor:
        # a repository's fsmonitor may itself be an executable program.
        git_env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "LC_ALL": "C",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
        return subprocess.run(
            [
                "git",
                "-C",
                str(self._source_root),
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                *arguments,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=git_env,
            timeout=self._timeout_seconds,
        ).stdout

    def _attest_source_files(self) -> dict[str, bytes]:
        """Compare actual bytes/path inventory to the pinned Git *tree*, not index.

        `git status` alone is insufficient: assume-unchanged/skip-worktree and
        ignored files can conceal executable code or extra ledger tranches.
        The returned checked bytes are materialized in a private snapshot for
        execution, preventing a working-tree change between check and dispatch.
        """
        root = self._source_root
        if not root.is_dir():
            raise EvidenceContractError("Deep Memory source root is not a directory")
        try:
            top = self._git("rev-parse", "--show-toplevel").decode("utf-8").strip()
            head = self._git("rev-parse", "HEAD").decode("ascii").strip()
            entries = self._git("ls-tree", "-r", "-z", self._source_commit)
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            UnicodeError,
        ) as exc:
            raise EvidenceContractError(
                "cannot attest Deep Memory source checkout"
            ) from exc
        if Path(top).resolve() != root or head != self._source_commit:
            raise EvidenceContractError(
                "Deep Memory source checkout is moved or unpinned"
            )
        tree: dict[str, str] = {}
        expected_directories: set[str] = set()
        for entry in entries.split(b"\x00"):
            if not entry:
                continue
            try:
                metadata, raw_path = entry.split(b"\t", 1)
                mode, entry_type, raw_digest = metadata.split(b" ", 2)
                name = raw_path.decode("utf-8")
            except (ValueError, UnicodeError) as exc:
                raise EvidenceContractError("malformed pinned Git tree entry") from exc
            relative = Path(name)
            if (
                mode not in (b"100644", b"100755")
                or entry_type != b"blob"
                or not _SHA.fullmatch(raw_digest.decode("ascii"))
                or relative.is_absolute()
                or "\\" in name
                or any(part in ("", ".", "..") for part in relative.parts)
                or name in tree
            ):
                raise EvidenceContractError(
                    "unsafe symlink, submodule, or path in pinned Git tree"
                )
            tree[name] = raw_digest.decode("ascii")
            expected_directories.update(
                parent.as_posix() for parent in relative.parents if parent != Path(".")
            )
        if not 0 < len(tree) <= _MAX_SOURCE_FILES:
            raise EvidenceContractError("pinned source file count is outside the bound")
        if (
            not {"tools/query_deep_memory.py", "tools/deep_memory_catalog.py"}
            <= tree.keys()
        ):
            raise EvidenceContractError("pinned Deep Memory search program is missing")

        def walk_error(exc: OSError) -> None:
            raise EvidenceContractError(
                "cannot enumerate complete Deep Memory checkout"
            ) from exc

        for directory, subdirs, files in os.walk(
            root, followlinks=False, onerror=walk_error
        ):
            here = Path(directory)
            if here == root:
                subdirs[:] = [name for name in subdirs if name != ".git"]
                files = [name for name in files if name != ".git"]
            for name in subdirs:
                child = here / name
                rel = child.relative_to(root).as_posix()
                if child.is_symlink() or rel not in expected_directories:
                    raise EvidenceContractError(
                        "untracked, ignored, or linked source directory"
                    )
            for name in files:
                child = here / name
                rel = child.relative_to(root).as_posix()
                if child.is_symlink() or rel not in tree or not child.is_file():
                    raise EvidenceContractError(
                        "untracked, ignored, or linked source file"
                    )

        checked: dict[str, bytes] = {}
        total_bytes = 0
        for name, expected_blob in tree.items():
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise EvidenceContractError("pinned source file missing or linked")
            try:
                content = path.read_bytes()
            except OSError as exc:
                raise EvidenceContractError("cannot read pinned source bytes") from exc
            total_bytes += len(content)
            if total_bytes > _MAX_SOURCE_BYTES:
                raise EvidenceContractError("pinned source snapshot exceeds byte limit")
            actual_blob = hashlib.sha1(
                b"blob " + str(len(content)).encode("ascii") + b"\x00" + content
            ).hexdigest()
            if actual_blob != expected_blob:
                raise EvidenceContractError(
                    "pinned source file content differs from Git tree"
                )
            checked[name] = content
        return checked

    def __call__(
        self,
        *,
        operation: str,
        query: str,
        privacy_mode: str,
        authorized_privacy_scopes: list[str],
        provider_source_binding: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation != EVIDENCE_SEARCH:
            raise EvidenceAuthorizationError(
                "only read-only evidence search is supported"
            )
        if privacy_mode != "AUTHORIZED_SCOPE_FILTER":
            raise EvidenceAuthorizationError(
                "CLI transport does not authorize archive-wide audit"
            )
        if (
            not isinstance(authorized_privacy_scopes, list)
            or not authorized_privacy_scopes
            or any(
                not isinstance(s, str)
                or not s.strip()
                or "\x00" in s
                or s.startswith("-")
                for s in authorized_privacy_scopes
            )
            or len(set(authorized_privacy_scopes)) != len(authorized_privacy_scopes)
        ):
            raise EvidenceAuthorizationError(
                "exact non-empty unique privacy scopes are required"
            )
        if (
            not isinstance(query, str)
            or not query.strip()
            or "\x00" in query
            or len(query) > 512
        ):
            raise EvidenceContractError("query must be bounded non-empty text")
        if (
            not isinstance(provider_source_binding, Mapping)
            or provider_source_binding.get("repository") != self._source_repository
            or provider_source_binding.get("commit") != self._source_commit
        ):
            raise EvidenceContractError(
                "provider source binding does not match configured pinned source"
            )

        checked_files = self._attest_source_files()
        with tempfile.TemporaryDirectory(
            prefix="vera-deepmemory-verified-"
        ) as temp_name:
            snapshot = Path(temp_name) / "source"
            for name, contents in checked_files.items():
                destination = snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(contents)
            cache = Path(temp_name) / "empty-pycache"
            cache.mkdir()
            script = snapshot / "tools" / "query_deep_memory.py"
            args = [
                sys.executable,
                "-E",
                "-s",
                "-B",
                "-X",
                "utf8",
                "-X",
                f"pycache_prefix={cache}",
                str(script),
            ]
            for scope in authorized_privacy_scopes:
                args.extend(["--authorized-privacy", scope])
            args.extend(["--limit", str(self._max_results), "--json", "--", query])
            # No ambient tokens, auth headers, Python path, or Git configuration
            # are inherited by the provider. Only OS interpreter prerequisites.
            allowed_env = (
                "PATH",
                "SystemRoot",
                "WINDIR",
                "TEMP",
                "TMP",
                "TMPDIR",
                "LANG",
            )
            child_env = {
                key: os.environ[key] for key in allowed_env if key in os.environ
            }
            try:
                child = subprocess.Popen(
                    args,
                    cwd=snapshot,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=child_env,
                )
            except OSError as exc:
                raise EvidenceContractError(
                    "Deep Memory search execution unavailable"
                ) from exc
            chunks: queue.Queue[bytes] = queue.Queue(maxsize=2)
            reader_done = threading.Event()
            reader_stop = threading.Event()
            reader_errors: list[OSError] = []

            def drain_stdout() -> None:
                try:
                    assert child.stdout is not None
                    while not reader_stop.is_set():
                        chunk = child.stdout.read(64 * 1024)
                        while not reader_stop.is_set():
                            try:
                                chunks.put(chunk, timeout=0.1)
                                break
                            except queue.Full:
                                continue
                        if not chunk:
                            break
                except OSError as exc:
                    reader_errors.append(exc)
                finally:
                    reader_done.set()

            reader = threading.Thread(target=drain_stdout, daemon=True)
            reader.start()
            deadline = time.monotonic() + self._timeout_seconds
            output = bytearray()
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise EvidenceContractError("Deep Memory search timed out")
                    try:
                        chunk = chunks.get(timeout=min(0.1, remaining))
                    except queue.Empty:
                        if reader_done.is_set() and chunks.empty():
                            break
                        continue
                    if not chunk:
                        break
                    # A bounded queue of two 64KiB chunks guarantees the
                    # producer cannot outrun the caller into unbounded memory.
                    if len(output) + len(chunk) > self._max_result_bytes:
                        raise EvidenceContractError(
                            "Deep Memory result exceeds configured byte limit"
                        )
                    output.extend(chunk)
                if reader_errors:
                    raise EvidenceContractError("Deep Memory stdout stream failed")
                if child.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
                    raise EvidenceContractError("Deep Memory evidence search failed")
                response_text = output.decode("utf-8")
            except subprocess.TimeoutExpired as exc:
                raise EvidenceContractError("Deep Memory search timed out") from exc
            except UnicodeError as exc:
                raise EvidenceContractError(
                    "Deep Memory emitted invalid UTF-8"
                ) from exc
            finally:
                reader_stop.set()
                if child.poll() is None:
                    try:
                        child.kill()
                    except OSError:
                        pass
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                reader.join(timeout=1)
                if not reader.is_alive() and child.stdout is not None:
                    child.stdout.close()
        try:
            result = json.loads(response_text, object_pairs_hook=_unique_json_object)
        except (ValueError, json.JSONDecodeError) as exc:
            raise EvidenceContractError(
                "Deep Memory search emitted invalid JSON"
            ) from exc
        if not isinstance(result, dict):
            raise EvidenceContractError("Deep Memory result must be an object")
        return result
