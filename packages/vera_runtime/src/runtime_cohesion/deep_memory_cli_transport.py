"""Opt-in, read-only CLI transport for a *pinned* DeepMemoryStorage checkout.

The transport is an explicitly supplied dependency of DeepMemoryEvidenceAdapter.
It is not an installed provider, a current-memory writer, or an authority source.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .deep_memory_evidence import (
    EVIDENCE_SEARCH,
    EvidenceAuthorizationError,
    EvidenceContractError,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")


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

    def _verify_source_cut(self) -> Path:
        root = self._source_root
        if not root.is_dir():
            raise EvidenceContractError("Deep Memory source root is not a directory")
        try:
            top = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            ).stdout.strip()
            head = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            ).stdout.strip()
            status = subprocess.run(
                [
                    "git",
                    "-C",
                    str(root),
                    "status",
                    "--porcelain",
                    "--untracked-files=all",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            ).stdout
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise EvidenceContractError(
                "cannot attest Deep Memory source checkout"
            ) from exc
        if Path(top).resolve() != root or head != self._source_commit or status:
            raise EvidenceContractError(
                "Deep Memory source checkout is moved, unpinned, or dirty"
            )
        script = root / "tools" / "query_deep_memory.py"
        catalog = root / "tools" / "deep_memory_catalog.py"
        if any(not path.is_file() or path.is_symlink() for path in (script, catalog)):
            raise EvidenceContractError(
                "pinned Deep Memory search program is missing or linked"
            )
        return script

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

        script = self._verify_source_cut()
        args = [sys.executable, "-E", "-s", "-B", str(script), query]
        for scope in authorized_privacy_scopes:
            args.extend(["--authorized-privacy", scope])
        args.extend(["--limit", str(self._max_results), "--json"])
        try:
            completed = subprocess.run(
                args,
                cwd=self._source_root,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EvidenceContractError(
                "Deep Memory search execution unavailable"
            ) from exc
        self._verify_source_cut()
        if completed.returncode != 0:
            # The donor's stderr may contain private ledger data; do not surface it.
            raise EvidenceContractError("Deep Memory evidence search failed")
        if len(completed.stdout.encode("utf-8")) > self._max_result_bytes:
            raise EvidenceContractError(
                "Deep Memory result exceeds configured byte limit"
            )
        try:
            result = json.loads(completed.stdout, object_pairs_hook=_unique_json_object)
        except (ValueError, json.JSONDecodeError) as exc:
            raise EvidenceContractError(
                "Deep Memory search emitted invalid JSON"
            ) from exc
        if not isinstance(result, dict):
            raise EvidenceContractError("Deep Memory result must be an object")
        return result
