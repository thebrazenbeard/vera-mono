"""Private, explicit-review bridge from Ingest CAS to LoRA corpus JSONL.

Ingest acceptance establishes only an acquisition result, never consent,
truth, training authority, or memory admission. No model/network calls occur.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from ingest.canonical import canonical_digest, canonical_json
from ingest.normalization import NORMALIZER_VERSION, normalize_bytes, sniff_media_type

from .adapter_prep import _load_snapshot, _reject_git_checkout, _require_private_filesystem


_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_ID = re.compile(r"r_[0-9a-f]{32}\Z")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_REVIEW_REF = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_MAX_ITEM_BYTES = 1024 * 1024
_MAX_CORPUS_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class IngestCorpusReport:
    status: str
    selection_sha256: str
    corpus_sha256: str
    examples: int
    source_groups: int


def _private_dir(path: Path, label: str) -> None:
    if os.name != "posix":
        raise ValueError("native Windows private ACLs are not qualified")
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} must be an existing absolute non-symlink directory")
    _reject_git_checkout(path, label)
    _require_private_filesystem(path, label)
    meta = path.stat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) & 0o077:
        raise ValueError(f"{label} requires owner-only directory access")


def _private_read(path: Path, label: str, max_bytes: int = _MAX_ITEM_BYTES) -> bytes:
    _private_dir(path.parent, label + " parent")
    if path.exists() and path.stat().st_uid != os.getuid():
        raise ValueError(f"{label} requires locally owned private content")
    return _load_snapshot(path, label, max_bytes)


def _json_bytes(raw: bytes, label: str) -> dict:
    def unique_fields(items: list[tuple[str, object]]) -> dict:
        obj = {}
        for key, value in items:
            if key in obj:
                raise ValueError(f"{label} has duplicate JSON fields")
            obj[key] = value
        return obj

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be an object")
    return result


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record(store: Path, ingest_id: str) -> dict:
    _private_dir(store / "records", "Ingest records")
    data = _json_bytes(_private_read(store / "records" / f"{ingest_id}.json", "Ingest record"), "Ingest record")
    if data.get("schema") != "INGEST_RECORD_V1" or data.get("ingest_id") != ingest_id:
        raise ValueError("Ingest record identity mismatch")
    if data.get("status") != "ACCEPTED" or data.get("evidence_class") != "DIRECT_SOURCE":
        raise ValueError("Ingest record is not accepted direct-source evidence")
    if data.get("warnings") != [] or data.get("error") is not None:
        raise ValueError("Ingest record contains warnings or errors requiring review")
    if data.get("normalizer_version") != NORMALIZER_VERSION:
        raise ValueError("unqualified Ingest normalizer revision")
    return data


def _artifact(store: Path, body: object, *, expected_kind: str) -> bytes:
    if not isinstance(body, dict):
        raise ValueError("Ingest artifact missing")
    digest = body.get("sha256")
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        raise ValueError("Ingest artifact digest malformed")
    relative = f"blobs/sha256/{digest[:2]}/{digest}"
    if (body.get("artifact_id") != f"sha256:{digest}" or
            body.get("storage_locator") != relative or body.get("kind") != expected_kind):
        raise ValueError("Ingest artifact binding mismatch")
    length = body.get("size_bytes")
    if type(length) is not int or not 0 < length <= _MAX_ITEM_BYTES:
        raise ValueError("Ingest artifact size not permitted for training bridge")
    for directory in (store / "blobs", store / "blobs/sha256", store / "blobs/sha256" / digest[:2]):
        _private_dir(directory, "Ingest blob storage")
    raw = _private_read(store / relative, "Ingest artifact")
    if len(raw) != length or _hash(raw) != digest:
        raise ValueError("Ingest artifact bytes fail SHA-256/size binding")
    return raw


def _receipts(store: Path, record: dict) -> str | None:
    _private_dir(store / "receipts", "Ingest receipts")
    ids = record.get("receipt_ids")
    if (not isinstance(ids, list) or not ids or
            any(not isinstance(identifier, str) or not _RECEIPT_ID.fullmatch(identifier) for identifier in ids) or
            len(ids) != len(set(ids))):
        raise ValueError("Ingest receipt list missing or duplicated")
    raw_artifact = record["raw_artifact"]["artifact_id"]
    normalized = record["normalized_artifact"]["artifact_id"]
    normalization_pass = record_ready = False
    claimed_types: list[str | None] = []
    for identifier in ids:
        value = _json_bytes(_private_read(store / "receipts" / f"{identifier}.json", "Ingest receipt"), "Ingest receipt")
        digest = value.pop("receipt_digest", None)
        if value.get("schema") != "INGEST_STAGE_RECEIPT_V1" or value.get("receipt_id") != identifier:
            raise ValueError("Ingest receipt identity mismatch")
        if not isinstance(digest, str) or digest != _hash(canonical_json(value).encode("utf-8")):
            raise ValueError("Ingest receipt digest mismatch")
        inputs, outputs, details = (value.get("input_artifact_ids"), value.get("output_artifact_ids"),
                                    value.get("details"))
        if not isinstance(inputs, list) or not isinstance(outputs, list) or not isinstance(details, dict):
            raise ValueError("Ingest receipt artifact lists/details malformed")
        if (value.get("stage") == "persist_raw" and value.get("outcome") in {"CREATED", "EXISTS"}
                and value.get("ingest_id") is None and raw_artifact in outputs):
            if details.get("media_type") != record["raw_artifact"].get("media_type"):
                raise ValueError("raw persistence receipt/media type mismatch")
            claimed = details.get("claimed_media_type")
            if claimed is not None and (not isinstance(claimed, str) or not claimed):
                raise ValueError("Ingest claimed media type invalid")
            claimed_types.append(claimed)
        if value.get("ingest_id") == record["ingest_id"]:
            if (value.get("stage") == "normalize" and value.get("outcome") == "PASS" and
                    raw_artifact in inputs and normalized in outputs and
                    details.get("normalizer_version") == NORMALIZER_VERSION and
                    details.get("media_type") == record["normalized_artifact"].get("media_type")):
                normalization_pass = True
            if (value.get("stage") == "record" and value.get("outcome") == "READY" and
                    normalized in outputs):
                record_ready = True
    if not normalization_pass or not record_ready or len(claimed_types) != 1:
        raise ValueError("Ingest normalization and record-ready receipts required")
    return claimed_types[0]


def _approved_row(store: Path, selection: dict) -> dict:
    if set(selection) != {"ingest_id", "normalized_sha256", "example_id", "group_id", "consent", "approval_reference"}:
        raise ValueError("selection fields must be exact")
    ingest_id, expected = selection["ingest_id"], selection["normalized_sha256"]
    if (not isinstance(ingest_id, str) or not _DIGEST.fullmatch(ingest_id) or
            not isinstance(expected, str) or not _DIGEST.fullmatch(expected)):
        raise ValueError("selection requires pinned Ingest and normalized artifact digests")
    if any(not isinstance(selection[key], str) or not _OPAQUE_ID.fullmatch(selection[key])
           for key in ("example_id", "group_id")):
        raise ValueError("example and source group identifiers must be opaque and bounded")
    if selection["consent"] != "owner-approved-local-training":
        raise ValueError("explicit local training consent declaration missing")
    approval = selection["approval_reference"]
    if not isinstance(approval, str) or not _REVIEW_REF.fullmatch(approval):
        raise ValueError("selection needs an opaque per-example review reference")
    record = _record(store, ingest_id)
    raw = _artifact(store, record.get("raw_artifact"), expected_kind="raw")
    normal = record.get("normalized_artifact")
    if not isinstance(normal, dict) or normal.get("sha256") != expected or normal.get("media_type") != "application/json":
        raise ValueError("approved normalized JSON artifact binding mismatch")
    data = _artifact(store, normal, expected_kind="normalized")
    claimed_type = _receipts(store, record)
    if record["raw_artifact"]["media_type"] != sniff_media_type(raw):
        raise ValueError("raw Ingest media type is inconsistent with source bytes")
    if (normal["media_type"] != (claimed_type or record["raw_artifact"]["media_type"]) or
            normalize_bytes(raw, normal["media_type"]) != data):
        raise ValueError("normalized training bytes do not replay from raw source")
    source = record.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("source_identity"), dict):
        raise ValueError("Ingest source identity malformed")
    identity_fields = ("scheme", "locator", "adapter", "adapter_version", "source_identity")
    if any(field not in source for field in identity_fields):
        raise ValueError("Ingest source identity incomplete")
    identity = {
        "schema": "INGEST_IDENTITY_V1",
        "source": {field: source[field] for field in identity_fields},
        "raw_sha256": record["raw_artifact"]["sha256"],
        "claimed_media_type": claimed_type,
        "normalizer_version": NORMALIZER_VERSION,
        "policy_id": record.get("policy_id"),
    }
    if canonical_digest(identity) != ingest_id:
        raise ValueError("Ingest record identity does not bind the raw source")
    payload = _json_bytes(data, "normalized training candidate")
    if set(payload) != {"messages"} or canonical_json(payload).encode("utf-8") != data:
        raise ValueError("normalized training candidate must contain only canonical messages")
    messages = payload["messages"]
    if (not isinstance(messages, list) or len(messages) != 2 or
            any(not isinstance(m, dict) or set(m) != {"role", "content"}
                or not isinstance(m["content"], str) or not m["content"].strip() for m in messages) or
            [m["role"] for m in messages] != ["user", "assistant"]):
        raise ValueError("training candidate must contain a nonempty user/assistant pair")
    return {
        "example_id": selection["example_id"], "group_id": selection["group_id"],
        "provenance": f"ingest:{ingest_id}:sha256:{expected}:review-sha256:{_hash(approval.encode('utf-8'))}",
        "consent": selection["consent"], "messages": messages,
    }


def _curate(store: Path, selection_path: Path) -> tuple[IngestCorpusReport, bytes]:
    _private_dir(Path(store), "private Ingest store")
    selected_bytes = _private_read(Path(selection_path), "operator selection", 1024 * 1024)
    chosen: list[dict] = []
    ids: set[str] = set()
    examples: set[str] = set()
    normalized: set[str] = set()
    content: set[str] = set()
    try:
        for line in selected_bytes.decode("utf-8").splitlines():
            if not line.strip():
                raise ValueError("selection contains blank line")
            selection = _json_bytes(line.encode("utf-8"), "selection line")
            row = _approved_row(Path(store), selection)
            msg_hash = _hash(canonical_json(row["messages"]).encode("utf-8"))
            if (selection["ingest_id"] in ids or row["example_id"] in examples or
                    selection["normalized_sha256"] in normalized or msg_hash in content):
                raise ValueError("duplicate selected source, artifact, example or conversation")
            ids.add(selection["ingest_id"])
            examples.add(row["example_id"])
            normalized.add(selection["normalized_sha256"])
            content.add(msg_hash)
            chosen.append(row)
            if len(chosen) > 1024:
                raise ValueError("selection exceeds training bridge limit")
    except UnicodeDecodeError as exc:
        raise ValueError("selection must be UTF-8 JSONL") from exc
    groups = {row["group_id"] for row in chosen}
    if len(chosen) < 4 or len(groups) < 2:
        raise ValueError("at least four independent examples and two source groups required")
    export = b"".join((json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8") for row in chosen)
    if len(export) > _MAX_CORPUS_BYTES:
        raise ValueError("curated training corpus exceeds private bridge size limit")
    return IngestCorpusReport("VERIFIED_INGEST_LINKS_REVIEW_DECLARED_NOT_TRAINED", _hash(selected_bytes), _hash(export), len(chosen), len(groups)), export


def plan_ingest_export(store: Path, selection_path: Path) -> IngestCorpusReport:
    return _curate(store, selection_path)[0]


def write_ingest_export(store: Path, selection_path: Path, output_path: Path) -> IngestCorpusReport:
    report, export = _curate(store, selection_path)
    out = Path(output_path)
    _private_dir(out.parent, "private corpus output parent")
    if not out.is_absolute() or out.is_symlink() or out.exists():
        raise ValueError("export requires a new absolute non-symlink file")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(out, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(export)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline private Ingest-to-training selection bridge")
    parser.add_argument("action", choices=("plan", "export"))
    parser.add_argument("store", type=Path)
    parser.add_argument("selection", type=Path)
    parser.add_argument("output", type=Path, nargs="?")
    args = parser.parse_args(argv)
    if (args.action == "export") != (args.output is not None):
        parser.error("export requires a new output file; plan forbids output")
    try:
        report = (write_ingest_export(args.store, args.selection, args.output)
                  if args.output else plan_ingest_export(args.store, args.selection))
    except OSError:
        print("INGEST_TRAINING_HOLD: private file operation failed", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"INGEST_TRAINING_HOLD: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report.__dict__, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
