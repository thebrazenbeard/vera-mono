"""Persistent SemanticAtlas object store with explicit epistemic ceiling."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import sqlite3

from jsonschema import Draft202012Validator


@dataclass(frozen=True, slots=True)
class SemanticAdmissionReceipt:
    object_id: str
    object_type: str
    digest: str
    status: str
    authority_effect: str = "NONE"
    truth_effect: str = "NONE"
    identity_effect: str = "NONE"


class SemanticKnowledgeConflict(ValueError):
    pass


class SemanticKnowledgeStore:
    """Schema-valid immutable semantic objects; storage is not truth promotion."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        schema_path = (
            files("vera_identity")
            / "resources/architecture/semantic/vendor/semanticatlas"
            / "semantic_atlas_v0.1.schema.json"
        )
        self._validator = Draft202012Validator(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )
        self._memory: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._memory = sqlite3.connect(":memory:")
            self._memory.row_factory = sqlite3.Row
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS semantic_objects (
                    object_id TEXT PRIMARY KEY,
                    object_type TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    canonical_json TEXT NOT NULL
                )"""
            )

    def _connect(self):
        if self._memory is not None:
            return _BorrowedConnection(self._memory)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _canonical(value: dict[str, object]) -> str:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        )

    def admit(self, value: dict[str, object]) -> SemanticAdmissionReceipt:
        self._validator.validate(value)
        object_id = str(value["id"])
        object_type = str(value["object_type"])
        canonical = self._canonical(value)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._connect() as db:
            row = db.execute(
                "SELECT object_type,digest FROM semantic_objects WHERE object_id=?",
                (object_id,),
            ).fetchone()
            if row is not None:
                if row["digest"] != digest or row["object_type"] != object_type:
                    raise SemanticKnowledgeConflict(
                        "semantic object id cannot be rebound to different content"
                    )
                status = "DUPLICATE"
            else:
                db.execute(
                    "INSERT INTO semantic_objects VALUES (?,?,?,?)",
                    (object_id, object_type, digest, canonical),
                )
                db.commit()
                status = "ACCEPTED"
        return SemanticAdmissionReceipt(
            object_id=object_id, object_type=object_type,
            digest=digest, status=status,
        )

    def get(self, object_id: str) -> dict[str, object]:
        with self._connect() as db:
            row = db.execute(
                "SELECT canonical_json FROM semantic_objects WHERE object_id=?",
                (object_id,),
            ).fetchone()
        if row is None:
            raise KeyError(object_id)
        return json.loads(row["canonical_json"])

    def list_type(self, object_type: str) -> tuple[dict[str, object], ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT canonical_json FROM semantic_objects "
                "WHERE object_type=? ORDER BY object_id",
                (object_type,),
            ).fetchall()
        return tuple(json.loads(row["canonical_json"]) for row in rows)


class _BorrowedConnection:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        return self.db

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.db.rollback()
