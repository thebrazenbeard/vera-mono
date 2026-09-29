from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)


class SourceVerificationError(ValueError):
    pass


SOURCE_VERIFICATION_PREFIX = "SOURCE_VERIFY"
SOURCE_CHECK_STATUSES = frozenset(
    {"PASS", "FAIL", "PENDING", "UNAVAILABLE"}
)
SOURCE_VERIFICATION_STATUSES = frozenset(
    {"PASS", "FAIL", "PENDING", "UNAVAILABLE", "STALE_HEAD"}
)


@dataclass(frozen=True, slots=True)
class SourceVerificationRequirement:
    repository: str
    ref: str
    check_name: str

    @classmethod
    def parse(cls, value: str) -> "SourceVerificationRequirement":
        if type(value) is not str or not value:
            raise SourceVerificationError(
                "source verification requirement must be non-empty string"
            )
        parts = value.split("|")
        if len(parts) != 4 or parts[0] != SOURCE_VERIFICATION_PREFIX:
            raise SourceVerificationError(
                "source verification requirement must use "
                "'SOURCE_VERIFY|<repository>|<ref>|<check-name>'"
            )
        if any(not part for part in parts[1:]):
            raise SourceVerificationError(
                "source verification requirement fields must be non-empty"
            )
        return cls(
            repository=parts[1],
            ref=parts[2],
            check_name=parts[3],
        )


def source_verification_requirements(
    evidence_requirements: Sequence[str],
    *,
    repository: str,
    ref: str,
) -> tuple[SourceVerificationRequirement, ...]:
    found: list[SourceVerificationRequirement] = []
    for raw in evidence_requirements:
        if not isinstance(raw, str) or not raw.startswith(
            SOURCE_VERIFICATION_PREFIX + "|"
        ):
            continue
        requirement = SourceVerificationRequirement.parse(raw)
        if (
            requirement.repository == repository
            and requirement.ref == ref
        ):
            found.append(requirement)
    return tuple(found)


@dataclass(frozen=True, slots=True)
class SourceCheckObservation:
    check_name: str
    status: str
    external_id: str | None = None
    details_ref: str | None = None

    def validate(self) -> None:
        if type(self.check_name) is not str or not self.check_name:
            raise SourceVerificationError(
                "check_name must be a non-empty exact string"
            )
        if self.status not in SOURCE_CHECK_STATUSES:
            raise SourceVerificationError(
                f"unsupported source check status: {self.status!r}"
            )
        for label, value in (
            ("external_id", self.external_id),
            ("details_ref", self.details_ref),
        ):
            if value is not None and (
                type(value) is not str or not value
            ):
                raise SourceVerificationError(
                    f"{label} must be None or non-empty exact string"
                )

    def canonical_body(self) -> dict[str, Any]:
        self.validate()
        return {
            "check_name": self.check_name,
            "status": self.status,
            "external_id": self.external_id,
            "details_ref": self.details_ref,
        }


@dataclass(frozen=True, slots=True)
class SourceVerificationTransportResult:
    repository: str
    ref: str
    commit_sha: str
    observed_ref_head: str
    checks: tuple[SourceCheckObservation, ...]

    def validate(self) -> None:
        for label, value in (
            ("repository", self.repository),
            ("ref", self.ref),
            ("commit_sha", self.commit_sha),
            ("observed_ref_head", self.observed_ref_head),
        ):
            if type(value) is not str or not value:
                raise SourceVerificationError(
                    f"{label} must be a non-empty exact string"
                )
        names: set[str] = set()
        for check in self.checks:
            if type(check) is not SourceCheckObservation:
                raise SourceVerificationError(
                    "checks must contain exact SourceCheckObservation values"
                )
            check.validate()
            if check.check_name in names:
                raise SourceVerificationError(
                    "verification transport returned duplicate check name"
                )
            names.add(check.check_name)


@runtime_checkable
class SourceVerificationTransport(Protocol):
    repository: str
    ref: str

    def observe_ref_head(self) -> str:
        ...

    def verify(
        self,
        commit_sha: str,
        required_checks: tuple[str, ...],
    ) -> SourceVerificationTransportResult:
        ...


@dataclass(frozen=True, slots=True)
class SourceVerificationReceipt:
    sequence: int
    mutation_id: str
    repository: str
    ref: str
    commit_sha: str
    observed_ref_head: str
    required_checks: tuple[str, ...]
    checks: tuple[SourceCheckObservation, ...]
    status: str
    predecessor_digest: str
    receipt_digest: str


class SourceVerificationStore:
    """Append-only exact-commit source verification observations."""

    GENESIS_HEAD = sha256_hex(b"vera-mono-source-verification-genesis-v1")

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
                CREATE TABLE IF NOT EXISTS observations (
                    sequence INTEGER PRIMARY KEY,
                    mutation_id TEXT NOT NULL,
                    receipt_digest TEXT NOT NULL UNIQUE,
                    predecessor_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL
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
    def _aggregate(
        *,
        commit_sha: str,
        observed_ref_head: str,
        required_checks: tuple[str, ...],
        checks: tuple[SourceCheckObservation, ...],
    ) -> str:
        if observed_ref_head != commit_sha:
            return "STALE_HEAD"
        by_name = {item.check_name: item for item in checks}
        if set(by_name) != set(required_checks):
            raise SourceVerificationError(
                "verification result check set does not equal required checks"
            )
        statuses = {item.status for item in checks}
        if "FAIL" in statuses:
            return "FAIL"
        if "UNAVAILABLE" in statuses:
            return "UNAVAILABLE"
        if "PENDING" in statuses:
            return "PENDING"
        if statuses <= {"PASS"}:
            return "PASS"
        raise SourceVerificationError(
            "cannot aggregate source verification status"
        )

    def append(
        self,
        *,
        mutation_id: str,
        result: SourceVerificationTransportResult,
        required_checks: tuple[str, ...],
    ) -> SourceVerificationReceipt:
        if type(mutation_id) is not str or not mutation_id:
            raise SourceVerificationError(
                "mutation_id must be non-empty exact string"
            )
        if type(result) is not SourceVerificationTransportResult:
            raise SourceVerificationError(
                "result must be exact SourceVerificationTransportResult"
            )
        result.validate()
        if (
            not required_checks
            or not all(
                type(item) is str and item
                for item in required_checks
            )
            or len(set(required_checks)) != len(required_checks)
        ):
            raise SourceVerificationError(
                "required_checks must be unique non-empty exact strings"
            )
        status = self._aggregate(
            commit_sha=result.commit_sha,
            observed_ref_head=result.observed_ref_head,
            required_checks=required_checks,
            checks=result.checks,
        )
        payload = {
            "schema": "VERA_MONO_SOURCE_VERIFICATION_RECEIPT_V1",
            "mutation_id": mutation_id,
            "repository": result.repository,
            "ref": result.ref,
            "commit_sha": result.commit_sha,
            "observed_ref_head": result.observed_ref_head,
            "required_checks": list(required_checks),
            "checks": [
                item.canonical_body() for item in result.checks
            ],
            "status": status,
        }
        payload_json = canonical_json(payload)

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            body = {
                "schema": "VERA_MONO_SOURCE_VERIFICATION_EVENT_V1",
                "sequence": next_sequence,
                "predecessor_digest": predecessor,
                "payload": payload,
            }
            digest = sha256_hex(canonical_json_bytes(body))
            db.execute(
                """
                INSERT INTO observations(
                    sequence,mutation_id,receipt_digest,
                    predecessor_digest,payload_json
                ) VALUES(?,?,?,?,?)
                """,
                (
                    next_sequence,
                    mutation_id,
                    digest,
                    predecessor,
                    payload_json,
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
        return SourceVerificationReceipt(
            sequence=next_sequence,
            mutation_id=mutation_id,
            repository=result.repository,
            ref=result.ref,
            commit_sha=result.commit_sha,
            observed_ref_head=result.observed_ref_head,
            required_checks=required_checks,
            checks=result.checks,
            status=status,
            predecessor_digest=predecessor,
            receipt_digest=digest,
        )

    def latest(
        self,
        mutation_id: str,
    ) -> SourceVerificationReceipt | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM observations
                WHERE mutation_id=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (mutation_id,),
            ).fetchone()
        return None if row is None else self._row(row)

    def receipts(
        self,
        mutation_id: str | None = None,
    ) -> tuple[SourceVerificationReceipt, ...]:
        with self._connect() as db:
            if mutation_id is None:
                rows = db.execute(
                    "SELECT * FROM observations ORDER BY sequence"
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM observations
                    WHERE mutation_id=?
                    ORDER BY sequence
                    """,
                    (mutation_id,),
                ).fetchall()
        return tuple(self._row(row) for row in rows)

    def verify_chain(self) -> str:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM observations ORDER BY sequence"
            ).fetchall()
            meta_sequence, meta_head = self._meta(db)
        predecessor = self.GENESIS_HEAD
        expected_sequence = 1
        for row in rows:
            receipt = self._row(row)
            if receipt.sequence != expected_sequence:
                raise SourceVerificationError(
                    "source verification sequence gap"
                )
            if receipt.predecessor_digest != predecessor:
                raise SourceVerificationError(
                    "source verification predecessor mismatch"
                )
            payload = self._receipt_payload(receipt)
            body = {
                "schema": "VERA_MONO_SOURCE_VERIFICATION_EVENT_V1",
                "sequence": receipt.sequence,
                "predecessor_digest": receipt.predecessor_digest,
                "payload": payload,
            }
            observed = sha256_hex(canonical_json_bytes(body))
            if observed != receipt.receipt_digest:
                raise SourceVerificationError(
                    "source verification receipt digest mismatch"
                )
            predecessor = observed
            expected_sequence += 1
        if meta_sequence != expected_sequence - 1:
            raise SourceVerificationError(
                "source verification meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if meta_head != expected_head:
            raise SourceVerificationError(
                "source verification meta head mismatch"
            )
        return expected_head

    def context(self) -> dict[str, Any]:
        self.verify_chain()
        latest: dict[str, SourceVerificationReceipt] = {}
        for receipt in self.receipts():
            latest[receipt.mutation_id] = receipt
        return {
            "schema": "VERA_MONO_SOURCE_VERIFICATION_CONTEXT_V1",
            "head_digest": self.verify_chain(),
            "mutation_count": len(latest),
            "latest": [
                {
                    "mutation_id": receipt.mutation_id,
                    "repository": receipt.repository,
                    "ref": receipt.ref,
                    "commit_sha": receipt.commit_sha,
                    "observed_ref_head": receipt.observed_ref_head,
                    "required_checks": list(
                        receipt.required_checks
                    ),
                    "status": receipt.status,
                    "receipt_digest": receipt.receipt_digest,
                }
                for receipt in sorted(
                    latest.values(),
                    key=lambda item: item.mutation_id,
                )
            ],
        }

    @staticmethod
    def _receipt_payload(
        receipt: SourceVerificationReceipt,
    ) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_SOURCE_VERIFICATION_RECEIPT_V1",
            "mutation_id": receipt.mutation_id,
            "repository": receipt.repository,
            "ref": receipt.ref,
            "commit_sha": receipt.commit_sha,
            "observed_ref_head": receipt.observed_ref_head,
            "required_checks": list(receipt.required_checks),
            "checks": [
                item.canonical_body()
                for item in receipt.checks
            ],
            "status": receipt.status,
        }

    @classmethod
    def _row(
        cls,
        row: sqlite3.Row,
    ) -> SourceVerificationReceipt:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise SourceVerificationError(
                "source verification payload is invalid JSON"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema")
            != "VERA_MONO_SOURCE_VERIFICATION_RECEIPT_V1"
        ):
            raise SourceVerificationError(
                "unsupported source verification receipt schema"
            )
        required_checks = tuple(payload["required_checks"])
        checks = tuple(
            SourceCheckObservation(
                check_name=str(item["check_name"]),
                status=str(item["status"]),
                external_id=item.get("external_id"),
                details_ref=item.get("details_ref"),
            )
            for item in payload["checks"]
        )
        expected_status = cls._aggregate(
            commit_sha=str(payload["commit_sha"]),
            observed_ref_head=str(payload["observed_ref_head"]),
            required_checks=required_checks,
            checks=checks,
        )
        if expected_status != payload["status"]:
            raise SourceVerificationError(
                "persisted source verification aggregate status mismatch"
            )
        receipt = SourceVerificationReceipt(
            sequence=int(row["sequence"]),
            mutation_id=str(payload["mutation_id"]),
            repository=str(payload["repository"]),
            ref=str(payload["ref"]),
            commit_sha=str(payload["commit_sha"]),
            observed_ref_head=str(payload["observed_ref_head"]),
            required_checks=required_checks,
            checks=checks,
            status=str(payload["status"]),
            predecessor_digest=str(row["predecessor_digest"]),
            receipt_digest=str(row["receipt_digest"]),
        )
        if canonical_json(cls._receipt_payload(receipt)) != row["payload_json"]:
            raise SourceVerificationError(
                "source verification canonical readback mismatch"
            )
        return receipt
