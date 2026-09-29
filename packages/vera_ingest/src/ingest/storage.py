from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from .canonical import canonical_digest, canonical_json, sha256_bytes
from .model import Artifact


class StoreConflict(RuntimeError):
    pass


class StoreIntegrityError(RuntimeError):
    pass


class FileSystemStore:
    def __init__(self, root: str | Path = ".ingest"):
        self.root = Path(root)
        self._ensure_directory_chain(self.root)

    @staticmethod
    def _is_link_like(path: Path) -> bool:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction is not None and is_junction())

    def _assert_no_managed_links(self, path: Path) -> None:
        path = Path(path)
        try:
            relative = path.relative_to(self.root)
        except ValueError as exc:
            raise StoreConflict(f"storage path escapes root: {path}") from exc

        current = self.root
        for part in relative.parts:
            current = current / part
            if self._is_link_like(current):
                raise StoreConflict(
                    f"managed storage path cannot be a symlink or junction: {current}"
                )

    def _ensure_directory_chain(self, path: Path) -> None:
        path = Path(path)
        self._assert_no_managed_links(path)
        if path.exists():
            if not path.is_dir():
                raise NotADirectoryError(path)
            return

        missing: list[Path] = []
        cursor = path
        while not cursor.exists():
            missing.append(cursor)
            parent = cursor.parent
            if parent == cursor:
                break
            cursor = parent

        if cursor.exists() and not cursor.is_dir():
            raise NotADirectoryError(cursor)

        for directory in reversed(missing):
            try:
                directory.mkdir()
            except FileExistsError:
                if not directory.is_dir():
                    raise
            self._assert_no_managed_links(directory)
            self._fsync_directory(directory.parent)

    @staticmethod
    def _fsync_directory(path: Path) -> bool:
        if os.name == "nt":
            return False
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            fd = os.open(path, flags)
        except OSError:
            return False
        try:
            os.fsync(fd)
        except OSError:
            return False
        finally:
            os.close(fd)
        return True

    def _atomic_create(self, path: Path, data: bytes) -> bool:
        self._ensure_directory_chain(path.parent)
        self._assert_no_managed_links(path)
        if path.exists():
            try:
                self._verify_managed_sha256(
                    path,
                    expected_size=len(data),
                    expected_sha256=sha256_bytes(data),
                )
            except (FileNotFoundError, StoreIntegrityError) as exc:
                raise StoreConflict(
                    f"immutable path collision: {path}"
                ) from exc
            return False
        fd, temp_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            self._assert_no_managed_links(path.parent)
            try:
                os.link(temp_name, path)
            except FileExistsError:
                self._assert_no_managed_links(path)
                try:
                    self._verify_managed_sha256(
                        path,
                        expected_size=len(data),
                        expected_sha256=sha256_bytes(data),
                    )
                except (FileNotFoundError, StoreIntegrityError) as exc:
                    raise StoreConflict(
                        f"immutable path collision: {path}"
                    ) from exc
                return False
            self._fsync_directory(path.parent)
            return True
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def cleanup_stale_temp_files(
        self,
        *,
        older_than_seconds: float = 86400.0,
    ) -> dict[str, int]:
        if not math.isfinite(older_than_seconds) or older_than_seconds < 0:
            raise ValueError(
                "older_than_seconds must be finite and non-negative"
            )

        cutoff = time.time() - older_than_seconds
        files_removed = 0
        bytes_removed = 0

        for dirpath, dirnames, filenames in os.walk(
            self.root,
            topdown=True,
            followlinks=False,
        ):
            directory = Path(dirpath)
            dirnames[:] = [
                name
                for name in dirnames
                if not self._is_link_like(directory / name)
            ]

            for name in filenames:
                if not name.startswith(".tmp-"):
                    continue
                path = directory / name
                if self._is_link_like(path):
                    continue
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    continue
                if info.st_mtime > cutoff:
                    continue
                try:
                    path.unlink()
                except FileNotFoundError:
                    continue
                files_removed += 1
                bytes_removed += info.st_size
                self._fsync_directory(path.parent)

        return {
            "files_removed": files_removed,
            "bytes_removed": bytes_removed,
        }

    @staticmethod
    def _read_signature(value) -> tuple[int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    @staticmethod
    def _content_read_signature(value) -> tuple[int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
        )

    def _read_managed_bytes(
        self,
        path: Path,
        *,
        expected_size: int | None = None,
    ) -> bytes:
        path = Path(path)
        self._assert_no_managed_links(path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise StoreIntegrityError("managed storage read failed") from exc

        try:
            opened = os.fstat(fd)
            if (
                expected_size is not None
                and opened.st_size != expected_size
            ):
                raise StoreIntegrityError(
                    "managed storage object size differs before read"
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            data = b"".join(chunks)
            final = os.fstat(fd)
            if self._read_signature(final) != self._read_signature(opened):
                raise StoreIntegrityError(
                    "managed storage object changed during read"
                )
            if len(data) != opened.st_size:
                raise StoreIntegrityError(
                    "managed storage object size changed during read"
                )
            return data
        except StoreIntegrityError:
            raise
        except OSError as exc:
            raise StoreIntegrityError("managed storage read failed") from exc
        finally:
            os.close(fd)

    def _verify_managed_sha256(
        self,
        path: Path,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> None:
        path = Path(path)
        self._assert_no_managed_links(path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise StoreIntegrityError("managed storage read failed") from exc

        try:
            opened = os.fstat(fd)
            if opened.st_size != expected_size:
                raise StoreIntegrityError(
                    "managed storage object size differs before read"
                )

            digest = hashlib.sha256()
            observed_size = 0
            while True:
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    break
                observed_size += len(chunk)
                if observed_size > expected_size:
                    raise StoreIntegrityError(
                        "managed storage object grew during verification"
                    )
                digest.update(chunk)

            final = os.fstat(fd)
            if (
                self._content_read_signature(final)
                != self._content_read_signature(opened)
            ):
                raise StoreIntegrityError(
                    "managed storage object changed during read"
                )
            if observed_size != opened.st_size:
                raise StoreIntegrityError(
                    "managed storage object size changed during read"
                )
            if digest.hexdigest() != expected_sha256:
                raise StoreIntegrityError(
                    "artifact digest does not match bytes"
                )
        except StoreIntegrityError:
            raise
        except OSError as exc:
            raise StoreIntegrityError("managed storage read failed") from exc
        finally:
            os.close(fd)

    def _read_canonical_json(
        self,
        category: str,
        record_id: str,
    ) -> dict[str, Any]:
        path = self.root / category / f"{record_id}.json"
        data = self._read_managed_bytes(path)
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoreIntegrityError(
                f"{category} object is not valid UTF-8 JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise StoreIntegrityError(
                f"{category} object is not a JSON object"
            )
        try:
            canonical = (canonical_json(payload) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise StoreIntegrityError(
                f"{category} object is not strict canonical JSON"
            ) from exc
        if data != canonical:
            raise StoreIntegrityError(
                f"{category} object bytes are not canonical"
            )
        return payload

    def _verify_artifact(
        self,
        value: dict[str, Any],
        *,
        expected_kind: str | None = None,
    ) -> bytes:
        if not isinstance(value, dict):
            raise StoreIntegrityError("artifact metadata is not an object")
        digest = value.get("sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise StoreIntegrityError("artifact sha256 is invalid")
        expected_id = f"sha256:{digest}"
        expected_locator = (
            Path("blobs") / "sha256" / digest[:2] / digest
        ).as_posix()
        if value.get("artifact_id") != expected_id:
            raise StoreIntegrityError("artifact id does not match sha256")
        if value.get("storage_locator") != expected_locator:
            raise StoreIntegrityError(
                "artifact storage locator does not match sha256"
            )
        if expected_kind is not None and value.get("kind") != expected_kind:
            raise StoreIntegrityError(
                f"artifact kind is not {expected_kind}"
            )
        size = value.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise StoreIntegrityError("artifact size_bytes is invalid")
        self._verify_managed_sha256(
            self.root / expected_locator,
            expected_size=size,
            expected_sha256=digest,
        )

    def put_blob_stream(
        self,
        chunks,
        *,
        media_type: str,
        kind: str,
        max_bytes: int,
    ) -> tuple[Artifact, bool]:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")

        staging_dir = self.root / "blobs" / "sha256"
        self._ensure_directory_chain(staging_dir)
        self._assert_no_managed_links(staging_dir)
        fd, temp_name = tempfile.mkstemp(
            prefix=".tmp-",
            dir=staging_dir,
        )
        temp_path = Path(temp_name)
        digest = hashlib.sha256()
        size_bytes = 0

        try:
            with os.fdopen(fd, "wb") as handle:
                for chunk in chunks:
                    if not isinstance(
                        chunk,
                        (bytes, bytearray, memoryview),
                    ):
                        raise TypeError(
                            "stream chunks must be bytes-like"
                        )
                    if not chunk:
                        continue
                    data = bytes(chunk)
                    next_size = size_bytes + len(data)
                    if next_size > max_bytes:
                        raise ValueError(
                            f"stream exceeds max_bytes={max_bytes}"
                        )
                    handle.write(data)
                    digest.update(data)
                    size_bytes = next_size

                handle.flush()
                os.fsync(handle.fileno())

            hex_digest = digest.hexdigest()
            relative = (
                Path("blobs")
                / "sha256"
                / hex_digest[:2]
                / hex_digest
            )
            final_path = self.root / relative
            self._ensure_directory_chain(final_path.parent)
            self._assert_no_managed_links(final_path)

            if final_path.exists():
                try:
                    self._verify_managed_sha256(
                        final_path,
                        expected_size=size_bytes,
                        expected_sha256=hex_digest,
                    )
                except (
                    FileNotFoundError,
                    StoreIntegrityError,
                ) as exc:
                    raise StoreConflict(
                        f"immutable path collision: {final_path}"
                    ) from exc
                created = False
            else:
                try:
                    os.link(temp_path, final_path)
                except FileExistsError:
                    self._assert_no_managed_links(final_path)
                    try:
                        self._verify_managed_sha256(
                            final_path,
                            expected_size=size_bytes,
                            expected_sha256=hex_digest,
                        )
                    except (
                        FileNotFoundError,
                        StoreIntegrityError,
                    ) as exc:
                        raise StoreConflict(
                            f"immutable path collision: {final_path}"
                        ) from exc
                    created = False
                else:
                    self._fsync_directory(final_path.parent)
                    created = True

            return (
                Artifact(
                    artifact_id=f"sha256:{hex_digest}",
                    sha256=hex_digest,
                    size_bytes=size_bytes,
                    media_type=media_type,
                    kind=kind,
                    storage_locator=relative.as_posix(),
                ),
                created,
            )
        finally:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def read_blob_bytes(self, artifact: Artifact) -> bytes:
        digest = artifact.sha256
        expected_id = f"sha256:{digest}"
        expected_locator = (
            Path("blobs") / "sha256" / digest[:2] / digest
        ).as_posix()
        if artifact.artifact_id != expected_id:
            raise StoreIntegrityError("artifact id does not match sha256")
        if artifact.storage_locator != expected_locator:
            raise StoreIntegrityError(
                "artifact storage locator does not match sha256"
            )
        data = self._read_managed_bytes(
            self.root / expected_locator,
            expected_size=artifact.size_bytes,
        )
        if sha256_bytes(data) != digest:
            raise StoreIntegrityError(
                "artifact digest does not match bytes"
            )
        return data

    def put_blob(self, data: bytes, *, media_type: str, kind: str) -> tuple[Artifact, bool]:
        digest = sha256_bytes(data)
        relative = Path("blobs") / "sha256" / digest[:2] / digest
        created = self._atomic_create(self.root / relative, data)
        return (
            Artifact(
                artifact_id=f"sha256:{digest}",
                sha256=digest,
                size_bytes=len(data),
                media_type=media_type,
                kind=kind,
                storage_locator=relative.as_posix(),
            ),
            created,
        )

    def _put_json(self, category: str, record_id: str, value: dict[str, Any]) -> bool:
        data = (canonical_json(value) + "\n").encode("utf-8")
        return self._atomic_create(self.root / category / f"{record_id}.json", data)

    def put_record(self, ingest_id: str, value: dict[str, Any]) -> bool:
        return self._put_json("records", ingest_id, value)

    def put_receipt(self, receipt_id: str, value: dict[str, Any]) -> bool:
        return self._put_json("receipts", receipt_id, value)

    def put_derivation(self, derivation_id: str, value: dict[str, Any]) -> bool:
        return self._put_json("derivations", derivation_id, value)

    def has_record(self, ingest_id: str) -> bool:
        return (self.root / "records" / f"{ingest_id}.json").is_file()

    @staticmethod
    def _is_ingest_id(value: str) -> bool:
        return (
            len(value) == 64
            and all(ch in "0123456789abcdef" for ch in value)
        )

    def audit_records(self) -> dict[str, Any]:
        records_dir = self.root / "records"
        issues: list[dict[str, Any]] = []
        records_checked = 0
        records_ok = 0

        if not records_dir.exists():
            return {
                "schema": "INGEST_RECORD_AUDIT_V1",
                "status": "PASS",
                "records_checked": 0,
                "records_ok": 0,
                "records_corrupt": 0,
                "issues": [],
            }

        try:
            self._assert_no_managed_links(records_dir)
        except StoreConflict as exc:
            return {
                "schema": "INGEST_RECORD_AUDIT_V1",
                "status": "CORRUPT",
                "records_checked": 0,
                "records_ok": 0,
                "records_corrupt": 1,
                "issues": [
                    {
                        "entry": "records",
                        "ingest_id": None,
                        "error": str(exc),
                    }
                ],
            }

        if not records_dir.is_dir():
            return {
                "schema": "INGEST_RECORD_AUDIT_V1",
                "status": "CORRUPT",
                "records_checked": 0,
                "records_ok": 0,
                "records_corrupt": 1,
                "issues": [
                    {
                        "entry": "records",
                        "ingest_id": None,
                        "error": "records path is not a directory",
                    }
                ],
            }

        try:
            entries = sorted(records_dir.iterdir(), key=lambda value: value.name)
        except OSError as exc:
            return {
                "schema": "INGEST_RECORD_AUDIT_V1",
                "status": "CORRUPT",
                "records_checked": 0,
                "records_ok": 0,
                "records_corrupt": 1,
                "issues": [
                    {
                        "entry": "records",
                        "ingest_id": None,
                        "error": (
                            exc.strerror
                            or "records directory enumeration failed"
                        ),
                    }
                ],
            }

        for entry in entries:
            ingest_id = (
                entry.name[:-5]
                if entry.name.endswith(".json")
                else None
            )
            if (
                self._is_link_like(entry)
                or not entry.is_file()
                or ingest_id is None
                or not self._is_ingest_id(ingest_id)
            ):
                issues.append(
                    {
                        "entry": entry.name,
                        "ingest_id": None,
                        "error": "unexpected records directory entry",
                    }
                )
                continue

            records_checked += 1
            try:
                self.get_record(ingest_id)
            except (FileNotFoundError, StoreIntegrityError) as exc:
                issues.append(
                    {
                        "entry": entry.name,
                        "ingest_id": ingest_id,
                        "error": str(exc),
                    }
                )
            else:
                records_ok += 1

        return {
            "schema": "INGEST_RECORD_AUDIT_V1",
            "status": "PASS" if not issues else "CORRUPT",
            "records_checked": records_checked,
            "records_ok": records_ok,
            "records_corrupt": len(issues),
            "issues": issues,
        }

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        payload = self._read_canonical_json("receipts", receipt_id)
        if payload.get("schema") != "INGEST_STAGE_RECEIPT_V1":
            raise StoreIntegrityError("receipt schema is invalid")
        if payload.get("receipt_id") != receipt_id:
            raise StoreIntegrityError(
                "receipt id does not match storage key"
            )
        digest = payload.get("receipt_digest")
        if not isinstance(digest, str):
            raise StoreIntegrityError("receipt digest is missing")
        body = dict(payload)
        body.pop("receipt_digest", None)
        if canonical_digest(body) != digest:
            raise StoreIntegrityError(
                "receipt digest does not match receipt body"
            )
        return payload

    def get_derivation(self, derivation_id: str) -> dict[str, Any]:
        payload = self._read_canonical_json(
            "derivations",
            derivation_id,
        )
        if payload.get("schema") != "INGEST_DERIVATION_V1":
            raise StoreIntegrityError("derivation schema is invalid")
        if payload.get("derivation_id") != derivation_id:
            raise StoreIntegrityError(
                "derivation id does not match storage key"
            )
        if payload.get("relation") != "NORMALIZED_FROM":
            raise StoreIntegrityError(
                "derivation relation is unsupported"
            )

        receipt_id = payload.get("receipt_id")
        if not isinstance(receipt_id, str):
            raise StoreIntegrityError(
                "derivation receipt id is invalid"
            )
        receipt = self.get_receipt(receipt_id)
        if not isinstance(receipt.get("ingest_id"), str):
            raise StoreIntegrityError(
                "derivation receipt lacks ingest identity"
            )
        if (
            receipt.get("stage") != "normalize"
            or receipt.get("outcome") != "PASS"
        ):
            raise StoreIntegrityError(
                "derivation receipt is not normalize/PASS evidence"
            )
        parent_artifact_id = payload.get("parent_artifact_id")
        child_artifact_id = payload.get("child_artifact_id")
        if receipt.get("input_artifact_ids") != [
            parent_artifact_id
        ]:
            raise StoreIntegrityError(
                "derivation receipt input does not match parent artifact"
            )
        if receipt.get("output_artifact_ids") != [
            child_artifact_id
        ]:
            raise StoreIntegrityError(
                "derivation receipt output does not match child artifact"
            )
        normalizer_version = (receipt.get("details") or {}).get(
            "normalizer_version"
        )
        if not isinstance(normalizer_version, str):
            raise StoreIntegrityError(
                "derivation receipt lacks normalizer version"
            )
        expected = canonical_digest(
            {
                "relation": payload.get("relation"),
                "parent": payload.get("parent_artifact_id"),
                "child": payload.get("child_artifact_id"),
                "normalizer_version": normalizer_version,
            }
        )
        if expected != derivation_id:
            raise StoreIntegrityError(
                "derivation id does not match derivation body"
            )
        return payload

    def get_record(self, ingest_id: str) -> dict[str, Any]:
        payload = self._read_canonical_json("records", ingest_id)
        if payload.get("schema") != "INGEST_RECORD_V1":
            raise StoreIntegrityError("record schema is invalid")
        if payload.get("ingest_id") != ingest_id:
            raise StoreIntegrityError(
                "record ingest id does not match storage key"
            )

        source = payload.get("source")
        if not isinstance(source, dict):
            raise StoreIntegrityError("record source is invalid")
        source_identity = {
            key: source.get(key)
            for key in (
                "scheme",
                "locator",
                "adapter",
                "adapter_version",
                "source_identity",
            )
        }
        if not all(
            source_identity.get(key) is not None
            for key in (
                "scheme",
                "locator",
                "adapter",
                "adapter_version",
                "source_identity",
            )
        ):
            raise StoreIntegrityError(
                "record source identity is incomplete"
            )

        raw_artifact = payload.get("raw_artifact")
        self._verify_artifact(raw_artifact, expected_kind="raw")
        normalized_artifact = payload.get("normalized_artifact")
        if normalized_artifact is not None:
            self._verify_artifact(
                normalized_artifact,
                expected_kind="normalized",
            )

        receipt_ids = payload.get("receipt_ids")
        if not isinstance(receipt_ids, list) or not all(
            isinstance(value, str) for value in receipt_ids
        ):
            raise StoreIntegrityError("record receipt ids are invalid")
        if len(set(receipt_ids)) != len(receipt_ids):
            raise StoreIntegrityError("record receipt ids are duplicated")
        receipts = [self.get_receipt(value) for value in receipt_ids]

        acquire = [
            receipt
            for receipt in receipts
            if receipt.get("stage") == "acquire"
        ]
        if len(acquire) != 1:
            raise StoreIntegrityError(
                "record must reference exactly one acquire receipt"
            )
        acquire_details = acquire[0].get("details") or {}
        if acquire_details.get("source") != source:
            raise StoreIntegrityError(
                "record source does not match acquire receipt"
            )
        if acquire_details.get("size_bytes") != raw_artifact.get(
            "size_bytes"
        ):
            raise StoreIntegrityError(
                "record raw size does not match acquire receipt"
            )

        persist_raw = [
            receipt
            for receipt in receipts
            if receipt.get("stage") == "persist_raw"
        ]
        if len(persist_raw) != 1:
            raise StoreIntegrityError(
                "record must reference exactly one persist_raw receipt"
            )
        persist_details = persist_raw[0].get("details") or {}
        claimed_media_type = persist_details.get(
            "claimed_media_type"
        )
        if persist_details.get("media_type") != raw_artifact.get(
            "media_type"
        ):
            raise StoreIntegrityError(
                "record raw media type does not match persist receipt"
            )
        raw_artifact_id = raw_artifact.get("artifact_id")
        if raw_artifact_id not in (
            persist_raw[0].get("output_artifact_ids") or []
        ):
            raise StoreIntegrityError(
                "persist receipt does not reference record raw artifact"
            )

        identity = {
            "schema": "INGEST_IDENTITY_V1",
            "source": source_identity,
            "raw_sha256": raw_artifact.get("sha256"),
            "claimed_media_type": claimed_media_type,
            "normalizer_version": payload.get("normalizer_version"),
            "policy_id": payload.get("policy_id"),
        }
        if canonical_digest(identity) != ingest_id:
            raise StoreIntegrityError(
                "record ingest id does not match identity material"
            )

        if payload.get("evidence_class") != "DIRECT_SOURCE":
            raise StoreIntegrityError(
                "record evidence class is invalid"
            )
        warnings = payload.get("warnings")
        if not isinstance(warnings, list) or not all(
            isinstance(value, str) for value in warnings
        ):
            raise StoreIntegrityError("record warnings are invalid")
        expected_warnings: list[str] = []
        raw_media_type = raw_artifact.get("media_type")
        if (
            claimed_media_type
            and claimed_media_type != raw_media_type
        ):
            expected_warnings.append(
                "media_type_mismatch: "
                f"claimed={claimed_media_type} "
                f"sniffed={raw_media_type}"
            )
        if warnings != expected_warnings:
            raise StoreIntegrityError(
                "record warnings do not match persisted media evidence"
            )

        normalize = [
            receipt
            for receipt in receipts
            if receipt.get("stage") == "normalize"
        ]
        if len(normalize) != 1:
            raise StoreIntegrityError(
                "record must reference exactly one normalize receipt"
            )
        normalize_receipt = normalize[0]
        normalize_details = normalize_receipt.get("details") or {}
        if raw_artifact_id not in (
            normalize_receipt.get("input_artifact_ids") or []
        ):
            raise StoreIntegrityError(
                "normalize receipt does not reference record raw artifact"
            )

        derivation_ids = payload.get("derivation_ids")
        if not isinstance(derivation_ids, list) or not all(
            isinstance(value, str) for value in derivation_ids
        ):
            raise StoreIntegrityError(
                "record derivation ids are invalid"
            )
        if len(set(derivation_ids)) != len(derivation_ids):
            raise StoreIntegrityError(
                "record derivation ids are duplicated"
            )
        derivations = [
            self.get_derivation(value)
            for value in derivation_ids
        ]
        for derivation in derivations:
            derivation_receipt = self.get_receipt(
                derivation.get("receipt_id")
            )
            if derivation_receipt.get("ingest_id") != ingest_id:
                raise StoreIntegrityError(
                    "derivation receipt belongs to a different ingest"
                )
        if (
            normalized_artifact is not None
            and normalized_artifact.get("artifact_id")
            != raw_artifact.get("artifact_id")
        ):
            if not any(
                derivation.get("relation") == "NORMALIZED_FROM"
                and derivation.get("parent_artifact_id")
                == raw_artifact.get("artifact_id")
                and derivation.get("child_artifact_id")
                == normalized_artifact.get("artifact_id")
                for derivation in derivations
            ):
                raise StoreIntegrityError(
                    "record lacks normalized artifact derivation"
                )

        status = payload.get("status")
        if status == "ACCEPTED":
            if payload.get("error") is not None:
                raise StoreIntegrityError(
                    "accepted record cannot contain an error"
                )
            record_receipts = [
                receipt
                for receipt in receipts
                if receipt.get("stage") == "record"
                and receipt.get("outcome") == "READY"
            ]
            if len(record_receipts) != 1:
                raise StoreIntegrityError(
                    "accepted record must reference one record/READY receipt"
                )
            record_receipt = record_receipts[0]
            record_details = record_receipt.get("details") or {}
            if record_details.get("policy_id") != payload.get(
                "policy_id"
            ):
                raise StoreIntegrityError(
                    "record/READY policy does not match record"
                )
            if raw_artifact_id not in (
                record_receipt.get("input_artifact_ids") or []
            ):
                raise StoreIntegrityError(
                    "record/READY does not reference raw artifact"
                )

            if normalized_artifact is None:
                if normalize_receipt.get("outcome") != "SKIPPED_OPAQUE":
                    raise StoreIntegrityError(
                        "accepted opaque record lacks SKIPPED_OPAQUE receipt"
                    )
                if record_receipt.get("output_artifact_ids"):
                    raise StoreIntegrityError(
                        "opaque record/READY has unexpected output artifact"
                    )
            else:
                normalized_id = normalized_artifact.get("artifact_id")
                if normalize_receipt.get("outcome") != "PASS":
                    raise StoreIntegrityError(
                        "accepted normalized record lacks PASS receipt"
                    )
                if normalized_id not in (
                    normalize_receipt.get("output_artifact_ids") or []
                ):
                    raise StoreIntegrityError(
                        "normalize receipt does not reference normalized artifact"
                    )
                if normalized_id not in (
                    record_receipt.get("output_artifact_ids") or []
                ):
                    raise StoreIntegrityError(
                        "record/READY does not reference normalized artifact"
                    )
                if normalize_details.get(
                    "normalizer_version"
                ) != payload.get("normalizer_version"):
                    raise StoreIntegrityError(
                        "normalize receipt version does not match record"
                    )
                if normalize_details.get(
                    "media_type"
                ) != normalized_artifact.get("media_type"):
                    raise StoreIntegrityError(
                        "normalize receipt media type does not match artifact"
                    )
        elif status == "QUARANTINED":
            if normalized_artifact is not None:
                raise StoreIntegrityError(
                    "quarantined record cannot contain normalized artifact"
                )
            if normalize_receipt.get("outcome") != "QUARANTINED":
                raise StoreIntegrityError(
                    "quarantined record lacks quarantine receipt"
                )
            if payload.get("error") != normalize_details.get("error"):
                raise StoreIntegrityError(
                    "quarantined record error does not match receipt"
                )
            if any(
                receipt.get("stage") == "record"
                for receipt in receipts
            ):
                raise StoreIntegrityError(
                    "quarantined record cannot contain record commit receipt"
                )
        else:
            raise StoreIntegrityError(
                "stored record has unsupported status"
            )

        return payload
