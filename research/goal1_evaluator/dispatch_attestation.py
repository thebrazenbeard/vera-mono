"""Cryptographic dispatch-receipt verifier for the Goal 1 evaluator.

The gateway private key must live outside the learner/controller OS privilege boundary.
This module verifies signed receipts and durable one-use reservations; it does not
create a gateway, provision keys, or prove that a signer is honestly operated.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED = frozenset({
    "witness_kind", "gateway_id", "attestation_id", "invocation_id",
    "reservation_id", "run_id", "arm", "challenge_id",
    "challenge_view_digest", "model_prompt_sha256", "model_response_sha256",
    "model_identity", "model_artifact_sha256", "dispatch_monotonic_ns",
    "response_monotonic_ns", "outcome_status", "resource_usage", "signature",
})
_USAGE_FIELDS = frozenset({"input_tokens", "output_tokens", "wall_time_ms"})


def canonical_attestation_bytes(fields: dict[str, Any]) -> bytes:
    """Canonical signed bytes; the detached signature itself is excluded."""
    body = {key: value for key, value in fields.items() if key != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _sha(value: object, name: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _nonempty(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


class Ed25519DispatchEvidenceVerifier:
    """Verify gateway-signed receipts against a pre-dispatch reservation ledger.

    The pinned public key is trust configuration, not learner-supplied receipt data.
    The durable SQLite ledger provides atomic one-use semantics across verifier
    process restarts on this host. It is not tamper-proof against a same-privilege
    attacker who can rewrite the DB or replace this process/configuration.
    """

    def __init__(
        self, *, trusted_public_key: bytes, trusted_gateway_id: str,
        replay_db: str, expected_model_identity: str,
        expected_model_artifact_sha256: str,
    ) -> None:
        try:
            self._public_key = Ed25519PublicKey.from_public_bytes(trusted_public_key)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid pinned Ed25519 public key") from exc
        _nonempty(trusted_gateway_id, "trusted_gateway_id")
        _nonempty(expected_model_identity, "expected_model_identity")
        _sha(expected_model_artifact_sha256, "expected_model_artifact_sha256")
        self._gateway_id = trusted_gateway_id
        self._model_identity = expected_model_identity
        self._model_artifact_sha256 = expected_model_artifact_sha256
        self._db = str(Path(replay_db).resolve())
        Path(self._db).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    arm TEXT NOT NULL,
                    challenge_id TEXT NOT NULL,
                    challenge_view_digest TEXT NOT NULL,
                    model_prompt_sha256 TEXT NOT NULL,
                    expected_model_identity TEXT NOT NULL,
                    expected_model_artifact_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('RESERVED','CONSUMED','UNKNOWN')),
                    UNIQUE(run_id, arm, challenge_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consumed_receipts (
                    attestation_id TEXT PRIMARY KEY,
                    invocation_id TEXT NOT NULL UNIQUE,
                    reservation_id TEXT NOT NULL UNIQUE,
                    receipt_sha256 TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(reservation_id) REFERENCES reservations(reservation_id)
                )
            """)

    def _connect(self):
        conn = sqlite3.connect(self._db, timeout=10, isolation_level=None)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def reserve_invocation(
        self, *, reservation_id: str, run_id: str, arm: str,
        challenge_id: str, challenge_view_digest: str,
        model_prompt_sha256: str, expected_model_identity: str,
        expected_model_artifact_sha256: str,
    ) -> None:
        """Durably reserve exactly one arm/case before dispatch is attempted."""
        for name, value in (("reservation_id", reservation_id), ("run_id", run_id),
                            ("arm", arm), ("challenge_id", challenge_id),
                            ("expected_model_identity", expected_model_identity)):
            _nonempty(value, name)
        _sha(challenge_view_digest, "challenge_view_digest")
        _sha(model_prompt_sha256, "model_prompt_sha256")
        _sha(expected_model_artifact_sha256, "expected_model_artifact_sha256")
        if expected_model_identity != self._model_identity or expected_model_artifact_sha256 != self._model_artifact_sha256:
            raise ValueError("reservation model identity does not match pinned policy")
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("""
                    INSERT INTO reservations (
                        reservation_id, run_id, arm, challenge_id,
                        challenge_view_digest, model_prompt_sha256,
                        expected_model_identity, expected_model_artifact_sha256, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RESERVED')
                """, (reservation_id, run_id, arm, challenge_id, challenge_view_digest,
                      model_prompt_sha256, expected_model_identity, expected_model_artifact_sha256))
                conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise ValueError("reservation duplicate or arm/case already reserved") from exc

    def verify(self, evidence: dict[str, Any]) -> bool:
        """Cryptographically verify and atomically consume one matching receipt."""
        if not isinstance(evidence, dict) or set(evidence) != _REQUIRED:
            raise ValueError("dispatch evidence fields missing or unexpected")
        if evidence["witness_kind"] != "independent_dispatch_gateway":
            raise ValueError("independent dispatch witness required")
        if evidence["gateway_id"] != self._gateway_id:
            raise ValueError("untrusted gateway identity")
        for name in ("attestation_id", "invocation_id", "reservation_id", "run_id",
                     "arm", "challenge_id", "model_identity"):
            _nonempty(evidence[name], name)
        for name in ("challenge_view_digest", "model_prompt_sha256",
                     "model_response_sha256", "model_artifact_sha256"):
            _sha(evidence[name], name)
        if evidence["model_identity"] != self._model_identity:
            raise ValueError("model identity mismatch")
        if evidence["model_artifact_sha256"] != self._model_artifact_sha256:
            raise ValueError("model artifact identity mismatch")
        if evidence["outcome_status"] not in ("COMPLETED", "OUTCOME_UNKNOWN"):
            raise ValueError("non-completed invocation cannot be committed")
        start, end = evidence["dispatch_monotonic_ns"], evidence["response_monotonic_ns"]
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise ValueError("invalid dispatch timestamp ordering")
        usage = evidence["resource_usage"]
        if not isinstance(usage, dict) or set(usage) != _USAGE_FIELDS:
            raise ValueError("measured resource usage fields missing")
        if any(type(usage[key]) is not int or usage[key] < 0 for key in ("input_tokens", "output_tokens")):
            raise ValueError("invalid measured token usage")
        if type(usage["wall_time_ms"]) is not int or usage["wall_time_ms"] <= 0:
            raise ValueError("invalid measured wall time")
        signature = evidence["signature"]
        if not isinstance(signature, str):
            raise ValueError("detached signature missing")
        try:
            raw_signature = base64.b64decode(signature, validate=True)
            self._public_key.verify(raw_signature, canonical_attestation_bytes(evidence))
        except (ValueError, InvalidSignature) as exc:
            raise ValueError("gateway signature verification failed") from exc

        receipt_hash = hashlib.sha256(canonical_attestation_bytes(evidence)).hexdigest()
        if evidence["outcome_status"] == "OUTCOME_UNKNOWN":
            try:
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute("""
                        SELECT run_id, arm, challenge_id, challenge_view_digest,
                               model_prompt_sha256, expected_model_identity,
                               expected_model_artifact_sha256, status
                        FROM reservations WHERE reservation_id=?
                    """, (evidence["reservation_id"],)).fetchone()
                    expected = (
                        evidence["run_id"], evidence["arm"], evidence["challenge_id"],
                        evidence["challenge_view_digest"], evidence["model_prompt_sha256"],
                        evidence["model_identity"], evidence["model_artifact_sha256"], "RESERVED",
                    )
                    if row is None or tuple(row) != expected:
                        raise ValueError("unknown outcome lacks matching live reservation")
                    conn.execute("UPDATE reservations SET status='UNKNOWN' WHERE reservation_id=?",
                                 (evidence["reservation_id"],))
                    conn.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                raise ValueError("unknown outcome reservation conflict") from exc
            raise ValueError("OUTCOME_UNKNOWN closes reservation; automatic retry forbidden")
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("""
                    SELECT run_id, arm, challenge_id, challenge_view_digest,
                           model_prompt_sha256, expected_model_identity,
                           expected_model_artifact_sha256, status
                    FROM reservations WHERE reservation_id=?
                """, (evidence["reservation_id"],)).fetchone()
                if row is None:
                    raise ValueError("pre-dispatch reservation not found")
                expected = (
                    evidence["run_id"], evidence["arm"], evidence["challenge_id"],
                    evidence["challenge_view_digest"], evidence["model_prompt_sha256"],
                    evidence["model_identity"], evidence["model_artifact_sha256"], "RESERVED",
                )
                if tuple(row) != expected:
                    raise ValueError("dispatch receipt does not match reservation")
                conn.execute("""
                    INSERT INTO consumed_receipts
                    (attestation_id, invocation_id, reservation_id, receipt_sha256)
                    VALUES (?, ?, ?, ?)
                """, (evidence["attestation_id"], evidence["invocation_id"],
                      evidence["reservation_id"], receipt_hash))
                conn.execute("UPDATE reservations SET status='CONSUMED' WHERE reservation_id=?",
                             (evidence["reservation_id"],))
                conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise ValueError("dispatch replay or reused invocation/reservation") from exc
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        return True
