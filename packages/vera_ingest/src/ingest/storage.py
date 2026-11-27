from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import re
import stat
from pathlib import Path
import tempfile
from typing import Any

from .canonical import canonical_digest, canonical_json, sha256_bytes
from .model import Artifact


class StoreConflict(RuntimeError):
    pass


class StoreIntegrityError(StoreConflict):
    """A managed record or its referenced material cannot be verified."""


_DIGEST = re.compile(r"[0-9a-f]{64}")
_RECEIPT_ID = re.compile(r"r_[0-9a-f]{32}")


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _unsafe_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & (
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            | getattr(stat, "FILE_ATTRIBUTE_OFFLINE", 0x1000)
            | 0x00040000 | 0x00400000
        )
    )


class FileSystemStore:
    def __init__(self, root: str | Path = ".ingest"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _atomic_create(self, path: Path, data: bytes) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise StoreConflict(f"immutable path collision: {path}")
            return False
        fd, temp_name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_name, path)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise StoreConflict(f"immutable path collision: {path}")
                return False
            return True
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

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
        if not isinstance(ingest_id, str) or not _DIGEST.fullmatch(ingest_id):
            raise StoreIntegrityError("invalid ingest ID")
        root = self.root.absolute()
        if ".." in root.parts:
            raise StoreIntegrityError("invalid managed storage path")
        try:
            for directory in (*reversed(root.parents), root):
                info = directory.lstat()
                if _unsafe_link(info) or not stat.S_ISDIR(info.st_mode):
                    raise StoreIntegrityError("managed storage ancestor is not a regular directory")
            directory = root / "records"
            try:
                info = directory.lstat()
            except FileNotFoundError:
                # A freshly constructed empty store need not have records yet.
                return False
            if _unsafe_link(info) or not stat.S_ISDIR(info.st_mode):
                raise StoreIntegrityError("managed records directory is not a regular directory")
            try:
                info = (directory / f"{ingest_id}.json").lstat()
            except FileNotFoundError:
                return False
            if _unsafe_link(info) or not stat.S_ISREG(info.st_mode):
                raise StoreIntegrityError("managed record is not a regular file")
            return True
        except OSError as exc:
            raise StoreIntegrityError("managed record presence cannot be established") from exc

    def _get_json(self, category: str, record_id: str) -> dict[str, Any]:
        path = self.root / category / f"{record_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @contextmanager
    def _managed_file(self, relative: Path):
        # Managed reads only. The surrounding private-root owner must exclude
        # concurrent hostile writers; this is not a cross-platform race-proof
        # filesystem sandbox.
        path = self.root / relative
        if ".." in path.parts:
            raise StoreIntegrityError("invalid managed storage path")
        path = path.absolute()
        for parent in reversed(path.parents):
            info = parent.lstat()
            if _unsafe_link(info) or not stat.S_ISDIR(info.st_mode):
                raise StoreIntegrityError("managed storage ancestor is not a regular directory")
        before = path.lstat()
        if _unsafe_link(before) or not stat.S_ISREG(before.st_mode):
            raise StoreIntegrityError("managed storage object is not a regular file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0)
                     | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if (not stat.S_ISREG(opened.st_mode) or _unsafe_link(opened)
                    or _file_identity(opened) != _file_identity(before)):
                raise StoreIntegrityError("managed storage object changed before reading")
            yield handle, opened
            after = path.lstat()
            if (_unsafe_link(after)
                    or _file_identity(after) != _file_identity(before)
                    or after.st_ctime_ns != before.st_ctime_ns
                    or _file_identity(os.fstat(handle.fileno())) != _file_identity(opened)
                    or os.fstat(handle.fileno()).st_ctime_ns != opened.st_ctime_ns):
                raise StoreIntegrityError("managed storage object changed during reading")

    def _managed_json(self, category: str, identifier: str) -> dict[str, Any]:
        def unique_fields(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise StoreIntegrityError("duplicate managed JSON field")
                result[key] = value
            return result
        with self._managed_file(Path(category) / f"{identifier}.json") as (handle, _):
            value = json.loads(handle.read().decode("utf-8"), object_pairs_hook=unique_fields)
        if not isinstance(value, dict):
            raise StoreIntegrityError("managed JSON is not an object")
        return value

    def _verify_artifact(self, artifact: Any, kind: str) -> str:
        if not isinstance(artifact, dict):
            raise StoreIntegrityError("managed artifact is missing")
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise StoreIntegrityError("managed artifact digest is invalid")
        locator = f"blobs/sha256/{digest[:2]}/{digest}"
        length = artifact.get("size_bytes")
        if (artifact.get("artifact_id") != f"sha256:{digest}"
                or artifact.get("kind") != kind
                or artifact.get("storage_locator") != locator
                or type(length) is not int or length < 0):
            raise StoreIntegrityError("managed artifact binding is invalid")
        with self._managed_file(Path(locator)) as (handle, info):
            if info.st_size != length:
                raise StoreIntegrityError("managed artifact size mismatch")
            observed = hashlib.sha256()
            remaining = length
            while remaining:
                chunk = handle.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise StoreIntegrityError("managed artifact truncated")
                observed.update(chunk)
                remaining -= len(chunk)
            if handle.read(1) or observed.hexdigest() != digest:
                raise StoreIntegrityError("managed artifact digest mismatch")
        return digest

    def _verified_receipt(self, identifier: str) -> dict:
        if not isinstance(identifier, str) or not _RECEIPT_ID.fullmatch(identifier):
            raise StoreIntegrityError("managed receipt ID invalid")
        body = self._managed_json("receipts", identifier)
        digest = body.pop("receipt_digest", None)
        if (body.get("schema") != "INGEST_STAGE_RECEIPT_V1"
                or body.get("receipt_id") != identifier
                or body.get("stage_version") != "1"
                or digest != canonical_digest(body)):
            raise StoreIntegrityError("managed receipt binding mismatch")
        return body

    @staticmethod
    def _receipt_matches(body, stage, outcome, ingest_id, inputs, outputs):
        if (body.get("stage") != stage or body.get("outcome") != outcome
                or body.get("ingest_id") != ingest_id
                or body.get("input_artifact_ids") != inputs
                or body.get("output_artifact_ids") != outputs
                or not isinstance(body.get("details"), dict)):
            raise StoreIntegrityError("managed receipt stage or artifact binding mismatch")
        return body["details"]

    def _verify_record_identity(self, record: dict, ingest_id: str, raw_digest: str) -> None:
        # Validate the existing V1 producer's ordered receipt contract. Its
        # acquire/persist receipts legitimately precede ingest identity.
        status = record["status"]
        ids = record.get("receipt_ids")
        if (status not in ("ACCEPTED", "QUARANTINED")
                or not isinstance(ids, list)
                or len(ids) != (4 if status == "ACCEPTED" else 3)
                or any(not isinstance(i, str) or not _RECEIPT_ID.fullmatch(i) for i in ids)
                or len(set(ids)) != len(ids)):
            raise StoreIntegrityError("managed record receipt IDs or status invalid")
        if record.get("evidence_class") != "DIRECT_SOURCE":
            raise StoreIntegrityError("managed record evidence class mismatch")
        receipts = [self._verified_receipt(i) for i in ids]
        raw = record["raw_artifact"]
        source = record["source"]
        raw_id = f"sha256:{raw_digest}"
        acquisition = self._receipt_matches(receipts[0], "acquire", "PASS", None, [], [])
        if (acquisition.get("source") != source
                or acquisition.get("size_bytes") != raw["size_bytes"]):
            raise StoreIntegrityError("managed acquisition receipt mismatch")
        persistence = receipts[1]
        if persistence.get("outcome") not in ("CREATED", "EXISTS"):
            raise StoreIntegrityError("raw persistence outcome mismatch")
        details = self._receipt_matches(persistence, "persist_raw",
                                        persistence["outcome"], None, [], [raw_id])
        if details.get("media_type") != raw.get("media_type") or "claimed_media_type" not in details:
            raise StoreIntegrityError("raw persistence receipt mismatch")
        claimed = details["claimed_media_type"]
        if claimed is not None and not isinstance(claimed, str):
            raise StoreIntegrityError("claimed media type invalid")
        identity = {
            "schema": "INGEST_IDENTITY_V1",
            "source": {key: source[key] for key in (
                "scheme", "locator", "adapter", "adapter_version", "source_identity"
            )},
            "raw_sha256": raw_digest,
            "claimed_media_type": claimed,
            "normalizer_version": record["normalizer_version"],
            "policy_id": record["policy_id"],
        }
        if canonical_digest(identity) != ingest_id:
            raise StoreIntegrityError("managed record identity mismatch")

        normalized = record["normalized_artifact"]
        outputs = [] if normalized is None else [normalized["artifact_id"]]
        media = claimed or raw["media_type"]
        norm = receipts[2]
        expected_derivations = []
        if status == "QUARANTINED":
            details = self._receipt_matches(norm, "normalize", "QUARANTINED", ingest_id, [raw_id], [])
            if normalized is not None or not isinstance(record["error"], str) or details.get("error") != record["error"]:
                raise StoreIntegrityError("managed quarantine binding mismatch")
        else:
            if record["error"] is not None:
                raise StoreIntegrityError("accepted record contains error")
            if normalized is None:
                details = self._receipt_matches(norm, "normalize", "SKIPPED_OPAQUE", ingest_id, [raw_id], [])
            else:
                details = self._receipt_matches(norm, "normalize", "PASS", ingest_id, [raw_id], outputs)
                if (normalized.get("media_type") != media
                        or details.get("normalizer_version") != record["normalizer_version"]):
                    raise StoreIntegrityError("normalization receipt mismatch")
                child = outputs[0]
                if child != raw_id:
                    derivation_id = canonical_digest({
                        "relation": "NORMALIZED_FROM", "parent": raw_id, "child": child,
                        "normalizer_version": record["normalizer_version"],
                    })
                    expected_derivations = [derivation_id]
                    derivation = self._managed_json("derivations", derivation_id)
                    if (derivation.get("schema") != "INGEST_DERIVATION_V1"
                            or derivation.get("derivation_id") != derivation_id
                            or derivation.get("relation") != "NORMALIZED_FROM"
                            or derivation.get("parent_artifact_id") != raw_id
                            or derivation.get("child_artifact_id") != child):
                        raise StoreIntegrityError("managed derivation binding mismatch")
                    # V1 deduplicates the relation by content pair and
                    # normalizer, not source/ingest ID. Its original receipt
                    # can legitimately belong to a different ingest.
                    origin = self._verified_receipt(derivation["receipt_id"])
                    origin_id = origin.get("ingest_id")
                    if not isinstance(origin_id, str) or not _DIGEST.fullmatch(origin_id):
                        raise StoreIntegrityError("managed derivation receipt identity invalid")
                    origin_details = self._receipt_matches(origin, "normalize", "PASS", origin_id, [raw_id], outputs)
                    if origin_details.get("normalizer_version") != record["normalizer_version"]:
                        raise StoreIntegrityError("managed derivation normalizer mismatch")
            if details.get("media_type") != media:
                raise StoreIntegrityError("managed normalization media mismatch")
            ready = self._receipt_matches(receipts[3], "record", "READY", ingest_id, [raw_id], outputs)
            if (ready.get("policy_id") != record["policy_id"]
                    or ready.get("commit_semantics") != "record_presence_commits_acceptance"):
                raise StoreIntegrityError("managed record-ready receipt mismatch")
        if record["derivation_ids"] != expected_derivations:
            raise StoreIntegrityError("managed derivation references mismatch")

    def get_record(self, ingest_id: str) -> dict[str, Any]:
        if not isinstance(ingest_id, str) or not _DIGEST.fullmatch(ingest_id):
            raise StoreIntegrityError("invalid ingest ID")
        try:
            record = self._managed_json("records", ingest_id)
        except FileNotFoundError:
            # Preserve the existing missing-record/CLI contract.
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise StoreIntegrityError("managed record unreadable") from exc
        try:
            if record.get("schema") != "INGEST_RECORD_V1" or record.get("ingest_id") != ingest_id:
                raise StoreIntegrityError("managed record identity mismatch")
            raw = self._verify_artifact(record.get("raw_artifact"), "raw")
            if record["normalized_artifact"] is not None:
                self._verify_artifact(record["normalized_artifact"], "normalized")
            self._verify_record_identity(record, ingest_id, raw)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise StoreIntegrityError("managed record material or provenance unreadable") from exc
        return record

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        return self._get_json("receipts", receipt_id)

    def get_derivation(self, derivation_id: str) -> dict[str, Any]:
        return self._get_json("derivations", derivation_id)
