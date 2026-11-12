"""One fixed, read-only source-file observation independent of model prose.

This module is a bounded local-process file read, NOT a signed host attestation,
external command executor, chain-of-custody oracle, or authorization for actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any

SOURCE_PATH = Path(__file__).with_name("compose.py")
MAX_SOURCE_BYTES = 256 * 1024
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
SCHEMA = "MINI_VERA_LOCAL_SOURCE_READ_V1"
RECEIPT_KEYS = frozenset({
    "schema", "operation", "request_sha256", "source_name",
    "source_sha256", "source_size_bytes", "observed_at_utc",
    "issuer_process_id", "nonce_hex", "evidence_class",
    "integrity_level", "external_effects", "receipt_sha256",
    "manifest_binding", "manifest_sha256",
})


class ProbeRefused(ValueError):
    """A bounded host file observation was not possible."""


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _read_fixed_source() -> bytes:
    path = SOURCE_PATH
    try:
        for part in (path, *path.parents):
            entry = os.lstat(part)
            if stat.S_ISLNK(entry.st_mode) or (
                    getattr(entry, "st_file_attributes", 0) & 0x400):
                raise ProbeRefused("reparse/symlink path refused")
        before = os.lstat(path)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_SOURCE_BYTES:
            raise ProbeRefused("missing/oversized source file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size != before.st_size:
                raise ProbeRefused("source file changed during open")
            if before.st_ino and opened.st_ino and before.st_ino != opened.st_ino:
                raise ProbeRefused("source file swapped during open")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(MAX_SOURCE_BYTES + 1)
            if len(data) != opened.st_size:
                raise ProbeRefused("source file changed during read")
            return data
        finally:
            os.close(fd)
    except ProbeRefused:
        raise
    except (OSError, ValueError) as exc:
        raise ProbeRefused("source bytes unavailable") from exc


def _manifest_binding(data: bytes) -> tuple[str, str | None]:
    """Check installed source against its local unsigned bundle manifest."""
    root = SOURCE_PATH.parents[2]
    path = root / "INSTALL.json"
    if not path.exists():
        if not (root / ".git").exists():
            raise ProbeRefused("bundled source manifest missing")
        return "SOURCE_TREE_NO_INSTALL_MANIFEST", None
    try:
        info = os.lstat(path)
        if (stat.S_ISLNK(info.st_mode)
                or (getattr(info, "st_file_attributes", 0) & 0x400)
                or not stat.S_ISREG(info.st_mode)
                or not 0 < info.st_size <= 256 * 1024):
            raise ProbeRefused("unsafe local bundle manifest")
        raw = path.read_bytes()
        if len(raw) != info.st_size:
            raise ProbeRefused("bundle manifest changed during read")

        def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for k, v in pairs:
                if k in result:
                    raise ProbeRefused("ambiguous bundle manifest")
                result[k] = v
            return result

        manifest = json.loads(raw, object_pairs_hook=unique_pairs)
        expected = manifest["files_sha256"]["tools/mini_vera/compose.py"]
        if (type(expected) is not str or HEX64.fullmatch(expected) is None
                or expected != hashlib.sha256(data).hexdigest()):
            raise ProbeRefused("installed source mismatch")
        return "MATCHED_UNSIGNED_LOCAL_MANIFEST", hashlib.sha256(raw).hexdigest()
    except ProbeRefused:
        raise
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise ProbeRefused("bundle manifest unreadable or invalid") from exc


def observe_source(request_sha256: str) -> dict[str, Any]:
    """Read only this package's compose.py, bound receipt to current request."""
    if type(request_sha256) is not str or HEX64.fullmatch(request_sha256) is None:
        raise ProbeRefused("invalid request binding")
    data = _read_fixed_source()
    manifest_binding, manifest_sha = _manifest_binding(data)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "operation": "READ_ONLY_SOURCE_SHA256",
        "request_sha256": request_sha256,
        "source_name": "tools/mini_vera/compose.py",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_size_bytes": len(data),
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "issuer_process_id": os.getpid(),
        "nonce_hex": secrets.token_hex(16),
        "evidence_class": "SOURCE_PROCESS_OBSERVATION_NOT_HOST_ATTESTATION",
        "integrity_level": "SELF_HASH_NOT_SIGNATURE",
        "external_effects": "NONE",
        "manifest_binding": manifest_binding,
        "manifest_sha256": manifest_sha,
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def check_source_receipt(value: dict[str, Any], *,
                         expected_request_sha256: str) -> bool:
    """Current-process byte consistency, NOT identity/signature verification."""
    if type(value) is not dict or set(value) != RECEIPT_KEYS:
        return False
    if (type(expected_request_sha256) is not str
            or HEX64.fullmatch(expected_request_sha256) is None
            or value.get("request_sha256") != expected_request_sha256
            or value.get("schema") != SCHEMA
            or value.get("operation") != "READ_ONLY_SOURCE_SHA256"
            or value.get("source_name") != "tools/mini_vera/compose.py"
            or value.get("evidence_class") !=
                "SOURCE_PROCESS_OBSERVATION_NOT_HOST_ATTESTATION"
            or value.get("integrity_level") != "SELF_HASH_NOT_SIGNATURE"
            or value.get("external_effects") != "NONE"
            or value.get("manifest_binding") not in (
                "MATCHED_UNSIGNED_LOCAL_MANIFEST", "SOURCE_TREE_NO_INSTALL_MANIFEST")
            or type(value.get("source_size_bytes")) is not int
            or type(value.get("issuer_process_id")) is not int
            or type(value.get("observed_at_utc")) is not str
            or type(value.get("nonce_hex")) is not str
            or len(value["nonce_hex"]) != 32):
        return False
    for digest in ("source_sha256", "receipt_sha256"):
        if type(value.get(digest)) is not str or HEX64.fullmatch(value[digest]) is None:
            return False
    if not re.fullmatch(r"[a-f0-9]{32}", value["nonce_hex"]):
        return False
    without_hash = {k: v for k, v in value.items() if k != "receipt_sha256"}
    if hashlib.sha256(_canonical(without_hash)).hexdigest() != value["receipt_sha256"]:
        return False
    try:
        data = _read_fixed_source()
    except ProbeRefused:
        return False
    try:
        binding, sha = _manifest_binding(data)
    except ProbeRefused:
        return False
    return (value["source_size_bytes"] == len(data)
            and value["source_sha256"] == hashlib.sha256(data).hexdigest()
            and value["manifest_binding"] == binding
            and value["manifest_sha256"] == sha)

OBSERVATION_SCHEMA = "MINI_VERA_HOST_SOURCE_OBSERVATION_V1"
OBSERVATION_FIELDS = frozenset({
    "schema", "base_request_sha256", "turn_sha256", "source_name", "source_sha256",
    "source_size_bytes", "manifest_binding", "manifest_sha256",
    "trust", "authority_effect",
})


def project_observation(receipt: dict[str, Any], *,
                        base_request_sha256: str,
                        turn_sha256: str) -> dict[str, Any]:
    """Minimize host observation presented as model DATA, not an instruction."""
    if type(turn_sha256) is not str or HEX64.fullmatch(turn_sha256) is None:
        raise ProbeRefused("invalid turn binding")
    if not check_source_receipt(receipt, expected_request_sha256=base_request_sha256):
        raise ProbeRefused("original source receipt invalid or stale")
    return {
        "schema": OBSERVATION_SCHEMA,
        "base_request_sha256": base_request_sha256,
        "turn_sha256": turn_sha256,
        "source_name": receipt["source_name"],
        "source_sha256": receipt["source_sha256"],
        "source_size_bytes": receipt["source_size_bytes"],
        "manifest_binding": receipt["manifest_binding"],
        "manifest_sha256": receipt["manifest_sha256"],
        "trust": "LOCALLY_OBSERVED_UNSIGNED_DATA",
        "authority_effect": "NONE",
    }


def check_projected_observation(value: dict[str, Any], *,
                                base_request_sha256: str,
                                expected_turn_sha256: str) -> bool:
    """Re-read local source and manifest. Never accept a caller-only self-hash."""
    if (type(value) is not dict or set(value) != OBSERVATION_FIELDS
            or type(base_request_sha256) is not str
            or HEX64.fullmatch(base_request_sha256) is None
            or value["schema"] != OBSERVATION_SCHEMA
            or value["base_request_sha256"] != base_request_sha256
            or type(expected_turn_sha256) is not str
            or HEX64.fullmatch(expected_turn_sha256) is None
            or value["turn_sha256"] != expected_turn_sha256
            or value["source_name"] != "tools/mini_vera/compose.py"
            or type(value["source_sha256"]) is not str
            or HEX64.fullmatch(value["source_sha256"]) is None
            or type(value["source_size_bytes"]) is not int
            or value["trust"] != "LOCALLY_OBSERVED_UNSIGNED_DATA"
            or value["authority_effect"] != "NONE"):
        return False
    try:
        raw = _read_fixed_source()
        binding, manifest_sha = _manifest_binding(raw)
    except ProbeRefused:
        return False
    return (
        value["source_sha256"] == hashlib.sha256(raw).hexdigest()
        and value["source_size_bytes"] == len(raw)
        and value["manifest_binding"] == binding
        and value["manifest_sha256"] == manifest_sha
    )
