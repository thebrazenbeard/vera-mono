from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import importlib.metadata
import json
import sqlite3
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)


class InstallationVerificationError(ValueError):
    pass


INSTALLATION_VERIFY_PREFIX = "INSTALL_VERIFY"
INSTALLATION_VERIFICATION_STATUSES = frozenset(
    {"PASS", "FAIL", "UNAVAILABLE"}
)


@dataclass(frozen=True, slots=True)
class InstallationVerificationRequirement:
    target_id: str
    distribution_name: str
    expected_version: str

    @classmethod
    def parse(
        cls,
        value: str,
    ) -> "InstallationVerificationRequirement":
        if type(value) is not str or not value:
            raise InstallationVerificationError(
                "installation verification requirement must be non-empty string"
            )
        parts = value.split("|")
        if (
            len(parts) != 4
            or parts[0] != INSTALLATION_VERIFY_PREFIX
            or any(not part for part in parts[1:])
        ):
            raise InstallationVerificationError(
                "installation verification requirement must use "
                "'INSTALL_VERIFY|<target-id>|<distribution>|<version>'"
            )
        return cls(
            target_id=parts[1],
            distribution_name=parts[2],
            expected_version=parts[3],
        )


def installation_verification_requirements(
    evidence_requirements: Sequence[str],
) -> tuple[InstallationVerificationRequirement, ...]:
    found: list[InstallationVerificationRequirement] = []
    for raw in evidence_requirements:
        if not isinstance(raw, str) or not raw.startswith(
            INSTALLATION_VERIFY_PREFIX + "|"
        ):
            continue
        found.append(InstallationVerificationRequirement.parse(raw))
    return tuple(found)


@dataclass(frozen=True, slots=True)
class InstallationObservation:
    target_id: str
    distribution_name: str
    observed_version: str | None
    location_ref: str | None
    installation_digest: str | None
    file_count: int
    import_roots: tuple[str, ...]
    available: bool

    def validate(self) -> None:
        for label, value in (
            ("target_id", self.target_id),
            ("distribution_name", self.distribution_name),
        ):
            if type(value) is not str or not value:
                raise InstallationVerificationError(
                    f"{label} must be non-empty exact string"
                )
        for label, value in (
            ("observed_version", self.observed_version),
            ("location_ref", self.location_ref),
            ("installation_digest", self.installation_digest),
        ):
            if value is not None and (
                type(value) is not str or not value
            ):
                raise InstallationVerificationError(
                    f"{label} must be None or non-empty exact string"
                )
        if self.installation_digest is not None:
            if len(self.installation_digest) != 64:
                raise InstallationVerificationError(
                    "installation_digest must be SHA-256"
                )
            try:
                int(self.installation_digest, 16)
            except ValueError as exc:
                raise InstallationVerificationError(
                    "installation_digest must be hexadecimal"
                ) from exc
        if (
            isinstance(self.file_count, bool)
            or not isinstance(self.file_count, int)
            or self.file_count < 0
        ):
            raise InstallationVerificationError(
                "file_count must be non-negative integer"
            )
        if not all(
            type(item) is str and item for item in self.import_roots
        ):
            raise InstallationVerificationError(
                "import_roots must contain non-empty exact strings"
            )
        if len(set(self.import_roots)) != len(self.import_roots):
            raise InstallationVerificationError(
                "import_roots must not contain duplicates"
            )
        if type(self.available) is not bool:
            raise InstallationVerificationError(
                "available must be boolean"
            )
        if not self.available and any(
            value is not None
            for value in (
                self.observed_version,
                self.location_ref,
                self.installation_digest,
            )
        ):
            raise InstallationVerificationError(
                "unavailable installation cannot claim observed installation fields"
            )


@runtime_checkable
class InstallationVerificationTransport(Protocol):
    target_id: str
    distribution_name: str

    def observe(
        self,
        expected_version: str,
    ) -> InstallationObservation:
        ...


@dataclass(frozen=True, slots=True)
class InstallationVerificationReceipt:
    sequence: int
    task_id: str
    packet_digest: str
    target_id: str
    distribution_name: str
    expected_version: str
    observed_version: str | None
    location_ref: str | None
    installation_digest: str | None
    file_count: int
    import_roots: tuple[str, ...]
    status: str
    predecessor_digest: str
    receipt_digest: str


class InstallationVerificationStore:
    """Append-only task-bound installation observations."""

    GENESIS_HEAD = sha256_hex(
        b"vera-mono-installation-verification-genesis-v1"
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
                CREATE TABLE IF NOT EXISTS observations (
                    sequence INTEGER PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    distribution_name TEXT NOT NULL,
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
    def _status(
        requirement: InstallationVerificationRequirement,
        observation: InstallationObservation,
    ) -> str:
        observation.validate()
        if (
            observation.target_id != requirement.target_id
            or observation.distribution_name
            != requirement.distribution_name
        ):
            raise InstallationVerificationError(
                "installation observation identity mismatch"
            )
        if not observation.available:
            return "UNAVAILABLE"
        if observation.observed_version != requirement.expected_version:
            return "FAIL"
        if (
            observation.installation_digest is None
            or observation.location_ref is None
            or observation.file_count < 1
        ):
            return "FAIL"
        return "PASS"

    def append(
        self,
        *,
        task_id: str,
        packet_digest: str,
        requirement: InstallationVerificationRequirement,
        observation: InstallationObservation,
    ) -> InstallationVerificationReceipt:
        for label, value in (
            ("task_id", task_id),
            ("packet_digest", packet_digest),
        ):
            if type(value) is not str or not value:
                raise InstallationVerificationError(
                    f"{label} must be non-empty exact string"
                )
        if len(packet_digest) != 64:
            raise InstallationVerificationError(
                "packet_digest must be SHA-256"
            )
        status = self._status(requirement, observation)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sequence, predecessor = self._meta(db)
            next_sequence = sequence + 1
            payload = {
                "schema": "VERA_MONO_INSTALLATION_VERIFICATION_V1",
                "sequence": next_sequence,
                "task_id": task_id,
                "packet_digest": packet_digest,
                "target_id": requirement.target_id,
                "distribution_name": requirement.distribution_name,
                "expected_version": requirement.expected_version,
                "observed_version": observation.observed_version,
                "location_ref": observation.location_ref,
                "installation_digest": observation.installation_digest,
                "file_count": observation.file_count,
                "import_roots": list(observation.import_roots),
                "status": status,
                "predecessor_digest": predecessor,
            }
            digest = sha256_hex(canonical_json_bytes(payload))
            db.execute(
                """
                INSERT INTO observations(
                    sequence,task_id,target_id,distribution_name,
                    receipt_digest,predecessor_digest,payload_json
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    next_sequence,
                    task_id,
                    requirement.target_id,
                    requirement.distribution_name,
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
            requirement.target_id,
            requirement.distribution_name,
        )

    def latest(
        self,
        task_id: str,
        target_id: str,
        distribution_name: str,
    ) -> InstallationVerificationReceipt:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT * FROM observations
                WHERE task_id=? AND target_id=? AND distribution_name=?
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (task_id, target_id, distribution_name),
            ).fetchone()
        if row is None:
            raise KeyError((task_id, target_id, distribution_name))
        return self._row(row)

    def receipts(
        self,
        task_id: str | None = None,
    ) -> tuple[InstallationVerificationReceipt, ...]:
        with self._connect() as db:
            if task_id is None:
                rows = db.execute(
                    "SELECT * FROM observations ORDER BY sequence"
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    SELECT * FROM observations
                    WHERE task_id=?
                    ORDER BY sequence
                    """,
                    (task_id,),
                ).fetchall()
        return tuple(self._row(row) for row in rows)

    def verify_chain(self) -> str:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM observations ORDER BY sequence"
            ).fetchall()
            sequence, head = self._meta(db)
        predecessor = self.GENESIS_HEAD
        expected_sequence = 1
        for row in rows:
            receipt = self._row(row)
            if receipt.sequence != expected_sequence:
                raise InstallationVerificationError(
                    "installation verification sequence gap"
                )
            if receipt.predecessor_digest != predecessor:
                raise InstallationVerificationError(
                    "installation verification predecessor mismatch"
                )
            payload = self._payload(receipt)
            observed = sha256_hex(canonical_json_bytes(payload))
            if observed != receipt.receipt_digest:
                raise InstallationVerificationError(
                    "installation verification receipt digest mismatch"
                )
            predecessor = observed
            expected_sequence += 1
        if sequence != expected_sequence - 1:
            raise InstallationVerificationError(
                "installation verification meta sequence mismatch"
            )
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if head != expected_head:
            raise InstallationVerificationError(
                "installation verification meta head mismatch"
            )
        return head

    def context(self) -> dict[str, Any]:
        receipts = self.receipts()
        return {
            "schema": "VERA_MONO_INSTALLATION_VERIFICATION_CONTEXT_V1",
            "sequence": len(receipts),
            "head_digest": self.verify_chain(),
            "task_ids": sorted({item.task_id for item in receipts}),
            "latest": [
                {
                    "task_id": item.task_id,
                    "target_id": item.target_id,
                    "distribution_name": item.distribution_name,
                    "expected_version": item.expected_version,
                    "observed_version": item.observed_version,
                    "installation_digest": item.installation_digest,
                    "status": item.status,
                    "receipt_digest": item.receipt_digest,
                }
                for item in receipts
            ],
        }

    @staticmethod
    def _payload(
        receipt: InstallationVerificationReceipt,
    ) -> dict[str, Any]:
        return {
            "schema": "VERA_MONO_INSTALLATION_VERIFICATION_V1",
            "sequence": receipt.sequence,
            "task_id": receipt.task_id,
            "packet_digest": receipt.packet_digest,
            "target_id": receipt.target_id,
            "distribution_name": receipt.distribution_name,
            "expected_version": receipt.expected_version,
            "observed_version": receipt.observed_version,
            "location_ref": receipt.location_ref,
            "installation_digest": receipt.installation_digest,
            "file_count": receipt.file_count,
            "import_roots": list(receipt.import_roots),
            "status": receipt.status,
            "predecessor_digest": receipt.predecessor_digest,
        }

    @classmethod
    def _row(
        cls,
        row: sqlite3.Row,
    ) -> InstallationVerificationReceipt:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError as exc:
            raise InstallationVerificationError(
                "installation verification payload is invalid JSON"
            ) from exc
        required = {
            "schema",
            "sequence",
            "task_id",
            "packet_digest",
            "target_id",
            "distribution_name",
            "expected_version",
            "observed_version",
            "location_ref",
            "installation_digest",
            "file_count",
            "import_roots",
            "status",
            "predecessor_digest",
        }
        if not isinstance(payload, dict) or set(payload) != required:
            raise InstallationVerificationError(
                "installation verification payload field set mismatch"
            )
        if payload["schema"] != "VERA_MONO_INSTALLATION_VERIFICATION_V1":
            raise InstallationVerificationError(
                "unsupported installation verification schema"
            )
        if payload["status"] not in INSTALLATION_VERIFICATION_STATUSES:
            raise InstallationVerificationError(
                "unsupported persisted installation verification status"
            )
        if (
            int(payload["sequence"]) != int(row["sequence"])
            or payload["task_id"] != row["task_id"]
            or payload["target_id"] != row["target_id"]
            or payload["distribution_name"] != row["distribution_name"]
            or payload["predecessor_digest"] != row["predecessor_digest"]
        ):
            raise InstallationVerificationError(
                "installation verification row/payload mismatch"
            )
        receipt = InstallationVerificationReceipt(
            sequence=int(payload["sequence"]),
            task_id=payload["task_id"],
            packet_digest=payload["packet_digest"],
            target_id=payload["target_id"],
            distribution_name=payload["distribution_name"],
            expected_version=payload["expected_version"],
            observed_version=payload["observed_version"],
            location_ref=payload["location_ref"],
            installation_digest=payload["installation_digest"],
            file_count=int(payload["file_count"]),
            import_roots=tuple(payload["import_roots"]),
            status=payload["status"],
            predecessor_digest=payload["predecessor_digest"],
            receipt_digest=str(row["receipt_digest"]),
        )
        expected = sha256_hex(
            canonical_json_bytes(cls._payload(receipt))
        )
        if expected != receipt.receipt_digest:
            raise InstallationVerificationError(
                "installation verification receipt digest mismatch"
            )
        return receipt


class PythonDistributionInstallationTransport:
    """Read-only verifier for one installed Python distribution target."""

    def __init__(
        self,
        *,
        target_id: str,
        distribution_name: str,
    ):
        if type(target_id) is not str or not target_id:
            raise ValueError("target_id must be non-empty exact string")
        if type(distribution_name) is not str or not distribution_name:
            raise ValueError(
                "distribution_name must be non-empty exact string"
            )
        self.target_id = target_id
        self.distribution_name = distribution_name

    def observe(
        self,
        expected_version: str,
    ) -> InstallationObservation:
        del expected_version
        try:
            distribution = importlib.metadata.distribution(
                self.distribution_name
            )
        except importlib.metadata.PackageNotFoundError:
            return InstallationObservation(
                target_id=self.target_id,
                distribution_name=self.distribution_name,
                observed_version=None,
                location_ref=None,
                installation_digest=None,
                file_count=0,
                import_roots=(),
                available=False,
            )

        files = tuple(distribution.files or ())
        hashed: list[dict[str, str]] = []
        import_roots: set[str] = set()
        for entry in files:
            relative = str(entry).replace("\\", "/")
            if not relative or relative.startswith("../"):
                continue
            located = Path(distribution.locate_file(entry))
            if not located.is_file():
                raise InstallationVerificationError(
                    "installed distribution RECORD references missing file: "
                    + relative
                )
            digest = hashlib.sha256(located.read_bytes()).hexdigest()
            hashed.append({"path": relative, "sha256": digest})
            parts = relative.split("/")
            if (
                len(parts) >= 2
                and parts[1] == "__init__.py"
                and not parts[0].endswith(".dist-info")
            ):
                import_roots.add(parts[0])

        installation_digest = sha256_hex(
            canonical_json_bytes(
                {
                    "distribution_name": self.distribution_name,
                    "observed_version": distribution.version,
                    "files": sorted(
                        hashed,
                        key=lambda item: item["path"],
                    ),
                }
            )
        )
        return InstallationObservation(
            target_id=self.target_id,
            distribution_name=self.distribution_name,
            observed_version=distribution.version,
            location_ref=str(distribution.locate_file("")),
            installation_digest=installation_digest,
            file_count=len(hashed),
            import_roots=tuple(sorted(import_roots)),
            available=True,
        )
