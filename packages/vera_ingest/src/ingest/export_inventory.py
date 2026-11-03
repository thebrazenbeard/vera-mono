"""Read-only, non-admitting inventory of local historical export files.

This intentionally does not call the ingestion pipeline, mutate a store, open
OneDrive offline placeholders, or assert that any content may be published.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile


# Windows cloud files can hydrate on opening. Refuse known offline/recall
# placeholders even when the operator explicitly enables local-byte reads.
_WINDOWS_CLOUD_FLAGS = (
    getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
    | getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    | 0x00040000  # FILE_ATTRIBUTE_RECALL_ON_OPEN
    | 0x00400000  # FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)
_MAX_ARCHIVE_MEMBERS = 2048
_MAX_ZIP_INPUT_BYTES = 2 * 1024 * 1024
_MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
# Heuristic suffix denial, not a content-based proof that nested archives are absent.
_NESTED_ARCHIVE_SUFFIXES = (
    ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz",
    ".jar", ".war", ".ear", ".whl", ".apk", ".epub",
    ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp",
)


def _is_cloud_or_reparse(metadata: os.stat_result) -> bool:
    attributes = getattr(metadata, "st_file_attributes", None)
    # Missing file-attribute evidence must not make a Windows placeholder
    # appear safe. POSIX stat results ordinarily have no such attribute.
    if attributes is None:
        return os.name == "nt"
    return bool(attributes & _WINDOWS_CLOUD_FLAGS)


def _has_nofollow_open() -> bool:
    # Windows Python builds ordinarily omit O_NOFOLLOW. Without an atomic
    # no-follow open, a path can become a cloud/reparse link after stat and
    # before os.open, potentially hydrating bytes before fstat can reject it.
    return bool(getattr(os, "O_NOFOLLOW", 0))


def _hash_small_local(path: Path, expected_size: int, limit: int) -> str | None:
    if expected_size > limit or not _has_nofollow_open():
        return None
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or _is_cloud_or_reparse(before):
            return None
        if before.st_size != expected_size or before.st_size > limit:
            return None
        digest = hashlib.sha256()
        counted = 0
        while True:
            block = os.read(fd, min(64 * 1024, limit + 1 - counted))
            if not block:
                break
            counted += len(block)
            if counted > limit:
                return None
            digest.update(block)
        after = os.fstat(fd)
        if counted != expected_size or after.st_size != before.st_size:
            return None
        return digest.hexdigest()
    finally:
        os.close(fd)


def _unsafe_zip_name(name: str) -> bool:
    # A ZIP member path is never extracted, but a future consumer must not be
    # tempted to mistake dangerous entries for safe-to-extract members.
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    return (
        not name
        or "\x00" in name
        or normalized.startswith("/")
        or (len(normalized) >= 2 and normalized[1] == ":")
        or ".." in parts
    )


def _inspect_zip_local(path: Path, expected_size: int) -> dict:
    result = {"status": "METADATA_ONLY", "members": 0, "declared_uncompressed_bytes": 0}
    reasons: set[str] = set()
    if not _has_nofollow_open():
        return {**result, "status": "REJECTED_METADATA", "reasons": ["NO_SAFE_NOFOLLOW_OPEN"]}
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | os.O_NOFOLLOW
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or _is_cloud_or_reparse(metadata)
                or metadata.st_size != expected_size
            ):
                reasons.add("CHANGED_OR_UNSAFE_FILE")
            else:
                with zipfile.ZipFile(handle, "r", allowZip64=True) as archive:
                    members = archive.infolist()
                    result["members"] = len(members)
                    if len(members) > _MAX_ARCHIVE_MEMBERS:
                        reasons.add("MEMBER_COUNT_LIMIT")
                    for item in members[: _MAX_ARCHIVE_MEMBERS + 1]:
                        if _unsafe_zip_name(item.filename):
                            reasons.add("UNSAFE_MEMBER_PATH")
                        if item.flag_bits & 1:
                            reasons.add("ENCRYPTED_MEMBER")
                        if stat.S_IFMT(item.external_attr >> 16) == stat.S_IFLNK:
                            reasons.add("SYMLINK_MEMBER")
                        if item.filename.lower().endswith(_NESTED_ARCHIVE_SUFFIXES):
                            reasons.add("NESTED_ARCHIVE_MEMBER")
                        result["declared_uncompressed_bytes"] += item.file_size
                        if result["declared_uncompressed_bytes"] > _MAX_UNCOMPRESSED_BYTES:
                            reasons.add("UNCOMPRESSED_SIZE_LIMIT")
                        if item.file_size and item.file_size > _MAX_COMPRESSION_RATIO * max(item.compress_size, 1):
                            reasons.add("COMPRESSION_RATIO_LIMIT")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, ValueError):
        reasons.add("CORRUPT_OR_UNREADABLE_ARCHIVE")
    result["status"] = "REJECTED_METADATA" if reasons else "STRUCTURE_BOUNDED"
    if reasons:
        result["reasons"] = sorted(reasons)
    return result


def inventory_exports(
    root: str | Path,
    *,
    max_files: int = 500,
    max_depth: int = 1,
    max_read_bytes: int = 1024 * 1024,
    hash_local: bool = False,
    inspect_zip_local: bool = False,
    include_names: bool = False,
) -> dict:
    """Produce a bounded local-only manifest. Never admit or store content.

    Byte reads require explicit opt-in, and each file must pass a Windows
    placeholder/reparse guard and the size cap. By default only metadata is
    inspected and names/hashes are omitted from the resulting JSON.
    """
    if max_files < 1 or max_depth < 0 or max_depth > 4 or max_read_bytes < 1:
        raise ValueError("invalid inventory limit")
    directory = Path(root)
    try:
        root_stat = directory.lstat()
    except OSError as exc:
        raise ValueError("root must be an existing local directory") from exc
    if not stat.S_ISDIR(root_stat.st_mode) or _is_cloud_or_reparse(root_stat):
        raise ValueError("root must be a non-reparse local directory")
    queue: list[tuple[Path, int]] = [(directory, 0)]
    entries: list[dict] = []
    scanned_entries = 0
    dirs_seen = 0
    duplicates: dict[str, str] = {}
    while queue:
        folder, depth = queue.pop(0)
        with os.scandir(folder) as iterator:
            children = []
            for child in iterator:
                children.append(child)
                scanned_entries += 1
                if scanned_entries > max_files:
                    raise ValueError("inventory entry limit exceeded")
            children.sort(key=lambda x: (x.name.casefold(), x.name))
        for child in children:
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError:
                # Preserve existence without exposing OS errors or paths.
                entries.append({"entry_id": f"f{len(entries)+1:05d}", "status": "UNREADABLE_METADATA"})
                continue
            if stat.S_ISDIR(metadata.st_mode) and not child.is_symlink() and not _is_cloud_or_reparse(metadata):
                dirs_seen += 1
                if depth < max_depth:
                    queue.append((Path(child.path), depth + 1))
                continue
            record = {
                "entry_id": f"f{len(entries)+1:05d}",
                "extension": Path(child.name).suffix.lower(),
                "size_bytes": metadata.st_size,
                "status": "METADATA_ONLY",
                "privacy": "UNREVIEWED",
                "data_rights": "UNVERIFIED",
                "admission": "NOT_GRANTED",
            }
            if include_names:
                record["relative_path"] = str(Path(child.path).relative_to(directory))
            if child.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                record["status"] = "SKIPPED_NONREGULAR"
            elif _is_cloud_or_reparse(metadata):
                record["status"] = "SKIPPED_CLOUD_OR_REPARSE"
            elif hash_local or (inspect_zip_local and record["extension"] == ".zip"):
                archive_limit = (
                    min(max_read_bytes, _MAX_ZIP_INPUT_BYTES)
                    if inspect_zip_local and record["extension"] == ".zip"
                    else max_read_bytes
                )
                if metadata.st_size > archive_limit:
                    record["status"] = "SKIPPED_READ_SIZE_LIMIT"
                elif not _has_nofollow_open():
                    record["status"] = "SKIPPED_NO_SAFE_NOFOLLOW_OPEN"
                else:
                    try:
                        if hash_local:
                            digest = _hash_small_local(Path(child.path), metadata.st_size, max_read_bytes)
                            if digest is None:
                                record["status"] = "SKIPPED_CHANGED_FILE"
                            else:
                                record["sha256"] = digest
                                if digest in duplicates:
                                    record["duplicate_of"] = duplicates[digest]
                                else:
                                    duplicates[digest] = record["entry_id"]
                        if inspect_zip_local and record["extension"] == ".zip" and record["status"] == "METADATA_ONLY":
                            record["archive"] = _inspect_zip_local(Path(child.path), metadata.st_size)
                    except OSError:
                        record["status"] = "SKIPPED_READ_FAILURE"
            entries.append(record)
    return {
        "schema": "VERA_EXPORT_INVENTORY_V1",
        "mode": "READ_ONLY_LOCAL_MANIFEST",
        "root": "REDACTED",
        "files": entries,
        "file_count": len(entries),
        "directory_count": dirs_seen,
        "manual_review_required": True,
        "public_release_authorized": False,
        "raw_content_ingested": False,
    }
