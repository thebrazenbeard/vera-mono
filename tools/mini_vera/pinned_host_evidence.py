"""Caller-pinned Ed25519 evidence gate with an UNPROTECTED local SQLite replay ledger.

SOURCE CANDIDATE. This module never signs, issues authority or stores secrets.
A caller must independently provision the trusted public key AND its pin.
SQLite state can be deleted/rolled back by the same OS user: no host attestation.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat

from . import host_read_probe, signed_host_receipt

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
MAX_LEDGER_BYTES = 4 * 1024 * 1024


class AdmissionRefused(ValueError):
    """No valid independently pinned signed admission was recorded."""


def _check_ledger_path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.suffix != ".sqlite":
        raise AdmissionRefused("ledger must be an absolute .sqlite path")
    # This is source-only policy, not a principal-based permission boundary.
    root = Path(__file__).resolve().parents[2]
    if path.is_relative_to(root):
        raise AdmissionRefused("ledger cannot be inside Mini-Vera source or bundle")
    if not path.parent.exists() or not path.parent.is_dir():
        raise AdmissionRefused("ledger parent missing")
    try:
        for part in (path.parent, *path.parent.parents):
            item = os.lstat(part)
            if (stat.S_ISLNK(item.st_mode)
                    or getattr(item, "st_file_attributes", 0) & 0x400):
                raise AdmissionRefused("ledger parent link/reparse refused")
        if path.exists() or path.is_symlink():
            item = os.lstat(path)
            if (not stat.S_ISREG(item.st_mode)
                    or getattr(item, "st_file_attributes", 0) & 0x400
                    or not 0 < item.st_size <= MAX_LEDGER_BYTES):
                raise AdmissionRefused("unsafe or oversized ledger file")
    except (OSError, ValueError) as exc:
        raise AdmissionRefused("ledger path unavailable") from exc
    return path


class PinnedHostEvidence:
    """Verify fixed-source observation, then atomically consume a challenge.

    The trusted public key, SHA-256 pin, source/request/turn/challenge come
    from the operator/controller, NEVER from the signed receipt itself.
    """

    def __init__(self, *, ledger_path: Path,
                 trusted_public_key: bytes,
                 expected_public_key_sha256: str,
                 expected_request_sha256: str,
                 expected_turn_sha256: str,
                 expected_source_sha256: str,
                 challenge_hex: str) -> None:
        try:
            self._verifier = signed_host_receipt.OneShotSignedHostVerifier(
                trusted_public_key=trusted_public_key,
                expected_public_key_sha256=expected_public_key_sha256,
                expected_request_sha256=expected_request_sha256,
                expected_turn_sha256=expected_turn_sha256,
                expected_source_sha256=expected_source_sha256,
                challenge_hex=challenge_hex,
                now=datetime.now(timezone.utc),
            )
        except signed_host_receipt.ReceiptRefused as exc:
            raise AdmissionRefused("untrusted or incorrectly pinned key") from exc
        self._path = _check_ledger_path(ledger_path)
        self._pin = expected_public_key_sha256
        self._source = expected_source_sha256
        self._challenge = challenge_hex

    def accept(self, receipt: bytes) -> dict[str, object]:
        """Returns bounded evidence, NOT privilege or host qualification."""
        try:
            source = host_read_probe._read_fixed_source()
            host_read_probe._manifest_binding(source)
        except host_read_probe.ProbeRefused as exc:
            raise AdmissionRefused("local fixed source unavailable") from exc
        if hashlib.sha256(source).hexdigest() != self._source:
            raise AdmissionRefused("current source mismatched operator expectation")
        try:
            proof = self._verifier.accept(receipt)
        except signed_host_receipt.ReceiptRefused as exc:
            raise AdmissionRefused("signed receipt failed verification") from exc
        if proof["source_size_bytes"] != len(source):
            raise AdmissionRefused("signed byte count mismatches real source")
        self._store(proof, hashlib.sha256(receipt).hexdigest())
        return {
            "schema": "MINI_VERA_PINNED_RECEIPT_ADMISSION_V1",
            "status": "PINNED_SIGNATURE_LOCAL_SOURCE_LEDGER_CONSISTENT",
            "source_name": proof["source_name"],
            "source_sha256": proof["source_sha256"],
            "source_size_bytes": proof["source_size_bytes"],
            "public_key_sha256": self._pin,
            "request_sha256": proof["request_sha256"],
            "turn_sha256": proof["turn_sha256"],
            "challenge_hex": self._challenge,
            "signature_status": proof["signature_status"],
            "pin_provenance": "CALLER_PIN_NOT_INDEPENDENTLY_ATTESTED",
            "durable_replay_recorded": True,
            "replay_protection": "UNPROTECTED_LOCAL_SQLITE_ROLLBACK_POSSIBLE",
            "host_issuer_qualified": False,
            "source_read_attested": False,
            "verified_external_effects": False,
        }

    def _store(self, proof: dict, receipt_sha: str) -> None:
        path = _check_ledger_path(self._path)
        connection: sqlite3.Connection | None = None
        try:
            # SQLite uniqueness serializes competing local processes. Database
            # provenance, rollback and permissions remain UNPROTECTED here.
            connection = sqlite3.connect(str(path), timeout=5, isolation_level=None)
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA journal_mode=DELETE")
            check = connection.execute("PRAGMA quick_check").fetchone()
            if check != ("ok",):
                raise AdmissionRefused("ledger integrity check failed")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS accepted ("
                "challenge TEXT PRIMARY KEY NOT NULL,"
                "receipt_sha TEXT NOT NULL,"
                "issuer_pin TEXT NOT NULL,"
                "request_sha TEXT NOT NULL,"
                "turn_sha TEXT NOT NULL,"
                "source_sha TEXT NOT NULL) WITHOUT ROWID")
            fields = (
                self._challenge, receipt_sha, self._pin,
                proof["request_sha256"], proof["turn_sha256"],
                proof["source_sha256"],
            )
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO accepted(challenge,receipt_sha,issuer_pin,"
                "request_sha,turn_sha,source_sha) VALUES (?,?,?,?,?,?)",
                fields)
            connection.commit()
            row = connection.execute(
                "SELECT challenge,receipt_sha,issuer_pin,request_sha,"
                "turn_sha,source_sha FROM accepted WHERE challenge=?",
                (self._challenge,)).fetchone()
            if row != fields:
                raise AdmissionRefused("ledger commit readback mismatch")
        except (sqlite3.DatabaseError, OSError) as exc:
            if connection is not None and connection.in_transaction:
                connection.rollback()
            raise AdmissionRefused("ledger corrupt, already consumed or unavailable") from exc
        finally:
            if connection is not None:
                connection.close()
