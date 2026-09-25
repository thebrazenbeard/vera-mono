from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import base64
import json
import sqlite3
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from .behavior_effect_verification import BehaviorEffectRequirement, BehaviorEffectVerificationReceipt


class IndependentBehaviorReviewError(ValueError):
    pass


INDEPENDENT_BEHAVIOR_REVIEW_VERIFY_PREFIX = "INDEPENDENT_BEHAVIOR_REVIEW_VERIFY"
INDEPENDENT_BEHAVIOR_REVIEW_STATUSES = frozenset({"PASS", "FAIL", "UNAVAILABLE"})


def _text(value: str, label: str) -> str:
    if type(value) is not str or not value:
        raise IndependentBehaviorReviewError(f"{label} must be a non-empty exact string")
    return value


def _digest(value: str, label: str) -> str:
    if type(value) is not str or len(value) != 64:
        raise IndependentBehaviorReviewError(f"{label} must be an exact SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise IndependentBehaviorReviewError(f"{label} must be hexadecimal") from exc
    return value.lower()


@dataclass(frozen=True, slots=True)
class IndependentBehaviorReviewRequirement:
    consumer_id: str
    probe_id: str
    review_id: str
    subject_actor_id: str
    declaration_digest: str
    held_out_probe_set_digest: str
    probe_curator_id: str
    evaluator_id: str
    evaluator_key_id: str
    evaluator_key_digest: str
    authority_id: str
    authority_key_id: str
    authority_key_digest: str

    @classmethod
    def parse(cls, value: str) -> "IndependentBehaviorReviewRequirement":
        parts = value.split("|") if type(value) is str else ()
        if len(parts) != 14 or parts[0] != INDEPENDENT_BEHAVIOR_REVIEW_VERIFY_PREFIX or any(not x for x in parts[1:]):
            raise IndependentBehaviorReviewError(
                "independent review requirement must use "
                "'INDEPENDENT_BEHAVIOR_REVIEW_VERIFY|<consumer-id>|<probe-id>|<review-id>|"
                "<subject-actor-id>|<declaration-sha256>|<held-out-probe-set-sha256>|"
                "<probe-curator-id>|<evaluator-id>|<evaluator-key-id>|<evaluator-key-sha256>|"
                "<authority-id>|<authority-key-id>|<authority-key-sha256>'"
            )
        item = cls(
            consumer_id=parts[1], probe_id=parts[2], review_id=parts[3],
            subject_actor_id=parts[4], declaration_digest=_digest(parts[5], "declaration_digest"),
            held_out_probe_set_digest=_digest(parts[6], "held_out_probe_set_digest"),
            probe_curator_id=parts[7], evaluator_id=parts[8], evaluator_key_id=parts[9],
            evaluator_key_digest=_digest(parts[10], "evaluator_key_digest"),
            authority_id=parts[11], authority_key_id=parts[12],
            authority_key_digest=_digest(parts[13], "authority_key_digest"),
        )
        item.validate()
        return item

    def validate(self) -> None:
        for label, value in (
            ("consumer_id", self.consumer_id), ("probe_id", self.probe_id), ("review_id", self.review_id),
            ("subject_actor_id", self.subject_actor_id), ("probe_curator_id", self.probe_curator_id),
            ("evaluator_id", self.evaluator_id), ("evaluator_key_id", self.evaluator_key_id),
            ("authority_id", self.authority_id), ("authority_key_id", self.authority_key_id),
        ):
            _text(value, label)
        for label, value in (
            ("declaration_digest", self.declaration_digest),
            ("held_out_probe_set_digest", self.held_out_probe_set_digest),
            ("evaluator_key_digest", self.evaluator_key_digest),
            ("authority_key_digest", self.authority_key_digest),
        ):
            _digest(value, label)
        if len({self.subject_actor_id, self.probe_curator_id, self.evaluator_id, self.authority_id}) != 4:
            raise IndependentBehaviorReviewError(
                "independent review requires distinct subject, probe curator, evaluator, and authority actors"
            )


def independent_behavior_review_requirements(evidence_requirements: Sequence[str]) -> tuple[IndependentBehaviorReviewRequirement, ...]:
    return tuple(
        IndependentBehaviorReviewRequirement.parse(raw)
        for raw in evidence_requirements
        if isinstance(raw, str) and raw.startswith(INDEPENDENT_BEHAVIOR_REVIEW_VERIFY_PREFIX + "|")
    )


@dataclass(frozen=True, slots=True)
class IndependentReviewAuthoritySubject:
    review_id: str
    subject_actor_id: str
    held_out_probe_set_digest: str
    probe_curator_id: str
    evaluator_id: str
    evaluator_key_id: str
    evaluator_key_digest: str
    authority_id: str
    authority_key_id: str
    authority_key_digest: str
    evaluator_currentness_digest: str
    operationally_separate: bool
    current: bool
    authority_nonce: str

    def canonical_body(self) -> dict[str, Any]:
        return {"schema": "VERA_MONO_INDEPENDENT_REVIEW_AUTHORITY_SUBJECT_V1", **asdict(self)}

    def canonical_bytes(self) -> bytes:
        if len({self.subject_actor_id, self.probe_curator_id, self.evaluator_id, self.authority_id}) != 4:
            raise IndependentBehaviorReviewError("independent review authority roles must be distinct")
        for x in (self.held_out_probe_set_digest, self.evaluator_key_digest, self.authority_key_digest, self.evaluator_currentness_digest):
            _digest(x, "authority digest")
        if type(self.current) is not bool or type(self.operationally_separate) is not bool:
            raise IndependentBehaviorReviewError("authority current/separation flags must be boolean")
        return canonical_json_bytes(self.canonical_body())

    @property
    def digest(self) -> str:
        return sha256_hex(self.canonical_bytes())


@dataclass(frozen=True, slots=True)
class IndependentBehaviorReviewSubject:
    consumer_id: str
    probe_id: str
    review_id: str
    declaration_digest: str
    held_out_probe_set_digest: str
    probe_curator_id: str
    behavior_effect_receipt_digest: str
    process_instance_id: str
    runtime_state_digest: str
    stimulus_digest: str
    outcome_digest: str
    evaluator_id: str
    evaluator_key_id: str
    evaluator_key_digest: str
    evaluator_currentness_digest: str
    authority_subject_digest: str
    authority_evidence_digest: str
    review_nonce: str
    verdict: str
    result_digest: str
    result_receipt_digest: str
    review_provenance_digest: str

    def canonical_body(self) -> dict[str, Any]:
        return {"schema": "VERA_MONO_INDEPENDENT_BEHAVIOR_REVIEW_SUBJECT_V1", **asdict(self)}

    def canonical_bytes(self) -> bytes:
        for value in (
            self.declaration_digest, self.held_out_probe_set_digest, self.behavior_effect_receipt_digest,
            self.runtime_state_digest, self.stimulus_digest, self.outcome_digest, self.evaluator_key_digest,
            self.evaluator_currentness_digest, self.authority_subject_digest, self.authority_evidence_digest,
            self.result_digest, self.result_receipt_digest, self.review_provenance_digest,
        ):
            _digest(value, "review digest")
        return canonical_json_bytes(self.canonical_body())

    @property
    def digest(self) -> str:
        return sha256_hex(self.canonical_bytes())


@runtime_checkable
class IndependentReviewSignatureVerifier(Protocol):
    actor_id: str
    key_id: str
    key_digest: str
    def verify(self, subject: bytes, signature: str) -> bool: ...


class Ed25519IndependentReviewVerifier:
    """Public-key-only verifier for externally signed review evidence."""

    def __init__(
        self,
        *,
        actor_id: str,
        key_id: str,
        public_key: bytes,
    ):
        self.actor_id = _text(actor_id, "actor_id")
        self.key_id = _text(key_id, "key_id")
        if type(public_key) is not bytes or len(public_key) != 32:
            raise IndependentBehaviorReviewError(
                "Ed25519 public_key must be exactly 32 raw bytes"
            )
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        self._public_key_bytes = public_key
        self._public_key = Ed25519PublicKey.from_public_bytes(public_key)
        self.key_digest = sha256_hex(public_key)

    @property
    def public_key_bytes(self) -> bytes:
        return self._public_key_bytes

    def verify(self, subject: bytes, signature: str) -> bool:
        if type(subject) is not bytes or not subject:
            return False
        if type(signature) is not str or not signature:
            return False
        try:
            signature_bytes = base64.b64decode(
                signature.encode("ascii"),
                validate=True,
            )
        except (UnicodeEncodeError, ValueError):
            return False
        if len(signature_bytes) != 64:
            return False
        from cryptography.exceptions import InvalidSignature
        try:
            self._public_key.verify(signature_bytes, subject)
        except (InvalidSignature, ValueError):
            return False
        return True


@dataclass(frozen=True, slots=True)
class IndependentBehaviorReviewObservation:
    consumer_id: str
    probe_id: str
    review_id: str
    available: bool
    authority_current: bool | None = None
    operationally_separate: bool | None = None
    subject_actor_id: str | None = None
    declaration_digest: str | None = None
    held_out_probe_set_digest: str | None = None
    probe_curator_id: str | None = None
    behavior_effect_receipt_digest: str | None = None
    process_instance_id: str | None = None
    runtime_state_digest: str | None = None
    stimulus_digest: str | None = None
    outcome_digest: str | None = None
    evaluator_id: str | None = None
    evaluator_key_id: str | None = None
    evaluator_key_digest: str | None = None
    evaluator_currentness_digest: str | None = None
    authority_id: str | None = None
    authority_key_id: str | None = None
    authority_key_digest: str | None = None
    authority_nonce: str | None = None
    authority_subject_digest: str | None = None
    authority_signature_valid: bool | None = None
    authority_evidence_digest: str | None = None
    review_nonce: str | None = None
    verdict: str | None = None
    result_digest: str | None = None
    result_receipt_digest: str | None = None
    review_provenance_digest: str | None = None
    review_subject_digest: str | None = None
    evaluator_signature_valid: bool | None = None
    review_evidence_digest: str | None = None
    authority_evidence_ref: str | None = None
    review_evidence_ref: str | None = None


@runtime_checkable
class IndependentBehaviorReviewTransport(Protocol):
    consumer_id: str
    review_id: str
    def observe(
        self,
        requirement: IndependentBehaviorReviewRequirement,
        behavior_requirement: BehaviorEffectRequirement,
        behavior_receipt: BehaviorEffectVerificationReceipt,
    ) -> IndependentBehaviorReviewObservation: ...


class JsonFileIndependentBehaviorReviewTransport:
    """Read-only two-signer evidence transport; signing keys remain external to Vera."""

    def __init__(self, *, consumer_id: str, review_id: str, authority_path: str | Path, review_path: str | Path,
                 authority_verifier: IndependentReviewSignatureVerifier, evaluator_verifier: IndependentReviewSignatureVerifier):
        self.consumer_id = _text(consumer_id, "consumer_id")
        self.review_id = _text(review_id, "review_id")
        if not isinstance(authority_verifier, IndependentReviewSignatureVerifier) or not isinstance(evaluator_verifier, IndependentReviewSignatureVerifier):
            raise TypeError("independent review verifiers must satisfy IndependentReviewSignatureVerifier")
        self.authority_path = Path(authority_path)
        self.review_path = Path(review_path)
        self.authority_verifier = authority_verifier
        self.evaluator_verifier = evaluator_verifier

    @staticmethod
    def _load(path: Path) -> tuple[bytes, Mapping[str, Any]] | None:
        if not path.is_file():
            return None
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IndependentBehaviorReviewError(f"invalid independent review JSON: {path}") from exc
        if not isinstance(payload, Mapping):
            raise IndependentBehaviorReviewError("independent review JSON must be an object")
        return raw, payload

    @staticmethod
    def _b64(value: Any, label: str) -> bytes:
        try:
            return base64.b64decode(value.encode("ascii"), validate=True)
        except Exception as exc:
            raise IndependentBehaviorReviewError(f"{label} is not valid base64") from exc

    def observe(self, requirement, behavior_requirement, behavior_receipt):
        del behavior_requirement, behavior_receipt
        requirement.validate()
        if (requirement.consumer_id, requirement.review_id) != (self.consumer_id, self.review_id):
            raise IndependentBehaviorReviewError("independent review transport identity mismatch")
        if (self.authority_verifier.actor_id, self.authority_verifier.key_id, self.authority_verifier.key_digest) != (
            requirement.authority_id, requirement.authority_key_id, requirement.authority_key_digest
        ):
            raise IndependentBehaviorReviewError("authority verifier identity/key mismatch")
        if (self.evaluator_verifier.actor_id, self.evaluator_verifier.key_id, self.evaluator_verifier.key_digest) != (
            requirement.evaluator_id, requirement.evaluator_key_id, requirement.evaluator_key_digest
        ):
            raise IndependentBehaviorReviewError("evaluator verifier identity/key mismatch")
        authority_loaded, review_loaded = self._load(self.authority_path), self._load(self.review_path)
        if authority_loaded is None or review_loaded is None:
            return IndependentBehaviorReviewObservation(self.consumer_id, requirement.probe_id, self.review_id, False)
        authority_raw, authority = authority_loaded
        review_raw, review = review_loaded
        a = IndependentReviewAuthoritySubject(
            review_id=authority["review_id"], subject_actor_id=authority["subject_actor_id"],
            held_out_probe_set_digest=authority["held_out_probe_set_digest"], probe_curator_id=authority["probe_curator_id"],
            evaluator_id=authority["evaluator_id"], evaluator_key_id=authority["evaluator_key_id"],
            evaluator_key_digest=authority["evaluator_key_digest"], authority_id=authority["authority_id"],
            authority_key_id=authority["authority_key_id"], authority_key_digest=authority["authority_key_digest"],
            evaluator_currentness_digest=authority["evaluator_currentness_digest"],
            operationally_separate=authority["operationally_separate"], current=authority["current"],
            authority_nonce=authority["authority_nonce"],
        )
        authority_digest = sha256_hex(authority_raw)
        provenance = review["provenance"]
        if not isinstance(provenance, Mapping):
            raise IndependentBehaviorReviewError("review provenance must be an object")
        r = IndependentBehaviorReviewSubject(
            consumer_id=review["consumer_id"], probe_id=review["probe_id"], review_id=review["review_id"],
            declaration_digest=review["declaration_digest"], held_out_probe_set_digest=review["held_out_probe_set_digest"],
            probe_curator_id=review["probe_curator_id"], behavior_effect_receipt_digest=review["behavior_effect_receipt_digest"],
            process_instance_id=review["process_instance_id"], runtime_state_digest=review["runtime_state_digest"],
            stimulus_digest=review["stimulus_digest"], outcome_digest=review["outcome_digest"],
            evaluator_id=review["evaluator_id"], evaluator_key_id=review["evaluator_key_id"],
            evaluator_key_digest=review["evaluator_key_digest"], evaluator_currentness_digest=review["evaluator_currentness_digest"],
            authority_subject_digest=review["authority_subject_digest"], authority_evidence_digest=review["authority_evidence_digest"],
            review_nonce=review["review_nonce"], verdict=review["verdict"],
            result_digest=sha256_hex(self._b64(review["result_b64"], "result_b64")),
            result_receipt_digest=sha256_hex(self._b64(review["result_receipt_b64"], "result_receipt_b64")),
            review_provenance_digest=sha256_hex(canonical_json_bytes(dict(provenance))),
        )
        return IndependentBehaviorReviewObservation(
            consumer_id=self.consumer_id, probe_id=requirement.probe_id, review_id=self.review_id, available=True,
            authority_current=a.current, operationally_separate=a.operationally_separate, subject_actor_id=a.subject_actor_id,
            declaration_digest=r.declaration_digest, held_out_probe_set_digest=r.held_out_probe_set_digest,
            probe_curator_id=r.probe_curator_id, behavior_effect_receipt_digest=r.behavior_effect_receipt_digest,
            process_instance_id=r.process_instance_id, runtime_state_digest=r.runtime_state_digest,
            stimulus_digest=r.stimulus_digest, outcome_digest=r.outcome_digest, evaluator_id=r.evaluator_id,
            evaluator_key_id=r.evaluator_key_id, evaluator_key_digest=r.evaluator_key_digest,
            evaluator_currentness_digest=r.evaluator_currentness_digest, authority_id=a.authority_id,
            authority_key_id=a.authority_key_id, authority_key_digest=a.authority_key_digest,
            authority_nonce=a.authority_nonce, authority_subject_digest=a.digest,
            authority_signature_valid=self.authority_verifier.verify(a.canonical_bytes(), authority["signature"]),
            authority_evidence_digest=authority_digest, review_nonce=r.review_nonce, verdict=r.verdict,
            result_digest=r.result_digest, result_receipt_digest=r.result_receipt_digest,
            review_provenance_digest=r.review_provenance_digest, review_subject_digest=r.digest,
            evaluator_signature_valid=self.evaluator_verifier.verify(r.canonical_bytes(), review["signature"]),
            review_evidence_digest=sha256_hex(review_raw), authority_evidence_ref=str(self.authority_path.resolve()),
            review_evidence_ref=str(self.review_path.resolve()),
        )


@dataclass(frozen=True, slots=True)
class IndependentBehaviorReviewReceipt:
    sequence: int
    task_id: str
    consumer_id: str
    probe_id: str
    review_id: str
    status: str
    payload: Mapping[str, Any]
    predecessor_digest: str
    receipt_digest: str


class IndependentBehaviorReviewStore:
    GENESIS_HEAD = sha256_hex(b"vera-mono-independent-behavior-review-genesis-v1")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, consumer_id TEXT NOT NULL,
                probe_id TEXT NOT NULL, review_id TEXT NOT NULL, evaluator_id TEXT, evaluator_key_id TEXT,
                review_nonce TEXT, status TEXT NOT NULL, payload_json TEXT NOT NULL, predecessor_digest TEXT NOT NULL,
                receipt_digest TEXT NOT NULL UNIQUE, UNIQUE(evaluator_id, evaluator_key_id, review_nonce)
            );
            """)
            db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('head',?)", (self.GENESIS_HEAD,))

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _status(requirement, behavior_requirement, behavior_receipt, observation) -> str:
        if (observation.consumer_id, observation.probe_id, observation.review_id) != (
            requirement.consumer_id, requirement.probe_id, requirement.review_id
        ):
            raise IndependentBehaviorReviewError("independent review observation identity mismatch")
        if not observation.available:
            return "UNAVAILABLE"
        if (
            behavior_receipt.status != "PASS"
            or behavior_receipt.consumer_id != requirement.consumer_id
            or behavior_receipt.probe_id != requirement.probe_id
            or observation.subject_actor_id != requirement.subject_actor_id
            or observation.declaration_digest != requirement.declaration_digest
            or observation.held_out_probe_set_digest != requirement.held_out_probe_set_digest
            or observation.probe_curator_id != requirement.probe_curator_id
            or observation.behavior_effect_receipt_digest != behavior_receipt.receipt_digest
            or observation.process_instance_id != behavior_receipt.observed_process_instance_id
            or observation.runtime_state_digest != behavior_receipt.observed_runtime_state_digest
            or observation.stimulus_digest != behavior_receipt.observed_stimulus_digest
            or observation.outcome_digest != behavior_receipt.observed_outcome_digest
            or observation.stimulus_digest != behavior_requirement.expected_stimulus_digest
            or observation.outcome_digest != behavior_requirement.expected_outcome_digest
            or observation.evaluator_id != requirement.evaluator_id
            or observation.evaluator_key_id != requirement.evaluator_key_id
            or observation.evaluator_key_digest != requirement.evaluator_key_digest
            or observation.authority_id != requirement.authority_id
            or observation.authority_key_id != requirement.authority_key_id
            or observation.authority_key_digest != requirement.authority_key_digest
            or observation.authority_current is not True
            or observation.operationally_separate is not True
            or observation.authority_signature_valid is not True
            or observation.evaluator_signature_valid is not True
            or observation.authority_subject_digest is None
            or observation.authority_evidence_digest is None
            or observation.review_subject_digest is None
            or observation.review_evidence_digest is None
            or observation.evaluator_currentness_digest is None
            or observation.review_nonce is None
            or observation.result_digest is None
            or observation.result_receipt_digest is None
            or observation.review_provenance_digest is None
            or observation.verdict != "PASS"
        ):
            return "FAIL"
        return "PASS"

    @staticmethod
    def _requirement_dict(r):
        return {
            "consumer_id": r.consumer_id, "probe_id": r.probe_id, "review_id": r.review_id,
            "subject_actor_id": r.subject_actor_id, "declaration_digest": r.declaration_digest,
            "held_out_probe_set_digest": r.held_out_probe_set_digest, "probe_curator_id": r.probe_curator_id,
            "evaluator_id": r.evaluator_id, "evaluator_key_id": r.evaluator_key_id,
            "evaluator_key_digest": r.evaluator_key_digest, "authority_id": r.authority_id,
            "authority_key_id": r.authority_key_id, "authority_key_digest": r.authority_key_digest,
        }

    def append(self, *, task_id, packet_digest, requirement, behavior_requirement, behavior_receipt, observation):
        status = self._status(requirement, behavior_requirement, behavior_receipt, observation)
        payload = {
            "schema": "VERA_MONO_INDEPENDENT_BEHAVIOR_REVIEW_RECEIPT_V1", "task_id": task_id,
            "packet_digest": packet_digest, "requirement": self._requirement_dict(requirement),
            "behavior_effect_receipt_digest": behavior_receipt.receipt_digest,
            "observation": asdict(observation), "status": status,
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            predecessor = str(db.execute("SELECT value FROM meta WHERE key='head'").fetchone()[0])
            receipt_digest = sha256_hex(canonical_json_bytes({"payload": payload, "predecessor_digest": predecessor}))
            try:
                cur = db.execute(
                    "INSERT INTO reviews(task_id,consumer_id,probe_id,review_id,evaluator_id,evaluator_key_id,review_nonce,status,payload_json,predecessor_digest,receipt_digest) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (task_id, requirement.consumer_id, requirement.probe_id, requirement.review_id,
                     observation.evaluator_id, observation.evaluator_key_id, observation.review_nonce, status,
                     json.dumps(payload, sort_keys=True, separators=(",", ":")), predecessor, receipt_digest),
                )
            except sqlite3.IntegrityError as exc:
                raise IndependentBehaviorReviewError("independent review nonce replay detected") from exc
            db.execute("UPDATE meta SET value=? WHERE key='head'", (receipt_digest,))
            sequence = int(cur.lastrowid)
        return IndependentBehaviorReviewReceipt(sequence, task_id, requirement.consumer_id, requirement.probe_id,
                                                requirement.review_id, status, payload, predecessor, receipt_digest)

    @staticmethod
    def _receipt(row):
        return IndependentBehaviorReviewReceipt(
            int(row["sequence"]), str(row["task_id"]), str(row["consumer_id"]), str(row["probe_id"]),
            str(row["review_id"]), str(row["status"]), json.loads(str(row["payload_json"])),
            str(row["predecessor_digest"]), str(row["receipt_digest"]),
        )

    def latest(self, task_id, consumer_id, probe_id, review_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM reviews WHERE task_id=? AND consumer_id=? AND probe_id=? AND review_id=? ORDER BY sequence DESC LIMIT 1",
                (task_id, consumer_id, probe_id, review_id),
            ).fetchone()
        if row is None:
            raise KeyError((task_id, consumer_id, probe_id, review_id))
        return self._receipt(row)

    def verify_chain(self) -> str:
        head = self.GENESIS_HEAD
        with self._connect() as db:
            rows = db.execute("SELECT * FROM reviews ORDER BY sequence").fetchall()
            stored = str(db.execute("SELECT value FROM meta WHERE key='head'").fetchone()[0])
        for row in rows:
            receipt = self._receipt(row)
            if receipt.predecessor_digest != head:
                raise IndependentBehaviorReviewError("independent review predecessor chain mismatch")
            expected = sha256_hex(canonical_json_bytes({"payload": dict(receipt.payload), "predecessor_digest": head}))
            if expected != receipt.receipt_digest:
                raise IndependentBehaviorReviewError("independent review receipt digest mismatch")
            head = receipt.receipt_digest
        if stored != head:
            raise IndependentBehaviorReviewError("independent review ledger head mismatch")
        return head

    def context(self):
        head = self.verify_chain()
        with self._connect() as db:
            count = int(db.execute("SELECT COUNT(*) FROM reviews").fetchone()[0])
        return {"schema": "VERA_MONO_INDEPENDENT_BEHAVIOR_REVIEW_CONTEXT_V1", "receipt_count": count, "head_digest": head}
