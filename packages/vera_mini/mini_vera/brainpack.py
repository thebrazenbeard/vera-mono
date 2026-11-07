"""Immutable, offline transport for explicitly authorized UTF-8 text files.

BrainPack packages content-addressed gzip blobs with a SHA-256 manifest. It
does not crawl directories, index documents, or write to assistant memory.
Every read verifies the stored and original content hashes.

This is integrity checking, not signed provenance or access control. Revocation
and deletion of a published immutable package are external responsibilities.
On Windows, component checks detect ordinary symlinks, junctions, and hardlinks
but cannot eliminate TOCTOU races against a concurrent hostile local writer;
the chosen source and destination trees must be access-controlled. NTFS
alternate data streams are not included in physical package byte accounting.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Iterable


DEFAULT_MAX_PACK_BYTES = 3 * 1024**3
DEFAULT_MAX_FILE_BYTES = 2 * 1024**2
MAX_DOCUMENTS = 10_000
MAX_MANIFEST_BYTES = 8 * 1024**2
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)


class BrainPackError(ValueError):
    """Unsafe source, corrupt package, or exceeded package limit."""


def _relative_name(value: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise BrainPackError("expected a root-relative POSIX file path")
    parts = value.split("/")
    if any(not part or part in (".", "..") or part.startswith(".") or
           part.endswith((".", " ")) or
           any(ord(ch) < 32 or ord(ch) == 127 or ch in '<>:"|?*'
               for ch in part) for part in parts):
        raise BrainPackError("unsafe or hidden file path")
    for part in parts:
        basename = part.split(".", 1)[0].upper()
        if basename in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
                r"(?:COM|LPT)[1-9]", basename):
            raise BrainPackError("reserved Windows device path")
    return tuple(parts)


def _has_dir_fd() -> bool:
    return (os.name != "nt" and hasattr(os, "O_NOFOLLOW") and
            hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd)


def _link_like(path: Path, metadata: os.stat_result) -> bool:
    """Reject symlinks, Windows junctions, and all Windows reparse points."""
    if stat.S_ISLNK(metadata.st_mode):
        return True
    if hasattr(path, "is_junction") and path.is_junction():
        return True
    attrs = getattr(metadata, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _check_directory_path(path: Path) -> None:
    """Best-effort Windows fallback: lstat each ancestor without following links.

    A concurrent local attacker can swap directory components between checks
    and open; Windows callers must use an access-controlled source tree.
    """
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
            if not stat.S_ISDIR(metadata.st_mode) or _link_like(current, metadata):
                raise BrainPackError("directory contains unsafe link or non-directory")
        except OSError as exc:
            raise BrainPackError("directory missing or inaccessible") from exc


def _open_directory(path: Path) -> int | Path:
    """Use descriptor-safe POSIX traversal, or checked Windows path fallback."""
    if not path.is_absolute():
        raise BrainPackError("directory must be an absolute path")
    if any(component in (".", "..") for component in path.parts[1:]):
        raise BrainPackError("directory path contains traversal component")
    if not _has_dir_fd():
        _check_directory_path(path)
        return path
    try:
        fd = os.open(path.anchor, _DIR_FLAGS)
        for component in path.parts[1:]:
            next_fd = os.open(component, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except OSError as exc:
        try:
            os.close(fd)
        except (OSError, UnboundLocalError):
            pass
        raise BrainPackError("directory missing or contains unsafe link") from exc


def _close_directory(root: int | Path) -> None:
    if isinstance(root, int):
        os.close(root)


def _open_child_directory(root: int | Path, child: str) -> int | Path:
    if isinstance(root, int):
        try:
            return os.open(child, _DIR_FLAGS, dir_fd=root)
        except OSError as exc:
            raise BrainPackError("missing or unsafe package subdirectory") from exc
    result = root / child
    _check_directory_path(result)
    return result


def _list_directory(root: int | Path, location: Path) -> dict[str, os.stat_result]:
    """Enumerate only an explicitly selected BrainPack directory level."""
    found: dict[str, os.stat_result] = {}
    try:
        with os.scandir(root) as listing:
            for entry in listing:
                if entry.name in found:
                    raise BrainPackError("duplicate package directory entry")
                metadata = entry.stat(follow_symlinks=False)
                if _link_like(location / entry.name, metadata):
                    raise BrainPackError("linked or reparse-point package entry")
                found[entry.name] = metadata
                if len(found) > MAX_DOCUMENTS + 2:
                    raise BrainPackError("package has too many physical entries")
    except OSError as exc:
        raise BrainPackError("package directory cannot be verified") from exc
    return found


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns)


def _read_checked_path(root: Path, name: str, max_bytes: int) -> bytes:
    """Windows-compatible path read; checks links before and after opening.

    This is not a no-follow guarantee against an adversary concurrently
    replacing a checked component, unlike the POSIX dir_fd backend.
    """
    path = root.joinpath(*_relative_name(name))
    _check_directory_path(path.parent)
    try:
        before = path.lstat()
        if (_link_like(path, before) or not stat.S_ISREG(before.st_mode) or
                before.st_nlink != 1 or before.st_size > max_bytes):
            raise BrainPackError("source is linked, non-regular, or oversized")
        with os.fdopen(os.open(path, _FILE_FLAGS), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or
                    _identity(opened) != _identity(before)):
                raise BrainPackError("source changed during open")
            payload = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
        _check_directory_path(path.parent)
        last = path.lstat()
        if (_link_like(path, last) or len(payload) > max_bytes or
                len(payload) != before.st_size or
                _identity(after) != _identity(before) or
                _identity(last) != _identity(before)):
            raise BrainPackError("file changed or exceeded size limit during read")
        return payload
    except OSError as exc:
        raise BrainPackError("file missing or contains unsafe link") from exc


def _read_regular(root_fd: int | Path, name: str, max_bytes: int) -> bytes:
    if isinstance(root_fd, Path):
        return _read_checked_path(root_fd, name, max_bytes)
    parts = _relative_name(name)
    fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        leaf_fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=fd)
        with os.fdopen(leaf_fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                    before.st_size > max_bytes):
                raise BrainPackError("source is linked, non-regular, or oversized")
            payload = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
            if (len(payload) > max_bytes or len(payload) != before.st_size or
                    _identity(before) != _identity(after)):
                raise BrainPackError("file changed or exceeded size limit during read")
            return payload
    except OSError as exc:
        raise BrainPackError("file missing or contains unsafe link") from exc
    finally:
        os.close(fd)


def _digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _limits(max_pack_bytes: int, max_file_bytes: int) -> None:
    if (type(max_pack_bytes) is not int or not 1 <= max_pack_bytes <= DEFAULT_MAX_PACK_BYTES or
            type(max_file_bytes) is not int or not 1 <= max_file_bytes <= DEFAULT_MAX_FILE_BYTES):
        raise BrainPackError("invalid bounded pack/file limits")


def _destination_exists(target: Path) -> bool:
    """lstat also detects dangling links and junctions at a destination."""
    try:
        target.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise BrainPackError("cannot inspect destination") from exc
    return True


def _publish_no_replace(staging: Path, target: Path) -> None:
    """Publish directory atomically, refusing even an existing empty directory.

    Windows os.rename is no-replace; Linux requires renameat2 RENAME_NOREPLACE.
    Unknown platforms fail closed rather than silently clobber a destination.
    """
    try:
        if os.name == "nt":
            os.rename(staging, target)
        elif sys.platform.startswith("linux"):
            import ctypes

            libc = ctypes.CDLL(None, use_errno=True)
            try:
                renameat2 = libc.renameat2
            except AttributeError as exc:
                raise BrainPackError("atomic no-replace publication unavailable") from exc
            renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p,
                                  ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
            renameat2.restype = ctypes.c_int
            # AT_FDCWD=-100, RENAME_NOREPLACE=1 (Linux renameat2 contract).
            if renameat2(-100, os.fsencode(staging), -100, os.fsencode(target), 1) != 0:
                number = ctypes.get_errno()
                raise OSError(number, os.strerror(number), str(target))
        else:
            raise BrainPackError("atomic no-replace publication unavailable")
    except OSError as exc:
        raise BrainPackError("destination exists or atomic publication failed") from exc


def build_brainpack(source_root: str | Path, files: Iterable[str], destination: str | Path,
                    *, max_pack_bytes: int = DEFAULT_MAX_PACK_BYTES,
                    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES) -> dict:
    """Atomically create a new directory package from an explicit file allowlist.

    Neither source_root nor destination is scanned. Existing destinations are
    refused. The limit covers both source bytes and on-disk payload+manifest.
    """
    _limits(max_pack_bytes, max_file_bytes)
    if isinstance(files, (str, Path)):
        raise BrainPackError("files must be an explicit iterable of relative names")
    names: list[str] = []
    seen: set[str] = set()
    for name in files:
        if not isinstance(name, str):
            raise BrainPackError("file names must be strings")
        _relative_name(name)
        if name in seen:
            raise BrainPackError("duplicate allowlisted file")
        names.append(name)
        seen.add(name)
        if len(names) > MAX_DOCUMENTS:
            raise BrainPackError("too many explicitly selected files")
    if not names:
        raise BrainPackError("at least one authorized file is required")
    target = Path(destination)
    if not target.is_absolute() or _destination_exists(target):
        raise BrainPackError("destination must be a new absolute directory")
    # Validate parent through descriptors before creating anything.
    parent_fd = _open_directory(target.parent)
    _close_directory(parent_fd)
    root_fd = _open_directory(Path(source_root))
    staging: Path | None = None
    try:
        staging = Path(tempfile.mkdtemp(prefix=".brainpack-build-", dir=target.parent))
        (staging / "blobs").mkdir()
        documents: list[dict] = []
        compressed_seen: set[str] = set()
        total_source = 0
        total_stored = 0
        for name in sorted(names):
            payload = _read_regular(root_fd, name, max_file_bytes)
            if b"\x00" in payload:
                raise BrainPackError("binary source rejected")
            try:
                payload.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise BrainPackError("source must be UTF-8 text") from exc
            total_source += len(payload)
            if total_source > max_pack_bytes:
                raise BrainPackError("source bytes exceed package budget")
            digest = _digest(payload)
            blob_name = f"blobs/{digest}.gz"
            compressed = gzip.compress(payload, compresslevel=6, mtime=0)
            compressed_sha = _digest(compressed)
            if digest not in compressed_seen:
                (staging / blob_name).write_bytes(compressed)
                total_stored += len(compressed)
                compressed_seen.add(digest)
            documents.append({"path": name, "sha256": digest, "bytes": len(payload),
                              "blob": blob_name, "blob_sha256": compressed_sha,
                              "blob_bytes": len(compressed)})
            if total_stored > max_pack_bytes:
                raise BrainPackError("compressed bytes exceed package budget")
        manifest = {"format": "mini-vera-brainpack", "version": 1,
                    "max_pack_bytes": max_pack_bytes, "max_file_bytes": max_file_bytes,
                    "source_bytes": total_source, "documents": documents}
        encoded = (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")) + "\n").encode("utf-8")
        if len(encoded) > MAX_MANIFEST_BYTES or total_stored + len(encoded) > max_pack_bytes:
            raise BrainPackError("manifest exceeds package budget")
        (staging / "manifest.json").write_bytes(encoded)
        # Same-parent rename makes a completed package visible in one operation.
        if _destination_exists(target):
            raise BrainPackError("destination appeared during build")
        _publish_no_replace(staging, target)
        staging = None
        return manifest
    finally:
        _close_directory(root_fd)
        if staging is not None:
            shutil.rmtree(staging)


class BrainPack:
    """Read-only, hash-checking access to an immutable document package."""

    def __init__(self, directory: str | Path, *,
                 max_pack_bytes: int = DEFAULT_MAX_PACK_BYTES) -> None:
        _limits(max_pack_bytes, DEFAULT_MAX_FILE_BYTES)
        self._directory = Path(directory)
        root_fd = _open_directory(self._directory)
        try:
            raw = _read_regular(root_fd, "manifest.json", min(MAX_MANIFEST_BYTES, max_pack_bytes))
        finally:
            _close_directory(root_fd)
        try:
            manifest = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise BrainPackError("invalid manifest JSON") from exc
        if not isinstance(manifest, dict) or (manifest.get("format"), manifest.get("version")) != (
                "mini-vera-brainpack", 1):
            raise BrainPackError("unsupported BrainPack manifest")
        cap = manifest.get("max_pack_bytes")
        file_cap = manifest.get("max_file_bytes")
        _limits(cap, file_cap)
        if cap > max_pack_bytes:
            raise BrainPackError("package exceeds reader budget")
        docs = manifest.get("documents")
        if not isinstance(docs, list) or not 1 <= len(docs) <= MAX_DOCUMENTS:
            raise BrainPackError("invalid document list")
        names: set[str] = set()
        blob_specs: dict[str, tuple[str, int]] = {}
        source_bytes = 0
        for doc in docs:
            if not isinstance(doc, dict):
                raise BrainPackError("invalid document record")
            path = doc.get("path")
            if not isinstance(path, str):
                raise BrainPackError("invalid document path")
            _relative_name(path)
            if path in names:
                raise BrainPackError("duplicate document path")
            names.add(path)
            sha = doc.get("sha256")
            compressed_sha = doc.get("blob_sha256")
            nbytes = doc.get("bytes")
            compressed_bytes = doc.get("blob_bytes")
            if (not isinstance(sha, str) or not _HEX64.fullmatch(sha) or
                    not isinstance(compressed_sha, str) or not _HEX64.fullmatch(compressed_sha) or
                    type(nbytes) is not int or not 0 <= nbytes <= file_cap or
                    type(compressed_bytes) is not int or
                    not 1 <= compressed_bytes <= min(cap, file_cap + 1024) or
                    doc.get("blob") != f"blobs/{sha}.gz"):
                raise BrainPackError("invalid document hash, size, or blob path")
            source_bytes += nbytes
            spec = (compressed_sha, compressed_bytes)
            if sha in blob_specs and blob_specs[sha] != spec:
                raise BrainPackError("conflicting content-addressed blob")
            blob_specs[sha] = spec
        if (source_bytes != manifest.get("source_bytes") or source_bytes > cap or
                sum(spec[1] for spec in blob_specs.values()) + len(raw) > cap):
            raise BrainPackError("package size or manifest total mismatch")
        self.manifest = manifest
        self._manifest_bytes = len(raw)
        self._manifest_sha256 = _digest(raw)
        self._documents = {doc["path"]: doc for doc in docs}

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted(self._documents))

    def read(self, path: str) -> str:
        """Read a selected document with bounded decompression and both hashes."""
        doc = self._documents.get(path)
        if doc is None:
            raise BrainPackError("document not in BrainPack allowlist")
        root_fd = _open_directory(self._directory)
        try:
            blob = _read_regular(root_fd, doc["blob"], doc["blob_bytes"])
        finally:
            _close_directory(root_fd)
        if len(blob) != doc["blob_bytes"] or _digest(blob) != doc["blob_sha256"]:
            raise BrainPackError("compressed blob checksum mismatch")
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(blob)) as stream:
                payload = stream.read(doc["bytes"] + 1)
        except (OSError, EOFError) as exc:
            raise BrainPackError("invalid gzip blob") from exc
        if len(payload) != doc["bytes"] or _digest(payload) != doc["sha256"]:
            raise BrainPackError("document checksum or decompression limit mismatch")
        try:
            return payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise BrainPackError("invalid UTF-8 document") from exc

    def _verify_physical_tree(self) -> None:
        """Reject unlisted padding, unexpected subtrees, links and size overrun."""
        expected_blobs = {
            doc["blob"].removeprefix("blobs/"): doc["blob_bytes"]
            for doc in self._documents.values()
        }
        root = _open_directory(self._directory)
        try:
            current_manifest = _read_regular(root, "manifest.json", self._manifest_bytes)
            if (_digest(current_manifest) != self._manifest_sha256 or
                    len(current_manifest) != self._manifest_bytes):
                raise BrainPackError("manifest content changed since package open")
            entries = _list_directory(root, self._directory)
            if set(entries) != {"manifest.json", "blobs"}:
                raise BrainPackError("unexpected physical package entry")
            manifest_stat = entries["manifest.json"]
            if (not stat.S_ISREG(manifest_stat.st_mode) or
                    manifest_stat.st_nlink != 1 or
                    manifest_stat.st_size != self._manifest_bytes or
                    not stat.S_ISDIR(entries["blobs"].st_mode)):
                raise BrainPackError("invalid physical manifest or blob directory")
            child = _open_child_directory(root, "blobs")
            try:
                physical = _list_directory(child, self._directory / "blobs")
            finally:
                _close_directory(child)
            if set(physical) != set(expected_blobs):
                raise BrainPackError("unexpected or missing physical blob")
            total = manifest_stat.st_size
            for filename, metadata in physical.items():
                if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
                        metadata.st_size != expected_blobs[filename]):
                    raise BrainPackError("invalid physical blob size or link count")
                total += metadata.st_size
                if total > self.manifest["max_pack_bytes"]:
                    raise BrainPackError("physical BrainPack exceeds byte budget")
        finally:
            _close_directory(root)

    def verify(self) -> dict:
        """Validate every listed document; does not mutate the package."""
        self._verify_physical_tree()
        for path in self.paths:
            self.read(path)
        self._verify_physical_tree()
        return {"verified_documents": len(self.paths),
                "source_bytes": self.manifest["source_bytes"]}
