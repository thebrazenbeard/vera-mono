from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import base64
import hashlib
import hmac
import json
import sqlite3
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)

from .behavior_effect_verification import (
    BehaviorEffectRequirement,
    BehaviorEffectVerificationReceipt,
)


class BehaviorAttestationError(ValueError):
    pass


BEHAVIOR_ATTEST_VERIFY_PREFIX = "BEHAVIOR_ATTEST_VERIFY"
BEHAVIOR_ATTESTATION_STATUSES = frozenset({"PASS", "FAIL", "UNAVAILABLE"})
NO_EFFECT_SUBJECT = "NONE"


def _require_digest(value: str, label: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise BehaviorAttestationError(
            f"{label} must be an exact SHA-256 digest"
        )
    try:
        int(value, 16)
    except ValueError as exc:
        raise BehaviorAttestationError(
            f"{label} must be hexadecimal"
        ) from exc
    return value.lower()


def canonical_behavior_declaration_digest(
    profile: Mapping[str, Any],
) -> str:
    if not isinstance(profile, Mapping):
        raise BehaviorAttestationError(
            "behavior declaration profile must be a mapping"
        )
    return sha256_hex(canonical_json_bytes(dict(profile)))


@dataclass(frozen=True, slots=True)
class BehaviorAttestationRequirement:
    consumer_id: str
    probe_id: str
    declaration_digest: str
    provider_id: str
    provider_key_id: str
    provider_key_digest: str
    effect_subject_digest: str | None

    @classmethod
    def parse(cls, value: str) -> "BehaviorAttestationRequirement":
        if type(value) is not str or not value:
            raise BehaviorAttestationError(
                "behavior attestation requirement must be non-empty string"
            )
        parts = value.split("|")
        if (
            len(parts) != 8
            or parts[0] != BEHAVIOR_ATTEST_VERIFY_PREFIX
            or any(not part for part in parts[1:])
        ):
            raise BehaviorAttestationError(
                "behavior attestation requirement must use "
                "'BEHAVIOR_ATTEST_VERIFY|<consumer-id>|<probe-id>|"
                "<declaration-sha256>|<provider-id>|<provider-key-id>|"
                "<provider-key-sha256>|<effect-subject-sha256-or-NONE>'"
            )
        effect_subject = (
            None
            if parts[7] == NO_EFFECT_SUBJECT
            else _require_digest(parts[7], "effect_subject_digest")
        )
        return cls(
            consumer_id=parts[1],
            probe_id=parts[2],
            declaration_digest=_require_digest(
                parts[3], "declaration_digest"
            ),
            provider_id=parts[4],
            provider_key_id=parts[5],
            provider_key_digest=_require_digest(
                parts[6], "provider_key_digest"
            ),
            effect_subject_digest=effect_subject,
        )


def behavior_attestation_requirements(
    evidence_requirements: Sequence[str],
) -> tuple[BehaviorAttestationRequirement, ...]:
    found: list[BehaviorAttestationRequirement] = []
    for raw in evidence_requirements:
        if not isinstance(raw, str) or not raw.startswith(
            BEHAVIOR_ATTEST_VERIFY_PREFIX + "|"
        ):
            continue
        found.append(BehaviorAttestationRequirement.parse(raw))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class BehaviorAttestationSubject:
    consumer_id: str
    probe_id: str
    evidence_kind: str
    declaration_digest: str
    behavior_effect_receipt_digest: str
    process_instance_id: str
    runtime_state_digest: str
    stimulus_digest: str
    outcome_digest: str
    raw_response_digest: str
    provider_id: str
    provider_key_id: str
    provider_key_digest: str
    attestation_nonce: str
    external_effect_id: str | None
    external_effect_receipt_digest: str | None
    external_effect_subject_digest: str | None

    def validate(self) -> None:
        for label, value in (
            ("consumer_id", self.consumer_id),
            ("probe_id", self.probe_id),
            ("evidence_kind", self.evidence_kind),
            ("process_instance_id", self.process_instance_id),
            ("provider_id", self.provider_id),
            ("provider_key_id", self.provider_key_id),
            ("attestation_nonce", self.attestation_nonce),
        ):
            if type(value) is not str or not value:
                raise BehaviorAttestationError(
                    f"{label} must be a non-empty exact string"
                )
        if self.evidence_kind not in {"BEHAVIOR", "EFFECT"}:
            raise BehaviorAttestationError(
                f"unsupported behavior attestation kind: {self.evidence_kind!r}"
            )
        for label, value in (
            ("declaration_digest", self.declaration_digest),
            ("behavior_effect_receipt_digest", self.behavior_effect_receipt_digest),
            ("runtime_state_digest", self.runtime_state_digest),
            ("stimulus_digest", self.stimulus_digest),
            ("outcome_digest", self.outcome_digest),
            ("raw_response_digest", self.raw_response_digest),
            ("provider_key_digest", self.provider_key_digest),
        ):
            _require_digest(value, label)
        if self.evidence_kind == "BEHAVIOR":
            if any(
                value is not None
                for value in (
                    self.external_effect_id,
                    self.external_effect_receipt_digest,
                    self.external_effect_subject_digest,
                )
            ):
                raise BehaviorAttestationError(
                    "BEHAVIOR attestation must not claim external effect evidence"
                )
        else:
            if type(self.external_effect_id) is not str or not self.external_effect_id:
                raise BehaviorAttestationError(
                    "EFFECT attestation requires external_effect_id"
                )
            if self.external_effect_receipt_digest is None:
                raise BehaviorAttestationError(
                    "EFFECT attestation requires external_effect_receipt_digest"
                )
            if self.external_effect_subject_digest is None:
                raise BehaviorAttestationError(
                    "EFFECT attestation requires external_effect_subject_digest"
                )
            _require_digest(
                self.external_effect_receipt_digest,
                "external_effect_receipt_digest",
            )
            _require_digest(
                self.external_effect_subject_digest,
                "external_effect_subject_digest",
            )

    def canonical_body(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "VERA_MONO_BEHAVIOR_ATTESTATION_SUBJECT_V1",
            "consumer_id": self.consumer_id,
            "probe_id": self.probe_id,
            "evidence_kind": self.evidence_kind,
            "declaration_digest": self.declaration_digest,
            "behavior_effect_receipt_digest": self.behavior_effect_receipt_digest,
            "process_instance_id": self.process_instance_id,
            "runtime_state_digest": self.runtime_state_digest,
            "stimulus_digest": self.stimulus_digest,
            "outcome_digest": self.outcome_digest,
            "raw_response_digest": self.raw_response_digest,
            "provider_id": self.provider_id,
            "provider_key_id": self.provider_key_id,
            "provider_key_digest": self.provider_key_digest,
            "attestation_nonce": self.attestation_nonce,
            "external_effect_id": self.external_effect_id,
            "external_effect_receipt_digest": self.external_effect_receipt_digest,
            "external_effect_subject_digest": self.external_effect_subject_digest,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_body())

    @property
    def digest(self) -> str:
        return sha256_hex(self.canonical_bytes())


@runtime_checkable
class BehaviorEvidenceAttestationVerifier(Protocol):
    provider_id: str
    key_id: str
    key_digest: str

    def verify(self, subject: bytes, signature: str) -> bool:
        ...


class HmacBehaviorEvidenceAttestationVerifier:
    """Host-injected integrity verifier; not an independent-review claim."""

    def __init__(
        self,
        *,
        provider_id: str,
        key_id: str,
        secret: bytes,
    ):
        if type(provider_id) is not str or not provider_id:
            raise ValueError("provider_id must be non-empty")
        if type(key_id) is not str or not key_id:
            raise ValueError("key_id must be non-empty")
        if type(secret) is not bytes or not secret:
            raise ValueError("secret must be non-empty bytes")
        self.provider_id = provider_id
        self.key_id = key_id
        self._secret = secret
        self.key_digest = sha256_hex(secret)

    def sign(self, subject: bytes) -> str:
        if type(subject) is not bytes or not subject:
            raise ValueError("subject must be non-empty bytes")
        return hmac.new(
            self._secret,
            subject,
            hashlib.sha256,
        ).hexdigest()

    def verify(self, subject: bytes, signature: str) -> bool:
        if type(subject) is not bytes or not subject:
            return False
        if type(signature) is not str or not signature:
            return False
        return hmac.compare_digest(
            self.sign(subject),
            signature.lower(),
        )


@dataclass(frozen=True, slots=True)
class BehaviorAttestationObservation:
    consumer_id: str
    probe_id: str
    available: bool
    evidence_kind: str | None
    declaration_digest: str | None
    behavior_effect_receipt_digest: str | None
    process_instance_id: str | None
    runtime_state_digest: str | None
    stimulus_digest: str | None
    outcome_digest: str | None
    raw_response_digest: str | None
    provider_id: str | None
    provider_key_id: str | None
    provider_key_digest: str | None
    attestation_nonce: str | None
    attestation_subject_digest: str | None
    attestation_signature: str | None
    signature_valid: bool | None
    external_effect_id: str | None
    external_effect_receipt_digest: str | None
    external_effect_subject_digest: str | None
    external_evidence_digest: str | None
    evidence_ref: str | None

    def validate(self) -> None:
        for label, value in (
            ("consumer_id", self.consumer_id),
            ("probe_id", self.probe_id),
        ):
            if type(value) is not str or not value:
                raise BehaviorAttestationError(
                    f"{label} must be a non-empty exact string"
                )
        if type(self.available) is not bool:
            raise BehaviorAttestationError("available must be boolean")
        observed = (
            self.evidence_kind,
            self.declaration_digest,
            self.behavior_effect_receipt_digest,
            self.process_instance_id,
            self.runtime_state_digest,
            self.stimulus_digest,
            self.outcome_digest,
            self.raw_response_digest,
            self.provider_id,
            self.provider_key_id,
            self.provider_key_digest,
            self.attestation_nonce,
            self.attestation_subject_digest,
            self.attestation_signature,
            self.signature_valid,
            self.external_effect_id,
            self.external_effect_receipt_digest,
            self.external_effect_subject_digest,
            self.external_evidence_digest,
            self.evidence_ref,
        )
        if not self.available:
            if any(value is not None for value in observed):
                raise BehaviorAttestationError(
                    "unavailable behavior attestation cannot carry observed evidence"
                )
            return
        if self.evidence_kind not in {"BEHAVIOR", "EFFECT"}:
            raise BehaviorAttestationError(
                "available behavior attestation has unsupported evidence kind"
            )
        for label, value in (
            ("process_instance_id", self.process_instance_id),
            ("provider_id", self.provider_id),
            ("provider_key_id", self.provider_key_id),
            ("attestation_nonce", self.attestation_nonce),
            ("attestation_signature", self.attestation_signature),
            ("evidence_ref", self.evidence_ref),
        ):
            if type(value) is not str or not value:
                raise BehaviorAttestationError(
                    f"{label} must be non-empty when attestation is available"
                )
        if type(self.signature_valid) is not bool:
            raise BehaviorAttestationError(
                "signature_valid must be boolean when attestation is available"
            )
        for label, value in (
            ("declaration_digest", self.declaration_digest),
            ("behavior_effect_receipt_digest", self.behavior_effect_receipt_digest),
            ("runtime_state_digest", self.runtime_state_digest),
            ("stimulus_digest", self.stimulus_digest),
            ("outcome_digest", self.outcome_digest),
            ("raw_response_digest", self.raw_response_digest),
            ("provider_key_digest", self.provider_key_digest),
            ("attestation_subject_digest", self.attestation_subject_digest),
            ("external_evidence_digest", self.external_evidence_digest),
        ):
            if value is None:
                raise BehaviorAttestationError(
                    f"{label} is required when attestation is available"
                )
            _require_digest(value, label)
        if self.evidence_kind == "BEHAVIOR":
            if any(
                value is not None
                for value in (
                    self.external_effect_id,
                    self.external_effect_receipt_digest,
                    self.external_effect_subject_digest,
                )
            ):
                raise BehaviorAttestationError(
                    "BEHAVIOR attestation cannot carry external effect fields"
                )
        else:
            if type(self.external_effect_id) is not str or not self.external_effect_id:
                raise BehaviorAttestationError(
                    "EFFECT attestation requires external_effect_id"
                )
            if self.external_effect_receipt_digest is None:
                raise BehaviorAttestationError(
                    "EFFECT attestation requires external_effect_receipt_digest"
                )
            if self.external_effect_subject_digest is None:
                raise BehaviorAttestationError(
                    "EFFECT attestation requires external_effect_subject_digest"
                )
            _require_digest(
                self.external_effect_receipt_digest,
                "external_effect_receipt_digest",
            )
            _require_digest(
                self.external_effect_subject_digest,
                "external_effect_subject_digest",
            )


@runtime_checkable
class BehaviorAttestationTransport(Protocol):
    consumer_id: str
    provider_id: str

    def observe(
        self,
        requirement: BehaviorAttestationRequirement,
        behavior_requirement: BehaviorEffectRequirement,
        behavior_receipt: BehaviorEffectVerificationReceipt,
    ) -> BehaviorAttestationObservation:
        ...


@dataclass(frozen=True, slots=True)
class BehaviorAttestationReceipt:
    sequence: int
    task_id: str
    packet_digest: str
    consumer_id: str
    probe_id: str
    evidence_kind: str
    expected_declaration_digest: str
    expected_provider_id: str
    expected_provider_key_id: str
    expected_provider_key_digest: str
    expected_effect_subject_digest: str | None
    behavior_effect_receipt_digest: str
    observed_behavior_effect_receipt_digest: str | None
    observed_declaration_digest: str | None
    observed_process_instance_id: str | None
    observed_runtime_state_digest: str | None
    observed_stimulus_digest: str | None
    observed_outcome_digest: str | None
    observed_raw_response_digest: str | None
    observed_provider_id: str | None
    observed_provider_key_id: str | None
    observed_provider_key_digest: str | None
    observed_attestation_nonce: str | None
    observed_attestation_subject_digest: str | None
    observed_attestation_signature: str | None
    observed_signature_valid: bool | None
    observed_external_effect_id: str | None
    observed_external_effect_receipt_digest: str | None
    observed_external_effect_subject_digest: str | None
    observed_external_evidence_digest: str | None
    evidence_ref: str | None
    status: str
    predecessor_digest: str
    receipt_digest: str


class BehaviorAttestationStore:
    """Append-only verifier-bound provenance above behavior/effect PASS."""

    GENESIS_HEAD = sha256_hex(
        b"vera-mono-behavior-attestation-genesis-v1"
    )

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attestations (
                    sequence INTEGER PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    consumer_id TEXT NOT NULL,
                    probe_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    provider_key_id TEXT NOT NULL,
                    attestation_nonce TEXT,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    predecessor_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(provider_id, provider_key_id, attestation_nonce)
                );
                """
            )
            if db.execute(
                "SELECT 1 FROM meta WHERE key='sequence'"
            ).fetchone() is None:
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('sequence','0')"
                )
                db.execute(
                    "INSERT INTO meta(key,value) VALUES('head',?)",
                    (self.GENESIS_HEAD,),
                )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _meta(db: sqlite3.Connection) -> tuple[int, str]:
        sequence = int(
            db.execute(
                "SELECT value FROM meta WHERE key='sequence'"
            ).fetchone()[0]
        )
        head = str(
            db.execute(
                "SELECT value FROM meta WHERE key='head'"
            ).fetchone()[0]
        )
        return sequence, head

    @staticmethod
    def _status(
        requirement: BehaviorAttestationRequirement,
        behavior_requirement: BehaviorEffectRequirement,
        behavior_receipt: BehaviorEffectVerificationReceipt,
        observation: BehaviorAttestationObservation,
    ) -> str:
        observation.validate()
        if (
            observation.consumer_id != requirement.consumer_id
            or observation.probe_id != requirement.probe_id
        ):
            raise BehaviorAttestationError(
                "behavior attestation observation identity mismatch"
            )
        if not observation.available:
            return "UNAVAILABLE"
        if (
            behavior_receipt.status != "PASS"
            or behavior_receipt.consumer_id != requirement.consumer_id
            or behavior_receipt.probe_id != requirement.probe_id
            or behavior_receipt.evidence_kind
            != behavior_requirement.evidence_kind
        ):
            return "FAIL"
        if (
            observation.evidence_kind != behavior_requirement.evidence_kind
            or observation.declaration_digest != requirement.declaration_digest
            or observation.behavior_effect_receipt_digest
            != behavior_receipt.receipt_digest
            or observation.process_instance_id
            != behavior_receipt.observed_process_instance_id
            or observation.runtime_state_digest
            != behavior_receipt.observed_runtime_state_digest
            or observation.stimulus_digest
            != behavior_receipt.observed_stimulus_digest
            or observation.outcome_digest
            != behavior_receipt.observed_outcome_digest
            or observation.stimulus_digest
            != behavior_requirement.expected_stimulus_digest
            or observation.outcome_digest
            != behavior_requirement.expected_outcome_digest
            or observation.provider_id != requirement.provider_id
            or observation.provider_key_id != requirement.provider_key_id
            or observation.provider_key_digest
            != requirement.provider_key_digest
            or observation.signature_valid is not True
            or observation.raw_response_digest is None
            or observation.attestation_nonce is None
            or observation.attestation_subject_digest is None
            or observation.external_evidence_digest is None
            or observation.evidence_ref is None
        ):
            return "FAIL"
        if behavior_requirement.evidence_kind == "BEHAVIOR":
            if (
                requirement.effect_subject_digest is not None
                or observation.external_effect_id is not None
                or observation.external_effect_receipt_digest is not None
                or observation.external_effect_subject_digest is not None
            ):
                return "FAIL"
        else:
            if (
                requirement.effect_subject_digest is None
                or observation.external_effect_id
                != behavior_receipt.external_effect_id
                or observation.external_effect_receipt_digest
                != behavior_receipt.external_effect_receipt_digest
                or observation.external_effect_subject_digest
                != requirement.effect_subject_digest
            ):
                return "FAIL"
        return "PASS"

    def append(
        self,
        *,
        task_id: str,
        packet_digest: str,
        requirement: BehaviorAttestationRequirement,
        behavior_requirement: BehaviorEffectRequirement,
        behavior_receipt: BehaviorEffectVerificationReceipt,
        observation: BehaviorAttestationObservation,
    ) -> BehaviorAttestationReceipt:
        if type(task_id) is not str or not task_id:
            raise BehaviorAttestationError("task_id must be non-empty")
        _require_digest(packet_digest, "packet_digest")
        status = self._status(
            requirement,
            behavior_requirement,
            behavior_receipt,
            observation,
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if observation.attestation_nonce is not None:
                replay = db.execute(
                    """
                    SELECT receipt_digest FROM attestations
                    WHERE provider_id=? AND provider_key_id=?
                      AND attestation_nonce=?
                    LIMIT 1
                    """,
                    (
                        requirement.provider_id,
                        requirement.provider_key_id,
                        observation.attestation_nonce,
                    ),
                ).fetchone()
                if replay is not None:
                    raise BehaviorAttestationError(
                        "behavior attestation nonce replay detected"
                    )
            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            payload = {
                "schema": "VERA_MONO_BEHAVIOR_ATTESTATION_V1",
                "sequence": next_sequence,
                "task_id": task_id,
                "packet_digest": packet_digest,
                "consumer_id": requirement.consumer_id,
                "probe_id": requirement.probe_id,
                "evidence_kind": behavior_requirement.evidence_kind,
                "expected_declaration_digest": requirement.declaration_digest,
                "expected_provider_id": requirement.provider_id,
                "expected_provider_key_id": requirement.provider_key_id,
                "expected_provider_key_digest": requirement.provider_key_digest,
                "expected_effect_subject_digest": requirement.effect_subject_digest,
                "behavior_effect_receipt_digest": behavior_receipt.receipt_digest,
                "observed_behavior_effect_receipt_digest": (
                    observation.behavior_effect_receipt_digest
                ),
                "observed_declaration_digest": observation.declaration_digest,
                "observed_process_instance_id": observation.process_instance_id,
                "observed_runtime_state_digest": observation.runtime_state_digest,
                "observed_stimulus_digest": observation.stimulus_digest,
                "observed_outcome_digest": observation.outcome_digest,
                "observed_raw_response_digest": observation.raw_response_digest,
                "observed_provider_id": observation.provider_id,
                "observed_provider_key_id": observation.provider_key_id,
                "observed_provider_key_digest": observation.provider_key_digest,
                "observed_attestation_nonce": observation.attestation_nonce,
                "observed_attestation_subject_digest": (
                    observation.attestation_subject_digest
                ),
                "observed_attestation_signature": observation.attestation_signature,
                "observed_signature_valid": observation.signature_valid,
                "observed_external_effect_id": observation.external_effect_id,
                "observed_external_effect_receipt_digest": (
                    observation.external_effect_receipt_digest
                ),
                "observed_external_effect_subject_digest": (
                    observation.external_effect_subject_digest
                ),
                "observed_external_evidence_digest": (
                    observation.external_evidence_digest
                ),
                "evidence_ref": observation.evidence_ref,
                "status": status,
                "predecessor_digest": predecessor,
            }
            digest = sha256_hex(canonical_json_bytes(payload))
            db.execute(
                """
                INSERT INTO attestations(
                    sequence,task_id,consumer_id,probe_id,
                    provider_id,provider_key_id,attestation_nonce,
                    receipt_digest,predecessor_digest,payload_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    next_sequence,
                    task_id,
                    requirement.consumer_id,
                    requirement.probe_id,
                    requirement.provider_id,
                    requirement.provider_key_id,
                    observation.attestation_nonce,
                    digest,
                    predecessor,
                    canonical_json(payload),
                ),
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='sequence'",
                (str(next_sequence),),
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='head'",
                (digest,),
            )
            db.commit()
        return self.latest(
            task_id,
            requirement.consumer_id,
            requirement.probe_id,
        )

    def latest(
        self,
        task_id: str,
        consumer_id: str,
        probe_id: str,
    ) -> BehaviorAttestationReceipt:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM attestations
                WHERE task_id=? AND consumer_id=? AND probe_id=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (task_id, consumer_id, probe_id),
            ).fetchone()
        if row is None:
            raise KeyError((task_id, consumer_id, probe_id))
        return self._row(row)

    def receipts(
        self,
        task_id: str | None = None,
    ) -> tuple[BehaviorAttestationReceipt, ...]:
        with self._connect() as db:
            if task_id is None:
                rows = db.execute(
                    "SELECT * FROM attestations ORDER BY sequence"
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM attestations
                    WHERE task_id=?
                    ORDER BY sequence
                    """,
                    (task_id,),
                ).fetchall()
        return tuple(self._row(row) for row in rows)

    def verify_chain(self) -> str:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM attestations ORDER BY sequence"
            ).fetchall()
            sequence, head = self._meta(db)
        predecessor = self.GENESIS_HEAD
        expected_sequence = 1
        for row in rows:
            receipt = self._row(row)
            if receipt.sequence != expected_sequence:
                raise BehaviorAttestationError(
                    "behavior attestation sequence gap"
                )
            if receipt.predecessor_digest != predecessor:
                raise BehaviorAttestationError(
                    "behavior attestation predecessor mismatch"
                )
            observed = sha256_hex(canonical_json_bytes(self._payload(receipt)))
            if observed != receipt.receipt_digest:
                raise BehaviorAttestationError(
                    "behavior attestation receipt digest mismatch"
                )
            predecessor = observed
            expected_sequence += 1
        if sequence != expected_sequence - 1:
            raise BehaviorAttestationError(
                "behavior attestation meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if head != expected_head:
            raise BehaviorAttestationError(
                "behavior attestation meta head mismatch"
            )
        return head

    def context(self) -> dict[str, Any]:
        receipts = self.receipts()
        return {
            "schema": "VERA_MONO_BEHAVIOR_ATTESTATION_CONTEXT_V1",
            "sequence": len(receipts),
            "head_digest": self.verify_chain(),
            "task_ids": sorted({item.task_id for item in receipts}),
            "latest": [
                {
                    "task_id": item.task_id,
                    "consumer_id": item.consumer_id,
                    "probe_id": item.probe_id,
                    "evidence_kind": item.evidence_kind,
                    "expected_declaration_digest": item.expected_declaration_digest,
                    "expected_provider_id": item.expected_provider_id,
                    "expected_provider_key_id": item.expected_provider_key_id,
                    "behavior_effect_receipt_digest": (
                        item.behavior_effect_receipt_digest
                    ),
                    "observed_attestation_nonce": item.observed_attestation_nonce,
                    "observed_attestation_subject_digest": (
                        item.observed_attestation_subject_digest
                    ),
                    "status": item.status,
                    "receipt_digest": item.receipt_digest,
                }
                for item in receipts
            ],
        }

    @staticmethod
    def _payload(
        receipt: BehaviorAttestationReceipt,
    ) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_BEHAVIOR_ATTESTATION_V1",
            "sequence": receipt.sequence,
            "task_id": receipt.task_id,
            "packet_digest": receipt.packet_digest,
            "consumer_id": receipt.consumer_id,
            "probe_id": receipt.probe_id,
            "evidence_kind": receipt.evidence_kind,
            "expected_declaration_digest": receipt.expected_declaration_digest,
            "expected_provider_id": receipt.expected_provider_id,
            "expected_provider_key_id": receipt.expected_provider_key_id,
            "expected_provider_key_digest": receipt.expected_provider_key_digest,
            "expected_effect_subject_digest": receipt.expected_effect_subject_digest,
            "behavior_effect_receipt_digest": receipt.behavior_effect_receipt_digest,
            "observed_behavior_effect_receipt_digest": (
                receipt.observed_behavior_effect_receipt_digest
            ),
            "observed_declaration_digest": receipt.observed_declaration_digest,
            "observed_process_instance_id": receipt.observed_process_instance_id,
            "observed_runtime_state_digest": receipt.observed_runtime_state_digest,
            "observed_stimulus_digest": receipt.observed_stimulus_digest,
            "observed_outcome_digest": receipt.observed_outcome_digest,
            "observed_raw_response_digest": receipt.observed_raw_response_digest,
            "observed_provider_id": receipt.observed_provider_id,
            "observed_provider_key_id": receipt.observed_provider_key_id,
            "observed_provider_key_digest": receipt.observed_provider_key_digest,
            "observed_attestation_nonce": receipt.observed_attestation_nonce,
            "observed_attestation_subject_digest": (
                receipt.observed_attestation_subject_digest
            ),
            "observed_attestation_signature": receipt.observed_attestation_signature,
            "observed_signature_valid": receipt.observed_signature_valid,
            "observed_external_effect_id": receipt.observed_external_effect_id,
            "observed_external_effect_receipt_digest": (
                receipt.observed_external_effect_receipt_digest
            ),
            "observed_external_effect_subject_digest": (
                receipt.observed_external_effect_subject_digest
            ),
            "observed_external_evidence_digest": (
                receipt.observed_external_evidence_digest
            ),
            "evidence_ref": receipt.evidence_ref,
            "status": receipt.status,
            "predecessor_digest": receipt.predecessor_digest,
        }

    @classmethod
    def _row(cls, row: sqlite3.Row) -> BehaviorAttestationReceipt:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise BehaviorAttestationError(
                "behavior attestation payload is invalid JSON"
            ) from exc
        required = {
            "schema",
            "sequence",
            "task_id",
            "packet_digest",
            "consumer_id",
            "probe_id",
            "evidence_kind",
            "expected_declaration_digest",
            "expected_provider_id",
            "expected_provider_key_id",
            "expected_provider_key_digest",
            "expected_effect_subject_digest",
            "behavior_effect_receipt_digest",
            "observed_behavior_effect_receipt_digest",
            "observed_declaration_digest",
            "observed_process_instance_id",
            "observed_runtime_state_digest",
            "observed_stimulus_digest",
            "observed_outcome_digest",
            "observed_raw_response_digest",
            "observed_provider_id",
            "observed_provider_key_id",
            "observed_provider_key_digest",
            "observed_attestation_nonce",
            "observed_attestation_subject_digest",
            "observed_attestation_signature",
            "observed_signature_valid",
            "observed_external_effect_id",
            "observed_external_effect_receipt_digest",
            "observed_external_effect_subject_digest",
            "observed_external_evidence_digest",
            "evidence_ref",
            "status",
            "predecessor_digest",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise BehaviorAttestationError(
                "behavior attestation payload field set mismatch"
            )
        if payload["schema"] != "VERA_MONO_BEHAVIOR_ATTESTATION_V1":
            raise BehaviorAttestationError(
                "unsupported behavior attestation schema"
            )
        if payload["status"] not in BEHAVIOR_ATTESTATION_STATUSES:
            raise BehaviorAttestationError(
                "unsupported behavior attestation status"
            )
        if (
            int(payload["sequence"]) != int(row["sequence"])
            or payload["task_id"] != row["task_id"]
            or payload["consumer_id"] != row["consumer_id"]
            or payload["probe_id"] != row["probe_id"]
            or payload["expected_provider_id"] != row["provider_id"]
            or payload["expected_provider_key_id"] != row["provider_key_id"]
            or payload["observed_attestation_nonce"] != row["attestation_nonce"]
            or payload["predecessor_digest"] != row["predecessor_digest"]
        ):
            raise BehaviorAttestationError(
                "behavior attestation row/payload mismatch"
            )
        receipt = BehaviorAttestationReceipt(
            sequence=int(payload["sequence"]),
            task_id=payload["task_id"],
            packet_digest=payload["packet_digest"],
            consumer_id=payload["consumer_id"],
            probe_id=payload["probe_id"],
            evidence_kind=payload["evidence_kind"],
            expected_declaration_digest=payload["expected_declaration_digest"],
            expected_provider_id=payload["expected_provider_id"],
            expected_provider_key_id=payload["expected_provider_key_id"],
            expected_provider_key_digest=payload["expected_provider_key_digest"],
            expected_effect_subject_digest=payload["expected_effect_subject_digest"],
            behavior_effect_receipt_digest=payload["behavior_effect_receipt_digest"],
            observed_behavior_effect_receipt_digest=(
                payload["observed_behavior_effect_receipt_digest"]
            ),
            observed_declaration_digest=payload["observed_declaration_digest"],
            observed_process_instance_id=payload["observed_process_instance_id"],
            observed_runtime_state_digest=payload["observed_runtime_state_digest"],
            observed_stimulus_digest=payload["observed_stimulus_digest"],
            observed_outcome_digest=payload["observed_outcome_digest"],
            observed_raw_response_digest=payload["observed_raw_response_digest"],
            observed_provider_id=payload["observed_provider_id"],
            observed_provider_key_id=payload["observed_provider_key_id"],
            observed_provider_key_digest=payload["observed_provider_key_digest"],
            observed_attestation_nonce=payload["observed_attestation_nonce"],
            observed_attestation_subject_digest=(
                payload["observed_attestation_subject_digest"]
            ),
            observed_attestation_signature=payload["observed_attestation_signature"],
            observed_signature_valid=payload["observed_signature_valid"],
            observed_external_effect_id=payload["observed_external_effect_id"],
            observed_external_effect_receipt_digest=(
                payload["observed_external_effect_receipt_digest"]
            ),
            observed_external_effect_subject_digest=(
                payload["observed_external_effect_subject_digest"]
            ),
            observed_external_evidence_digest=(
                payload["observed_external_evidence_digest"]
            ),
            evidence_ref=payload["evidence_ref"],
            status=payload["status"],
            predecessor_digest=payload["predecessor_digest"],
            receipt_digest=str(row["receipt_digest"]),
        )
        if (
            sha256_hex(canonical_json_bytes(cls._payload(receipt)))
            != receipt.receipt_digest
        ):
            raise BehaviorAttestationError(
                "behavior attestation receipt digest mismatch"
            )
        return receipt


class JsonFileBehaviorAttestationTransport:
    """Read-only host evidence transport with verifier-bound attestation."""

    PAYLOAD_FIELDS = frozenset(
        {
            "schema",
            "consumer_id",
            "probe_id",
            "evidence_kind",
            "declaration_digest",
            "behavior_effect_receipt_digest",
            "process_instance_id",
            "runtime_state_digest",
            "stimulus_digest",
            "outcome_digest",
            "raw_response_b64",
            "provider_id",
            "provider_key_id",
            "provider_key_digest",
            "attestation_nonce",
            "external_effect_id",
            "external_effect_receipt_b64",
            "external_effect_subject_digest",
            "signature",
        }
    )

    def __init__(
        self,
        *,
        consumer_id: str,
        path: str | Path,
        verifier: BehaviorEvidenceAttestationVerifier,
    ):
        if type(consumer_id) is not str or not consumer_id:
            raise ValueError("consumer_id must be non-empty")
        if not isinstance(verifier, BehaviorEvidenceAttestationVerifier):
            raise TypeError(
                "verifier must satisfy BehaviorEvidenceAttestationVerifier"
            )
        self.consumer_id = consumer_id
        self.path = Path(path)
        self.verifier = verifier
        self.provider_id = verifier.provider_id

    @staticmethod
    def _decode_b64(value: Any, label: str) -> bytes:
        if type(value) is not str or not value:
            raise BehaviorAttestationError(
                f"{label} must be non-empty base64 text"
            )
        try:
            return base64.b64decode(value.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise BehaviorAttestationError(
                f"{label} is not valid base64"
            ) from exc

    def observe(
        self,
        requirement: BehaviorAttestationRequirement,
        behavior_requirement: BehaviorEffectRequirement,
        behavior_receipt: BehaviorEffectVerificationReceipt,
    ) -> BehaviorAttestationObservation:
        if requirement.consumer_id != self.consumer_id:
            raise BehaviorAttestationError(
                "behavior attestation transport consumer mismatch"
            )
        if requirement.provider_id != self.verifier.provider_id:
            raise BehaviorAttestationError(
                "behavior attestation verifier provider mismatch"
            )
        if requirement.provider_key_id != self.verifier.key_id:
            raise BehaviorAttestationError(
                "behavior attestation verifier key id mismatch"
            )
        if requirement.provider_key_digest != self.verifier.key_digest:
            raise BehaviorAttestationError(
                "behavior attestation verifier key digest mismatch"
            )
        if not self.path.is_file():
            return BehaviorAttestationObservation(
                consumer_id=self.consumer_id,
                probe_id=requirement.probe_id,
                available=False,
                evidence_kind=None,
                declaration_digest=None,
                behavior_effect_receipt_digest=None,
                process_instance_id=None,
                runtime_state_digest=None,
                stimulus_digest=None,
                outcome_digest=None,
                raw_response_digest=None,
                provider_id=None,
                provider_key_id=None,
                provider_key_digest=None,
                attestation_nonce=None,
                attestation_subject_digest=None,
                attestation_signature=None,
                signature_valid=None,
                external_effect_id=None,
                external_effect_receipt_digest=None,
                external_effect_subject_digest=None,
                external_evidence_digest=None,
                evidence_ref=None,
            )
        raw_file = self.path.read_bytes()
        try:
            payload = json.loads(raw_file.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BehaviorAttestationError(
                "behavior attestation evidence is not valid UTF-8 JSON"
            ) from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != set(self.PAYLOAD_FIELDS)
        ):
            raise BehaviorAttestationError(
                "behavior attestation evidence field set mismatch"
            )
        if payload["schema"] != "VERA_MONO_EXTERNAL_BEHAVIOR_ATTESTATION_V1":
            raise BehaviorAttestationError(
                "unsupported external behavior attestation schema"
            )
        raw_response = self._decode_b64(
            payload["raw_response_b64"],
            "raw_response_b64",
        )
        effect_receipt_b64 = payload["external_effect_receipt_b64"]
        if effect_receipt_b64 is None:
            effect_receipt_digest = None
        else:
            effect_receipt_digest = sha256_hex(
                self._decode_b64(
                    effect_receipt_b64,
                    "external_effect_receipt_b64",
                )
            )
        subject = BehaviorAttestationSubject(
            consumer_id=payload["consumer_id"],
            probe_id=payload["probe_id"],
            evidence_kind=payload["evidence_kind"],
            declaration_digest=payload["declaration_digest"],
            behavior_effect_receipt_digest=(
                payload["behavior_effect_receipt_digest"]
            ),
            process_instance_id=payload["process_instance_id"],
            runtime_state_digest=payload["runtime_state_digest"],
            stimulus_digest=payload["stimulus_digest"],
            outcome_digest=payload["outcome_digest"],
            raw_response_digest=sha256_hex(raw_response),
            provider_id=payload["provider_id"],
            provider_key_id=payload["provider_key_id"],
            provider_key_digest=payload["provider_key_digest"],
            attestation_nonce=payload["attestation_nonce"],
            external_effect_id=payload["external_effect_id"],
            external_effect_receipt_digest=effect_receipt_digest,
            external_effect_subject_digest=(
                payload["external_effect_subject_digest"]
            ),
        )
        subject.validate()
        signature = payload["signature"]
        observation = BehaviorAttestationObservation(
            consumer_id=self.consumer_id,
            probe_id=requirement.probe_id,
            available=True,
            evidence_kind=subject.evidence_kind,
            declaration_digest=subject.declaration_digest,
            behavior_effect_receipt_digest=subject.behavior_effect_receipt_digest,
            process_instance_id=subject.process_instance_id,
            runtime_state_digest=subject.runtime_state_digest,
            stimulus_digest=subject.stimulus_digest,
            outcome_digest=subject.outcome_digest,
            raw_response_digest=subject.raw_response_digest,
            provider_id=subject.provider_id,
            provider_key_id=subject.provider_key_id,
            provider_key_digest=subject.provider_key_digest,
            attestation_nonce=subject.attestation_nonce,
            attestation_subject_digest=subject.digest,
            attestation_signature=signature,
            signature_valid=self.verifier.verify(
                subject.canonical_bytes(),
                signature,
            ),
            external_effect_id=subject.external_effect_id,
            external_effect_receipt_digest=subject.external_effect_receipt_digest,
            external_effect_subject_digest=subject.external_effect_subject_digest,
            external_evidence_digest=sha256_hex(raw_file),
            evidence_ref=str(self.path.resolve()),
        )
        observation.validate()
        return observation
