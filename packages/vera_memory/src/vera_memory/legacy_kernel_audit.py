"""Read-only v0.2.3 Vera memory-kernel compatibility audit.

This ONLY examines the old SQLite schema and event replay coverage. It never
imports, activates, promotes, publishes, or trains on archived records.
Output intentionally contains counts and finding types, not personal data.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any


class LegacyKernelAuditError(ValueError):
    """Fail-closed input or schema rejection; never includes source content."""


EVIDENCE_CLASS = "HISTORICAL_V023_SQLITE_SCHEMA_AUDIT_NOT_MEMORY_ADMISSION"
VERSIONS = ("1.0.0", "1.0.0", "1.0.0")
HANDLED_EVENTS = frozenset({
    "source_created", "memory_created", "legacy_memory_created_migrated",
    "memory_lifecycle_changed", "relationship_created", "tombstone_created",
    "promotion_requested", "promotion_decided", "reconciliation_created",
})
REQUIRED_COLUMNS = {
    "sources": frozenset({"source_id", "lineage_id"}),
    "memories": frozenset({"memory_id", "source_id", "lineage_id"}),
    "events": frozenset({"event_id", "event_seq", "event_type",
                         "subject_id", "payload_json"}),
    "projection_versions": frozenset({"projection_name", "projection_version",
                                      "reducer_version", "schema_version"}),
    "relationships": frozenset({"relation_id", "source_memory_id", "target_memory_id"}),
    "migration_records": frozenset({"migration_id", "legacy_event_id",
                                    "canonical_source_id", "migration_version"}),
}


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("invalid JSON constant")


def _validate_path(path: str | Path, *, max_db_bytes: int) -> Path:
    if type(max_db_bytes) is not int or not 1024 <= max_db_bytes <= 1024**3:
        raise LegacyKernelAuditError("bounded size limit required")
    try:
        candidate = Path(path).absolute()
        if not candidate.is_absolute() or any(x.is_symlink() for x in (
                candidate, *candidate.parents)):
            raise LegacyKernelAuditError("symbolic links are forbidden")
        if not candidate.is_file() or not 0 < candidate.stat().st_size <= max_db_bytes:
            raise LegacyKernelAuditError("database size or existence invalid")
        for suffix in ("-wal", "-shm", "-journal"):
            if Path(str(candidate) + suffix).exists():
                raise LegacyKernelAuditError("active SQLite sidecar not supported")
        with candidate.open("rb") as stream:
            header = stream.read(20)
            if header[:16] != b"SQLite format 3\x00" or len(header) != 20:
                raise LegacyKernelAuditError("not a SQLite database")
            if header[18:20] != b"\x01\x01":
                raise LegacyKernelAuditError("WAL or unknown SQLite journal mode unsupported")
    except (OSError, TypeError) as exc:
        raise LegacyKernelAuditError("unreadable historical SQLite input") from exc
    return candidate


def audit_legacy_kernel_database(
    path: str | Path, *, max_db_bytes: int = 64 * 1024 * 1024,
    max_rows: int = 100_000, max_payload_bytes: int = 65_536,
) -> dict[str, Any]:
    """Count replay blockers without exposing raw archived content.

    Audit is NOT a substitute for authenticating external source bytes,
    proving SQL journal completeness, consent admission or native runtime
    migration. Inspect a quiescent/offline file copy; WAL sidecars fail.
    """
    if type(max_rows) is not int or not 2 <= max_rows <= 100_000:
        raise LegacyKernelAuditError("bounded row limit required")
    if type(max_payload_bytes) is not int or not 128 <= max_payload_bytes <= 1_048_576:
        raise LegacyKernelAuditError("bounded payload limit required")
    candidate = _validate_path(path, max_db_bytes=max_db_bytes)
    counts: dict[str, int] = {}
    issues: Counter[str] = Counter()

    try:
        # immutable=1 prevents shared-memory/rollback creation and assumes
        # no concurrent writer. Input-side sidecars are forbidden above.
        with closing(sqlite3.connect(candidate.as_uri() + "?mode=ro&immutable=1",
                                     uri=True, timeout=1)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.set_progress_handler(lambda: 0, 500)
            existing = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not set(REQUIRED_COLUMNS).issubset(existing):
                raise LegacyKernelAuditError("unsupported legacy kernel schema")
            for table, required in REQUIRED_COLUMNS.items():
                actual = {r[1] for r in conn.execute(
                    f'PRAGMA table_info("{table}")')}
                if not required.issubset(actual):
                    raise LegacyKernelAuditError("unsupported legacy kernel schema")
                # Fixed, validated table names only. No user SQL accepted.
                counts[table] = int(conn.execute(
                    f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                if counts[table] > max_rows:
                    raise LegacyKernelAuditError("legacy table row limit exceeded")

            versions = conn.execute(
                "SELECT projection_version, reducer_version, schema_version "
                "FROM projection_versions WHERE projection_name='logical_memory'"
            ).fetchall()
            if len(versions) != 1 or tuple(versions[0]) != VERSIONS:
                issues["incompatible_projection_version"] += 1
            sources = dict(conn.execute(
                "SELECT source_id,lineage_id FROM sources").fetchall())
            memories = {
                row[0]: (row[1], row[2])
                for row in conn.execute(
                    "SELECT memory_id,source_id,lineage_id FROM memories")
            }
            events = conn.execute(
                "SELECT event_id,event_seq,event_type,subject_id,payload_json "
                "FROM events ORDER BY event_seq").fetchall()
            event_ids = {r[0] for r in events}
            source_events: set[str] = set()
            memory_events: set[str] = set()
            relationship_events: set[str] = set()
            for expected_seq, (event_id, seq, event_type, subject_id, raw) in enumerate(
                    events, start=1):
                if type(seq) is not int or seq != expected_seq:
                    issues["noncontiguous_event_sequence"] += 1
                if event_type not in HANDLED_EVENTS:
                    issues["unhandled_event_type"] += 1
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > max_payload_bytes:
                    issues["invalid_event_payload"] += 1
                    continue
                try:
                    body = json.loads(
                        raw, object_pairs_hook=_no_duplicate_keys,
                        parse_constant=_invalid_constant)
                    if type(body) is not dict:
                        raise ValueError("event payload not an object")
                except (ValueError, TypeError, UnicodeError):
                    issues["invalid_event_payload"] += 1
                    continue
                if event_type == "source_created":
                    source_events.add(subject_id)
                    if subject_id not in sources:
                        issues["unreplayable_source_event"] += 1
                elif event_type in ("memory_created", "legacy_memory_created_migrated"):
                    memory_events.add(subject_id)
                    record = body.get("record")
                    if type(record) is not dict:
                        issues["unreplayable_legacy_memory_event"] += 1
                    elif record.get("source_id") not in sources:
                        issues["unreplayable_memory_source"] += 1
                elif event_type == "relationship_created":
                    record = body.get("record")
                    if type(record) is not dict or any(
                            record.get(field) not in memories for field in (
                                "source_memory_id", "target_memory_id")):
                        issues["unreplayable_relationship"] += 1
                    if type(record) is dict and type(record.get("relation_id")) is str:
                        relationship_events.add(record["relation_id"])

            for memory_id, (source_id, lineage_id) in memories.items():
                if source_id not in sources:
                    issues["orphaned_memory_source"] += 1
                elif sources[source_id] != lineage_id:
                    issues["orphaned_memory_lineage"] += 1
                if memory_id not in memory_events:
                    issues["projection_without_origin_event"] += 1
            # Historical source table does not require every source to
            # originate inside the event stream; report as consistency gap.
            for source_id in sources:
                if source_id not in source_events:
                    issues["source_without_origin_event"] += 1

            for legacy_event_id, canonical_source_id in conn.execute(
                    "SELECT legacy_event_id,canonical_source_id "
                    "FROM migration_records"):
                if legacy_event_id not in event_ids or canonical_source_id not in sources:
                    issues["unreplayable_migration_reference"] += 1
            for relation_id, source_memory, target_memory in conn.execute(
                    "SELECT relation_id,source_memory_id,target_memory_id "
                    "FROM relationships"):
                if source_memory not in memories or target_memory not in memories:
                    issues["orphaned_relationship"] += 1
                if relation_id not in relationship_events:
                    issues["relationship_without_origin_event"] += 1
    except LegacyKernelAuditError:
        raise
    except (sqlite3.Error, ValueError, OverflowError, UnicodeError) as exc:
        raise LegacyKernelAuditError("unsafe or corrupt legacy SQLite structure") from exc

    return {
        "evidence_class": EVIDENCE_CLASS,
        "legacy_schema": "vera_memory.v0.2.3.event_sourcing",
        "status": "historical_source_structure_only",
        "ok": not issues,
        "counts": counts,
        "findings": dict(sorted(issues.items())),
        "privacy": "no source text, record identifiers, actors or payloads exposed",
        "effect": "read_only_no_memory_admission",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit_legacy_kernel_database(args.database),
                     sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
