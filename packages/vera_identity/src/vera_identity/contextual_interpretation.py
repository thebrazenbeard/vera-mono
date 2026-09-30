"""Durable contextual interpretations with explicit epistemic ceilings."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


class ContextualInterpretationError(ValueError):
    """Invalid contextual interpretation state or input."""


class ContextualInterpretationConflict(ContextualInterpretationError):
    """Stable record identity was rebound to different content."""


def _require_exact_nonempty(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContextualInterpretationError(f"{field} must be a non-empty exact string")
    return value


def _validate_context_atoms(value: object, field: str) -> frozenset[str]:
    if type(value) is not frozenset:
        raise ContextualInterpretationError(f"{field} must be a frozenset of exact strings")
    for atom in value:
        _require_exact_nonempty(atom, field)
    return value


@dataclass(frozen=True, slots=True)
class ContextualInterpretation:
    interpretation_id: str
    object_id: str
    meaning: str
    source_ref: str
    required_context: frozenset[str]
    excluded_context: frozenset[str]
    supersedes_id: str | None = None

    def __post_init__(self) -> None:
        _require_exact_nonempty(self.interpretation_id, "interpretation_id")
        _require_exact_nonempty(self.object_id, "object_id")
        _require_exact_nonempty(self.meaning, "meaning")
        _require_exact_nonempty(self.source_ref, "source_ref")
        required = _validate_context_atoms(self.required_context, "required_context")
        excluded = _validate_context_atoms(self.excluded_context, "excluded_context")
        if required & excluded:
            raise ContextualInterpretationError(
                "required_context and excluded_context must be disjoint"
            )
        if self.supersedes_id is not None:
            _require_exact_nonempty(self.supersedes_id, "supersedes_id")

    @property
    def specificity(self) -> int:
        return len(self.required_context) + len(self.excluded_context)

    def manifest(self) -> dict[str, object]:
        return {
            "interpretation_id": self.interpretation_id,
            "object_id": self.object_id,
            "meaning": self.meaning,
            "source_ref": self.source_ref,
            "required_context": sorted(self.required_context),
            "excluded_context": sorted(self.excluded_context),
            "supersedes_id": self.supersedes_id,
        }


@dataclass(frozen=True, slots=True)
class ContextualAdmissionReceipt:
    record_id: str
    record_type: str
    digest: str
    status: str
    authority_effect: str = "NONE"
    truth_effect: str = "NONE"
    identity_effect: str = "NONE"


class ContextualInterpretationStore:
    """Append-only contextual interpretation registry."""

    _SCHEMA_VERSION = "1"

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._memory: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._memory = sqlite3.connect(":memory:")
            self._memory.row_factory = sqlite3.Row
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS contextual_interpretations (
                    interpretation_id TEXT PRIMARY KEY,
                    object_id TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    canonical_json TEXT NOT NULL
                )"""
            )
            db.execute(
                """CREATE TABLE IF NOT EXISTS contextual_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )"""
            )
            db.execute(
                "INSERT OR IGNORE INTO contextual_metadata(key,value) VALUES (?,?)",
                ("schema_version", self._SCHEMA_VERSION),
            )
            db.commit()

    def _connect(self):
        if self._memory is not None:
            return _BorrowedConnection(self._memory)
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _canonical(value: dict[str, object]) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def _digest(cls, value: dict[str, object]) -> tuple[str, str]:
        canonical = cls._canonical(value)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return canonical, digest

    @staticmethod
    def _decode_interpretation(canonical_json: str) -> ContextualInterpretation:
        try:
            value: Any = json.loads(canonical_json)
            if type(value) is not dict:
                raise TypeError("canonical interpretation must decode to an object")
            return ContextualInterpretation(
                interpretation_id=value["interpretation_id"],
                object_id=value["object_id"],
                meaning=value["meaning"],
                source_ref=value["source_ref"],
                required_context=frozenset(value["required_context"]),
                excluded_context=frozenset(value["excluded_context"]),
                supersedes_id=value.get("supersedes_id"),
            )
        except ContextualInterpretationError:
            raise
        except Exception as exc:
            raise ContextualInterpretationError(
                "CORRUPT_CONTEXTUAL_INTERPRETATION_STATE:interpretation"
            ) from exc

    def admit_interpretation(
        self,
        value: ContextualInterpretation,
    ) -> ContextualAdmissionReceipt:
        if not isinstance(value, ContextualInterpretation):
            raise ContextualInterpretationError(
                "value must be a ContextualInterpretation"
            )
        canonical, digest = self._digest(value.manifest())
        with self._connect() as db:
            row = db.execute(
                "SELECT digest FROM contextual_interpretations "
                "WHERE interpretation_id=?",
                (value.interpretation_id,),
            ).fetchone()
            if row is not None:
                if row["digest"] != digest:
                    raise ContextualInterpretationConflict(
                        "interpretation_id cannot be rebound to different content"
                    )
                status = "DUPLICATE"
            else:
                db.execute(
                    "INSERT INTO contextual_interpretations "
                    "(interpretation_id,object_id,digest,canonical_json) "
                    "VALUES (?,?,?,?)",
                    (
                        value.interpretation_id,
                        value.object_id,
                        digest,
                        canonical,
                    ),
                )
                db.commit()
                status = "ACCEPTED"
        return ContextualAdmissionReceipt(
            record_id=value.interpretation_id,
            record_type="INTERPRETATION",
            digest=digest,
            status=status,
        )

    def get_interpretation(self, interpretation_id: str) -> ContextualInterpretation:
        _require_exact_nonempty(interpretation_id, "interpretation_id")
        with self._connect() as db:
            row = db.execute(
                "SELECT canonical_json FROM contextual_interpretations "
                "WHERE interpretation_id=?",
                (interpretation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(interpretation_id)
        return self._decode_interpretation(row["canonical_json"])

    def list_interpretations(
        self,
        object_id: str,
        *,
        include_superseded: bool = True,
    ) -> tuple[ContextualInterpretation, ...]:
        _require_exact_nonempty(object_id, "object_id")
        if type(include_superseded) is not bool:
            raise ContextualInterpretationError(
                "include_superseded must be an exact bool"
            )
        with self._connect() as db:
            rows = db.execute(
                "SELECT canonical_json FROM contextual_interpretations "
                "WHERE object_id=? ORDER BY interpretation_id",
                (object_id,),
            ).fetchall()
        return tuple(
            self._decode_interpretation(row["canonical_json"]) for row in rows
        )


class _BorrowedConnection:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        return self.db

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.db.rollback()
