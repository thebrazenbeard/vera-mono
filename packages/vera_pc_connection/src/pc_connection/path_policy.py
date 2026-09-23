from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath
import re
from typing import Final


class PathPolicyError(ValueError):
    """Raised when a path request crosses the PCCC lexical boundary."""


READ_ROOTS: Final[dict[str, PureWindowsPath]] = {
    "VERA_ROOT": PureWindowsPath("C:/VERA"),
    "USER_VERA_ROOT": PureWindowsPath("C:/Users/patri/VERA"),
}
WRITE_ROOT_ID: Final[str] = "PCCC_WRITE_ROOT_V1"
WRITE_ROOT: Final[PureWindowsPath] = PureWindowsPath("C:/VERA/PCCC")

_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_CONTROL = re.compile(r"[\x00-\x1f]")
_FORBIDDEN_CHARS = set('<>:"|?*')


def _casefold_parts(path: PureWindowsPath) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.parts)


def _is_within(path: PureWindowsPath, root: PureWindowsPath) -> bool:
    path_parts = _casefold_parts(path)
    root_parts = _casefold_parts(root)
    return path_parts[: len(root_parts)] == root_parts


def _validate_relative(value: str) -> PureWindowsPath:
    if not isinstance(value, str) or not value:
        raise PathPolicyError("relative_path must be a nonempty string")
    if value.startswith(("\\\\", "/", "\\")):
        raise PathPolicyError("UNC, rooted, and device paths are forbidden")
    if value.startswith(("//", "\\\\?\\", "\\\\.\\", "\\??\\")):
        raise PathPolicyError("device and NT namespaces are forbidden")
    if ":" in value:
        raise PathPolicyError("drive changes and alternate data streams are forbidden")
    if _CONTROL.search(value):
        raise PathPolicyError("control characters are forbidden")

    normalized = value.replace("/", "\\")
    candidate = PureWindowsPath(normalized)
    if candidate.is_absolute() or candidate.drive or candidate.root:
        raise PathPolicyError("absolute paths are forbidden")
    if not candidate.parts:
        raise PathPolicyError("relative_path must name a target")

    for part in candidate.parts:
        if part in {"", ".", ".."}:
            raise PathPolicyError("dot segments are forbidden")
        if part[-1] in {" ", "."}:
            raise PathPolicyError("trailing dot or space is forbidden")
        if any(char in _FORBIDDEN_CHARS for char in part):
            raise PathPolicyError("forbidden Windows path character")
        stem = part.split(".", 1)[0].upper()
        if stem in _RESERVED_NAMES:
            raise PathPolicyError("reserved Windows device name")
    return candidate


@dataclass(frozen=True)
class AuthorizedPath:
    root_id: str
    relative_path: str
    absolute_path: PureWindowsPath


def resolve_remote_read(root_id: str, relative_path: str) -> AuthorizedPath:
    """Resolve a remote read without exposing the writable runtime subtree.

    This is a lexical precheck only. The Windows adapter must additionally open
    by handle, reject reparse points and hard links, inspect the final path and
    file identity, and revalidate after the operation.
    """

    try:
        root = READ_ROOTS[root_id]
    except KeyError as exc:
        raise PathPolicyError("unknown read root alias") from exc
    relative = _validate_relative(relative_path)
    absolute = root / relative

    if not _is_within(absolute, root):
        raise PathPolicyError("path escaped the selected read root")
    if _is_within(absolute, WRITE_ROOT):
        raise PathPolicyError(
            "remote reads may not expose the writable PCCC runtime subtree"
        )
    return AuthorizedPath(root_id, str(relative), absolute)


def resolve_runtime_write(relative_path: str) -> AuthorizedPath:
    """Resolve an agent-owned write below the one authorized writable root."""

    relative = _validate_relative(relative_path)
    absolute = WRITE_ROOT / relative
    if not _is_within(absolute, WRITE_ROOT):
        raise PathPolicyError("path escaped the PCCC write root")
    return AuthorizedPath(WRITE_ROOT_ID, str(relative), absolute)


__all__ = [
    "AuthorizedPath",
    "PathPolicyError",
    "READ_ROOTS",
    "WRITE_ROOT",
    "WRITE_ROOT_ID",
    "resolve_remote_read",
    "resolve_runtime_write",
]
