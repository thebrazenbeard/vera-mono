from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex


class CoordinationCommandJournalError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CoordinationCommandBinding:
    command_id: str
    effect_id: str
    command: str
    actor_workstream: str
    lifecycle_permit_digest: str
    invocation_digest: str
    request_digest: str
    binding_digest: str


@dataclass(frozen=True, slots=True)
class CoordinationCommandRecoveryAssessment:
    command_id: str
    effect_id: str
    command: str
    actor_workstream: str
    request_digest: str
    result_recorded: bool
    fence_state: str | None
    lifecycle_permit_current: bool | None
    retry_candidate_allowed: bool
    pre_dispatch_cancel_allowed: bool
    recovery_required: bool
    terminal: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CoordinationCommandResult:
    command_id: str
    result_digest: str
    result_class: str
    database_write_confirmed: bool
    event_id: str | None
    event_sequence: int | None
    result_record_digest: str


class CoordinationCommandJournal:
    """Durable non-payload command/result evidence for local coordination.

    Invocation payloads are intentionally not stored here. The journal binds a
    command id to request/lifecycle digests and, after the coordination method
    returns, records the exact effect-result digest plus minimal receipt
    metadata. A recorded result can therefore close a crash window without
    re-running the coordination command.
    """

    SCHEMA = "VERA_MONO_COORDINATION_COMMAND_JOURNAL_V1"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS command_bindings (
                    command_id TEXT PRIMARY KEY,
                    effect_id TEXT NOT NULL UNIQUE,
                    command TEXT NOT NULL,
                    actor_workstream TEXT NOT NULL,
                    lifecycle_permit_digest TEXT NOT NULL,
                    invocation_digest TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    binding_digest TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS command_results (
                    command_id TEXT PRIMARY KEY,
                    result_digest TEXT NOT NULL,
                    result_class TEXT NOT NULL,
                    database_write_confirmed INTEGER NOT NULL,
                    event_id TEXT,
                    event_sequence INTEGER,
                    result_record_digest TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(command_id)
                        REFERENCES command_bindings(command_id)
                        ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS command_meta (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    binding_count INTEGER NOT NULL,
                    result_count INTEGER NOT NULL,
                    projection_digest TEXT NOT NULL
                );
                """
            )
            meta = db.execute(
                "SELECT 1 FROM command_meta WHERE singleton=1"
            ).fetchone()
            if meta is None:
                binding_count, result_count, digest = (
                    self._projection_state(db)
                )
                db.execute(
                    """
                    INSERT INTO command_meta(
                        singleton,binding_count,result_count,projection_digest
                    ) VALUES(1,?,?,?)
                    """,
                    (binding_count, result_count, digest),
                )

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        if type(value) is not str or not value:
            raise CoordinationCommandJournalError(
                f"{label} must be a non-empty exact string"
            )
        return value

    @staticmethod
    def _require_digest(value: str, label: str) -> str:
        if type(value) is not str or len(value) != 64:
            raise CoordinationCommandJournalError(
                f"{label} must be an exact SHA-256 digest"
            )
        try:
            int(value, 16)
        except ValueError as exc:
            raise CoordinationCommandJournalError(
                f"{label} must be hexadecimal"
            ) from exc
        return value.lower()

    @classmethod
    def _projection_state(
        cls,
        db: sqlite3.Connection,
    ) -> tuple[int, int, str]:
        binding_rows = db.execute(
            "SELECT * FROM command_bindings ORDER BY command_id"
        ).fetchall()
        result_rows = db.execute(
            "SELECT * FROM command_results ORDER BY command_id"
        ).fetchall()

        bindings: dict[str, CoordinationCommandBinding] = {}
        binding_material: list[dict[str, Any]] = []
        for row in binding_rows:
            binding = cls._binding_from_row(row)
            expected = cls._binding_digest(
                command_id=binding.command_id,
                effect_id=binding.effect_id,
                command=binding.command,
                actor_workstream=binding.actor_workstream,
                lifecycle_permit_digest=binding.lifecycle_permit_digest,
                invocation_digest=binding.invocation_digest,
                request_digest=binding.request_digest,
            )
            if expected != binding.binding_digest:
                raise CoordinationCommandJournalError(
                    "coordination command binding digest mismatch"
                )
            bindings[binding.command_id] = binding
            binding_material.append(
                {
                    "command_id": binding.command_id,
                    "effect_id": binding.effect_id,
                    "command": binding.command,
                    "actor_workstream": binding.actor_workstream,
                    "lifecycle_permit_digest": (
                        binding.lifecycle_permit_digest
                    ),
                    "invocation_digest": binding.invocation_digest,
                    "request_digest": binding.request_digest,
                    "binding_digest": binding.binding_digest,
                }
            )

        result_material: list[dict[str, Any]] = []
        for row in result_rows:
            result = cls._result_from_row(row)
            binding = bindings.get(result.command_id)
            if binding is None:
                raise CoordinationCommandJournalError(
                    "coordination result has no command binding"
                )
            expected = cls._result_record_digest(
                binding,
                result_digest=result.result_digest,
                result_class=result.result_class,
                database_write_confirmed=result.database_write_confirmed,
                event_id=result.event_id,
                event_sequence=result.event_sequence,
            )
            if expected != result.result_record_digest:
                raise CoordinationCommandJournalError(
                    "coordination command result digest mismatch"
                )
            result_material.append(
                {
                    "command_id": result.command_id,
                    "result_digest": result.result_digest,
                    "result_class": result.result_class,
                    "database_write_confirmed": (
                        result.database_write_confirmed
                    ),
                    "event_id": result.event_id,
                    "event_sequence": result.event_sequence,
                    "result_record_digest": result.result_record_digest,
                }
            )

        digest = sha256_hex(
            canonical_json_bytes(
                {
                    "schema": "VERA_MONO_COORDINATION_COMMAND_PROJECTION_V1",
                    "bindings": binding_material,
                    "results": result_material,
                }
            )
        )
        return len(binding_rows), len(result_rows), digest

    @classmethod
    def _write_meta(cls, db: sqlite3.Connection) -> None:
        binding_count, result_count, digest = cls._projection_state(db)
        db.execute(
            """
            UPDATE command_meta
            SET binding_count=?,result_count=?,projection_digest=?
            WHERE singleton=1
            """,
            (binding_count, result_count, digest),
        )

    def verify_integrity(self) -> str:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            observed = db.execute(
                """
                SELECT binding_count,result_count,projection_digest
                FROM command_meta WHERE singleton=1
                """
            ).fetchone()
            if observed is None:
                raise CoordinationCommandJournalError(
                    "coordination command integrity metadata is missing"
                )
            binding_count, result_count, digest = self._projection_state(db)
        if int(observed["binding_count"]) != binding_count:
            raise CoordinationCommandJournalError(
                "coordination command binding count mismatch"
            )
        if int(observed["result_count"]) != result_count:
            raise CoordinationCommandJournalError(
                "coordination command result count mismatch"
            )
        if str(observed["projection_digest"]) != digest:
            raise CoordinationCommandJournalError(
                "coordination command projection digest mismatch"
            )
        return digest

    @classmethod
    def _binding_digest(
        cls,
        *,
        command_id: str,
        effect_id: str,
        command: str,
        actor_workstream: str,
        lifecycle_permit_digest: str,
        invocation_digest: str,
        request_digest: str,
    ) -> str:
        return sha256_hex(
            canonical_json_bytes(
                {
                    "schema": cls.SCHEMA,
                    "record": "BINDING",
                    "command_id": command_id,
                    "effect_id": effect_id,
                    "command": command,
                    "actor_workstream": actor_workstream,
                    "lifecycle_permit_digest": lifecycle_permit_digest,
                    "invocation_digest": invocation_digest,
                    "request_digest": request_digest,
                }
            )
        )

    def bind(
        self,
        *,
        command_id: str,
        effect_id: str,
        command: str,
        actor_workstream: str,
        lifecycle_permit_digest: str,
        invocation_digest: str,
        request_digest: str,
    ) -> CoordinationCommandBinding:
        self.verify_integrity()
        command_id = self._require_text(command_id, "command_id")
        effect_id = self._require_text(effect_id, "effect_id")
        command = self._require_text(command, "command")
        actor_workstream = self._require_text(
            actor_workstream,
            "actor_workstream",
        )
        lifecycle_permit_digest = self._require_digest(
            lifecycle_permit_digest,
            "lifecycle_permit_digest",
        )
        invocation_digest = self._require_digest(
            invocation_digest,
            "invocation_digest",
        )
        request_digest = self._require_digest(
            request_digest,
            "request_digest",
        )
        digest = self._binding_digest(
            command_id=command_id,
            effect_id=effect_id,
            command=command,
            actor_workstream=actor_workstream,
            lifecycle_permit_digest=lifecycle_permit_digest,
            invocation_digest=invocation_digest,
            request_digest=request_digest,
        )
        candidate = CoordinationCommandBinding(
            command_id=command_id,
            effect_id=effect_id,
            command=command,
            actor_workstream=actor_workstream,
            lifecycle_permit_digest=lifecycle_permit_digest,
            invocation_digest=invocation_digest,
            request_digest=request_digest,
            binding_digest=digest,
        )
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM command_bindings WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if row is not None:
                observed = self._binding_from_row(row)
                if observed != candidate:
                    raise CoordinationCommandJournalError(
                        "coordination command id already binds different invocation"
                    )
                db.commit()
                return observed
            try:
                db.execute(
                    """
                    INSERT INTO command_bindings(
                        command_id,effect_id,command,actor_workstream,
                        lifecycle_permit_digest,invocation_digest,
                        request_digest,binding_digest
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        command_id,
                        effect_id,
                        command,
                        actor_workstream,
                        lifecycle_permit_digest,
                        invocation_digest,
                        request_digest,
                        digest,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CoordinationCommandJournalError(
                    "coordination command binding uniqueness conflict"
                ) from exc
            self._write_meta(db)
            db.commit()
        return candidate

    @classmethod
    def _result_record_digest(
        cls,
        binding: CoordinationCommandBinding,
        *,
        result_digest: str,
        result_class: str,
        database_write_confirmed: bool,
        event_id: str | None,
        event_sequence: int | None,
    ) -> str:
        return sha256_hex(
            canonical_json_bytes(
                {
                    "schema": cls.SCHEMA,
                    "record": "RESULT",
                    "binding_digest": binding.binding_digest,
                    "result_digest": result_digest,
                    "result_class": result_class,
                    "database_write_confirmed": database_write_confirmed,
                    "event_id": event_id,
                    "event_sequence": event_sequence,
                }
            )
        )

    def record_result(
        self,
        command_id: str,
        *,
        result_digest: str,
        result_class: str,
        database_write_confirmed: bool,
        event_id: str | None,
        event_sequence: int | None,
    ) -> CoordinationCommandResult:
        self.verify_integrity()
        binding = self.read_binding(command_id)
        result_digest = self._require_digest(
            result_digest,
            "result_digest",
        )
        result_class = self._require_text(result_class, "result_class")
        if type(database_write_confirmed) is not bool:
            raise CoordinationCommandJournalError(
                "database_write_confirmed must be exact bool"
            )
        if event_id is not None:
            self._require_text(event_id, "event_id")
        if event_sequence is not None and (
            isinstance(event_sequence, bool)
            or not isinstance(event_sequence, int)
            or event_sequence <= 0
        ):
            raise CoordinationCommandJournalError(
                "event_sequence must be a positive integer or None"
            )
        digest = self._result_record_digest(
            binding,
            result_digest=result_digest,
            result_class=result_class,
            database_write_confirmed=database_write_confirmed,
            event_id=event_id,
            event_sequence=event_sequence,
        )
        candidate = CoordinationCommandResult(
            command_id=command_id,
            result_digest=result_digest,
            result_class=result_class,
            database_write_confirmed=database_write_confirmed,
            event_id=event_id,
            event_sequence=event_sequence,
            result_record_digest=digest,
        )
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM command_results WHERE command_id=?",
                (command_id,),
            ).fetchone()
            if row is not None:
                observed = self._result_from_row(row)
                if observed != candidate:
                    raise CoordinationCommandJournalError(
                        "coordination command result replay diverged"
                    )
                db.commit()
                return observed
            db.execute(
                """
                INSERT INTO command_results(
                    command_id,result_digest,result_class,
                    database_write_confirmed,event_id,event_sequence,
                    result_record_digest
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    command_id,
                    result_digest,
                    result_class,
                    int(database_write_confirmed),
                    event_id,
                    event_sequence,
                    digest,
                ),
            )
            self._write_meta(db)
            db.commit()
        return candidate

    def read_binding(
        self,
        command_id: str,
    ) -> CoordinationCommandBinding:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM command_bindings WHERE command_id=?",
                (command_id,),
            ).fetchone()
        if row is None:
            raise KeyError(command_id)
        binding = self._binding_from_row(row)
        expected = self._binding_digest(
            command_id=binding.command_id,
            effect_id=binding.effect_id,
            command=binding.command,
            actor_workstream=binding.actor_workstream,
            lifecycle_permit_digest=binding.lifecycle_permit_digest,
            invocation_digest=binding.invocation_digest,
            request_digest=binding.request_digest,
        )
        if expected != binding.binding_digest:
            raise CoordinationCommandJournalError(
                "coordination command binding digest mismatch"
            )
        return binding

    def read_result(
        self,
        command_id: str,
    ) -> CoordinationCommandResult | None:
        binding = self.read_binding(command_id)
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "SELECT * FROM command_results WHERE command_id=?",
                (command_id,),
            ).fetchone()
        if row is None:
            return None
        result = self._result_from_row(row)
        expected = self._result_record_digest(
            binding,
            result_digest=result.result_digest,
            result_class=result.result_class,
            database_write_confirmed=result.database_write_confirmed,
            event_id=result.event_id,
            event_sequence=result.event_sequence,
        )
        if expected != result.result_record_digest:
            raise CoordinationCommandJournalError(
                "coordination command result digest mismatch"
            )
        return result

    def bindings(self) -> tuple[CoordinationCommandBinding, ...]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute(
                "SELECT command_id FROM command_bindings ORDER BY command_id"
            ).fetchall()
        return tuple(self.read_binding(str(row[0])) for row in rows)

    def context(self) -> dict[str, Any]:
        projection_digest = self.verify_integrity()
        bindings = self.bindings()
        results = {
            binding.command_id: self.read_result(binding.command_id)
            for binding in bindings
        }
        return {
            "schema": "VERA_MONO_COORDINATION_COMMAND_JOURNAL_CONTEXT_V1",
            "projection_digest": projection_digest,
            "binding_count": len(bindings),
            "result_count": sum(
                result is not None for result in results.values()
            ),
            "commands": [
                {
                    "command_id": binding.command_id,
                    "effect_id": binding.effect_id,
                    "command": binding.command,
                    "actor_workstream": binding.actor_workstream,
                    "lifecycle_permit_digest": (
                        binding.lifecycle_permit_digest
                    ),
                    "invocation_digest": binding.invocation_digest,
                    "request_digest": binding.request_digest,
                    "result_recorded": (
                        results[binding.command_id] is not None
                    ),
                }
                for binding in bindings
            ],
        }

    @staticmethod
    def _binding_from_row(
        row: sqlite3.Row,
    ) -> CoordinationCommandBinding:
        return CoordinationCommandBinding(
            command_id=str(row["command_id"]),
            effect_id=str(row["effect_id"]),
            command=str(row["command"]),
            actor_workstream=str(row["actor_workstream"]),
            lifecycle_permit_digest=str(row["lifecycle_permit_digest"]),
            invocation_digest=str(row["invocation_digest"]),
            request_digest=str(row["request_digest"]),
            binding_digest=str(row["binding_digest"]),
        )

    @staticmethod
    def _result_from_row(
        row: sqlite3.Row,
    ) -> CoordinationCommandResult:
        return CoordinationCommandResult(
            command_id=str(row["command_id"]),
            result_digest=str(row["result_digest"]),
            result_class=str(row["result_class"]),
            database_write_confirmed=bool(row["database_write_confirmed"]),
            event_id=None if row["event_id"] is None else str(row["event_id"]),
            event_sequence=(
                None
                if row["event_sequence"] is None
                else int(row["event_sequence"])
            ),
            result_record_digest=str(row["result_record_digest"]),
        )
