"""Durable contextual interpretations with explicit epistemic ceilings."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


_CORRUPT_PREFIX = "CORRUPT_CONTEXTUAL_INTERPRETATION_STATE"


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


def _normalize_query_context(value: object) -> frozenset[str]:
    if type(value) not in (set, frozenset):
        raise ContextualInterpretationError(
            "context must be a set or frozenset of exact strings"
        )
    normalized = frozenset(value)
    for atom in normalized:
        _require_exact_nonempty(atom, "context")
    return normalized


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


class InterpretationRelationKind(StrEnum):
    CONTRASTS_WITH = "CONTRASTS_WITH"
    CONTRADICTS = "CONTRADICTS"
    SUPPORTS = "SUPPORTS"
    REFINES = "REFINES"


@dataclass(frozen=True, slots=True)
class InterpretationRelation:
    relation_id: str
    left_id: str
    right_id: str
    kind: InterpretationRelationKind
    source_ref: str

    def __post_init__(self) -> None:
        _require_exact_nonempty(self.relation_id, "relation_id")
        _require_exact_nonempty(self.left_id, "left_id")
        _require_exact_nonempty(self.right_id, "right_id")
        _require_exact_nonempty(self.source_ref, "source_ref")
        if self.left_id == self.right_id:
            raise ContextualInterpretationError(
                "relation endpoints must be distinct"
            )
        if not isinstance(self.kind, InterpretationRelationKind):
            raise ContextualInterpretationError(
                "kind must be an InterpretationRelationKind"
            )

    def manifest(self) -> dict[str, object]:
        return {
            "relation_id": self.relation_id,
            "left_id": self.left_id,
            "right_id": self.right_id,
            "kind": self.kind.value,
            "source_ref": self.source_ref,
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


@dataclass(frozen=True, slots=True)
class ContextualInterpretationResult:
    interpretation: ContextualInterpretation
    relations: tuple[InterpretationRelation, ...]
    is_current: bool
    authority_effect: str = "NONE"
    truth_effect: str = "NONE"
    identity_effect: str = "NONE"

    @property
    def specificity(self) -> int:
        return self.interpretation.specificity


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
                """CREATE TABLE IF NOT EXISTS contextual_relations (
                    relation_id TEXT PRIMARY KEY,
                    left_id TEXT NOT NULL,
                    right_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
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

    @classmethod
    def _decode_interpretation_row(
        cls,
        row: sqlite3.Row,
    ) -> ContextualInterpretation:
        try:
            value: Any = json.loads(row["canonical_json"])
            if type(value) is not dict:
                raise TypeError("canonical interpretation must decode to an object")
            canonical = cls._canonical(value)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if digest != row["digest"]:
                raise ValueError("interpretation digest mismatch")
            interpretation = ContextualInterpretation(
                interpretation_id=value["interpretation_id"],
                object_id=value["object_id"],
                meaning=value["meaning"],
                source_ref=value["source_ref"],
                required_context=frozenset(value["required_context"]),
                excluded_context=frozenset(value["excluded_context"]),
                supersedes_id=value.get("supersedes_id"),
            )
            if "object_id" in row.keys() and interpretation.object_id != row["object_id"]:
                raise ValueError("interpretation object_id mismatch")
            if (
                "interpretation_id" in row.keys()
                and interpretation.interpretation_id != row["interpretation_id"]
            ):
                raise ValueError("interpretation id mismatch")
            return interpretation
        except Exception as exc:
            raise ContextualInterpretationError(
                f"{_CORRUPT_PREFIX}:interpretation"
            ) from exc

    @classmethod
    def _decode_relation_row(cls, row: sqlite3.Row) -> InterpretationRelation:
        try:
            value: Any = json.loads(row["canonical_json"])
            if type(value) is not dict:
                raise TypeError("canonical relation must decode to an object")
            canonical = cls._canonical(value)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if digest != row["digest"]:
                raise ValueError("relation digest mismatch")
            relation = InterpretationRelation(
                relation_id=value["relation_id"],
                left_id=value["left_id"],
                right_id=value["right_id"],
                kind=InterpretationRelationKind(value["kind"]),
                source_ref=value["source_ref"],
            )
            for column, actual in (
                ("relation_id", relation.relation_id),
                ("left_id", relation.left_id),
                ("right_id", relation.right_id),
                ("kind", relation.kind.value),
            ):
                if column in row.keys() and row[column] != actual:
                    raise ValueError(f"relation {column} mismatch")
            return relation
        except Exception as exc:
            raise ContextualInterpretationError(
                f"{_CORRUPT_PREFIX}:relation"
            ) from exc

    @staticmethod
    def _interpretation_select() -> str:
        return (
            "SELECT interpretation_id,object_id,digest,canonical_json "
            "FROM contextual_interpretations"
        )

    @staticmethod
    def _relation_select() -> str:
        return (
            "SELECT relation_id,left_id,right_id,kind,digest,canonical_json "
            "FROM contextual_relations"
        )

    def _validate_supersession(
        self,
        db: sqlite3.Connection,
        value: ContextualInterpretation,
    ) -> None:
        target_id = value.supersedes_id
        if target_id is None:
            return
        if target_id == value.interpretation_id:
            raise ContextualInterpretationError(
                "interpretation cannot supersede itself"
            )

        row = db.execute(
            self._interpretation_select() + " WHERE interpretation_id=?",
            (target_id,),
        ).fetchone()
        if row is None:
            raise ContextualInterpretationError(
                "supersedes_id must reference an existing interpretation"
            )
        target = self._decode_interpretation_row(row)
        if target.object_id != value.object_id:
            raise ContextualInterpretationError(
                "supersession must remain within one object_id"
            )

        seen: set[str] = set()
        cursor = target
        while cursor.supersedes_id is not None:
            if cursor.interpretation_id in seen:
                raise ContextualInterpretationError(
                    f"{_CORRUPT_PREFIX}:supersession_cycle"
                )
            seen.add(cursor.interpretation_id)
            if cursor.supersedes_id == value.interpretation_id:
                raise ContextualInterpretationError(
                    "supersession would create a cycle"
                )
            next_row = db.execute(
                self._interpretation_select() + " WHERE interpretation_id=?",
                (cursor.supersedes_id,),
            ).fetchone()
            if next_row is None:
                raise ContextualInterpretationError(
                    f"{_CORRUPT_PREFIX}:dangling_supersession"
                )
            cursor = self._decode_interpretation_row(next_row)

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
                self._interpretation_select() + " WHERE interpretation_id=?",
                (value.interpretation_id,),
            ).fetchone()
            if row is not None:
                existing = self._decode_interpretation_row(row)
                if row["digest"] != digest or existing != value:
                    raise ContextualInterpretationConflict(
                        "interpretation_id cannot be rebound to different content"
                    )
                status = "DUPLICATE"
            else:
                self._validate_supersession(db, value)
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
                self._interpretation_select() + " WHERE interpretation_id=?",
                (interpretation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(interpretation_id)
        return self._decode_interpretation_row(row)

    def _validate_persisted_supersession_graph(
        self,
        db: sqlite3.Connection,
        values: tuple[ContextualInterpretation, ...],
    ) -> None:
        by_id = {value.interpretation_id: value for value in values}
        for value in values:
            if value.supersedes_id is None:
                continue
            row = db.execute(
                self._interpretation_select() + " WHERE interpretation_id=?",
                (value.supersedes_id,),
            ).fetchone()
            if row is None:
                raise ContextualInterpretationError(
                    f"{_CORRUPT_PREFIX}:dangling_supersession"
                )
            target = self._decode_interpretation_row(row)
            if target.object_id != value.object_id:
                raise ContextualInterpretationError(
                    f"{_CORRUPT_PREFIX}:cross_referent_supersession"
                )

        for value in values:
            seen: set[str] = set()
            cursor = value
            while cursor.supersedes_id is not None:
                if cursor.interpretation_id in seen:
                    raise ContextualInterpretationError(
                        f"{_CORRUPT_PREFIX}:supersession_cycle"
                    )
                seen.add(cursor.interpretation_id)
                target = by_id.get(cursor.supersedes_id)
                if target is None:
                    raise ContextualInterpretationError(
                        f"{_CORRUPT_PREFIX}:invalid_supersession_graph"
                    )
                cursor = target

    def _all_interpretations(
        self,
        object_id: str,
    ) -> tuple[ContextualInterpretation, ...]:
        with self._connect() as db:
            rows = db.execute(
                self._interpretation_select()
                + " WHERE object_id=? ORDER BY interpretation_id",
                (object_id,),
            ).fetchall()
            values = tuple(self._decode_interpretation_row(row) for row in rows)
            self._validate_persisted_supersession_graph(db, values)
        return values

    @staticmethod
    def _superseded_ids(
        values: tuple[ContextualInterpretation, ...],
    ) -> frozenset[str]:
        return frozenset(
            value.supersedes_id
            for value in values
            if value.supersedes_id is not None
        )

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
        values = self._all_interpretations(object_id)
        if include_superseded:
            return values
        superseded = self._superseded_ids(values)
        return tuple(
            value for value in values if value.interpretation_id not in superseded
        )

    def admit_relation(
        self,
        value: InterpretationRelation,
    ) -> ContextualAdmissionReceipt:
        if not isinstance(value, InterpretationRelation):
            raise ContextualInterpretationError(
                "value must be an InterpretationRelation"
            )
        canonical, digest = self._digest(value.manifest())
        with self._connect() as db:
            row = db.execute(
                self._relation_select() + " WHERE relation_id=?",
                (value.relation_id,),
            ).fetchone()
            if row is not None:
                existing = self._decode_relation_row(row)
                if row["digest"] != digest or existing != value:
                    raise ContextualInterpretationConflict(
                        "relation_id cannot be rebound to different content"
                    )
                status = "DUPLICATE"
            else:
                for endpoint in (value.left_id, value.right_id):
                    endpoint_row = db.execute(
                        self._interpretation_select()
                        + " WHERE interpretation_id=?",
                        (endpoint,),
                    ).fetchone()
                    if endpoint_row is None:
                        raise ContextualInterpretationError(
                            "relation endpoint must reference an existing interpretation"
                        )
                    self._decode_interpretation_row(endpoint_row)
                db.execute(
                    "INSERT INTO contextual_relations "
                    "(relation_id,left_id,right_id,kind,digest,canonical_json) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        value.relation_id,
                        value.left_id,
                        value.right_id,
                        value.kind.value,
                        digest,
                        canonical,
                    ),
                )
                db.commit()
                status = "ACCEPTED"
        return ContextualAdmissionReceipt(
            record_id=value.relation_id,
            record_type="RELATION",
            digest=digest,
            status=status,
        )

    def _validate_persisted_relation_endpoints(
        self,
        db: sqlite3.Connection,
        relation: InterpretationRelation,
    ) -> None:
        for endpoint in (relation.left_id, relation.right_id):
            row = db.execute(
                self._interpretation_select() + " WHERE interpretation_id=?",
                (endpoint,),
            ).fetchone()
            if row is None:
                raise ContextualInterpretationError(
                    f"{_CORRUPT_PREFIX}:relation_endpoint"
                )
            self._decode_interpretation_row(row)

    def get_relation(self, relation_id: str) -> InterpretationRelation:
        _require_exact_nonempty(relation_id, "relation_id")
        with self._connect() as db:
            row = db.execute(
                self._relation_select() + " WHERE relation_id=?",
                (relation_id,),
            ).fetchone()
            if row is None:
                raise KeyError(relation_id)
            relation = self._decode_relation_row(row)
            self._validate_persisted_relation_endpoints(db, relation)
        return relation

    def _relations_for(
        self,
        interpretation_id: str,
    ) -> tuple[InterpretationRelation, ...]:
        with self._connect() as db:
            rows = db.execute(
                self._relation_select()
                + " WHERE left_id=? OR right_id=? ORDER BY relation_id",
                (interpretation_id, interpretation_id),
            ).fetchall()
            relations = tuple(self._decode_relation_row(row) for row in rows)
            for relation in relations:
                self._validate_persisted_relation_endpoints(db, relation)
        return relations

    def query(
        self,
        object_id: str,
        context: frozenset[str] | set[str],
        *,
        include_superseded: bool = False,
    ) -> tuple[ContextualInterpretationResult, ...]:
        _require_exact_nonempty(object_id, "object_id")
        normalized_context = _normalize_query_context(context)
        if type(include_superseded) is not bool:
            raise ContextualInterpretationError(
                "include_superseded must be an exact bool"
            )

        values = self._all_interpretations(object_id)
        superseded = self._superseded_ids(values)
        results: list[ContextualInterpretationResult] = []
        for value in values:
            is_current = value.interpretation_id not in superseded
            if not include_superseded and not is_current:
                continue
            if not value.required_context.issubset(normalized_context):
                continue
            if not value.excluded_context.isdisjoint(normalized_context):
                continue
            results.append(
                ContextualInterpretationResult(
                    interpretation=value,
                    relations=self._relations_for(value.interpretation_id),
                    is_current=is_current,
                )
            )
        return tuple(
            sorted(
                results,
                key=lambda item: (
                    -item.specificity,
                    item.interpretation.interpretation_id,
                ),
            )
        )


class _BorrowedConnection:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        return self.db

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.db.rollback()


@dataclass(frozen=True, slots=True)
class ContextualSemanticView:
    """Read-only pairing of a semantic object with compatible interpretations."""

    semantic_object: dict[str, object]
    interpretations: tuple[ContextualInterpretationResult, ...]


def query_semantic_interpretations(
    semantic_store: object,
    interpretation_store: ContextualInterpretationStore,
    object_id: str,
    context: frozenset[str] | set[str],
    *,
    include_superseded: bool = False,
) -> ContextualSemanticView:
    """Bind exact semantic referent existence to contextual query without mutation."""

    semantic_object = semantic_store.get(object_id)
    interpretations = interpretation_store.query(
        object_id,
        context,
        include_superseded=include_superseded,
    )
    return ContextualSemanticView(
        semantic_object=semantic_object,
        interpretations=interpretations,
    )
