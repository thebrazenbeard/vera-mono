"""Durable monotonic host-revision floor in UNPROTECTED local SQLite.

This is a SOURCE CANDIDATE, not an authenticated host-controlled store.
Same-user file replacement/rollback, filesystem permission drift and
untrusted issuer callbacks remain outside this module's authority.
No neural model, memory or credentials are accessed.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sqlite3
import stat

MAX_LEDGER_BYTES = 4 * 1024 * 1024
MAX_REVISION = 2**64 - 1
HEX16 = re.compile(r"[0-9a-f]{16}\Z")
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS revision_floor ("
    "singleton INTEGER NOT NULL PRIMARY KEY CHECK(singleton=1), "
    "revision_hex TEXT NOT NULL CHECK(length(revision_hex)=16)"
    ") WITHOUT ROWID"
)


class RevisionFloorRefused(ValueError):
    """Cannot guarantee even the unprotected SQLite floor's consistency."""


def _check_path(path: Path) -> Path:
    if not isinstance(path, Path) or not path.is_absolute() or path.suffix != ".sqlite":
        raise RevisionFloorRefused("revision floor needs absolute .sqlite path")
    root = Path(__file__).resolve().parents[2]
    if path.is_relative_to(root):
        raise RevisionFloorRefused("revision floor must remain outside source")
    if not path.parent.is_dir():
        raise RevisionFloorRefused("revision floor parent directory unavailable")
    try:
        for parent in (path.parent, *path.parent.parents):
            attr = os.lstat(parent)
            if (stat.S_ISLNK(attr.st_mode)
                    or getattr(attr, "st_file_attributes", 0) & 0x400):
                raise RevisionFloorRefused("revision floor parent link refused")
        if path.exists() or path.is_symlink():
            attr = os.lstat(path)
            if (not stat.S_ISREG(attr.st_mode)
                    or getattr(attr, "st_file_attributes", 0) & 0x400
                    or not 0 <= attr.st_size <= MAX_LEDGER_BYTES):
                raise RevisionFloorRefused("invalid or oversized revision floor file")
    except (OSError, ValueError) as exc:
        raise RevisionFloorRefused("revision floor filesystem unavailable") from exc
    return path


class UnprotectedRevisionFloor:
    """Atomic local revision max; the authority callback must be independent.

    Each call takes a SQLite BEGIN IMMEDIATE transaction and reads back the
    commit. Fresh Python processes and concurrent calls observe the maximum
    committed revision, except when the untrusted file itself is rolled back
    or replaced by a principal with filesystem write access.
    """

    def __init__(self, path: Path) -> None:
        self._path = _check_path(path)

    def __call__(self, revision: int) -> int:
        return self.advance(revision)

    def advance(self, revision: int) -> int:
        if type(revision) is not int or not 0 <= revision <= MAX_REVISION:
            raise RevisionFloorRefused("revision outside uint64 range")
        _check_path(self._path)
        con: sqlite3.Connection | None = None
        try:
            con = sqlite3.connect(str(self._path), timeout=10, isolation_level=None)
            con.execute("PRAGMA trusted_schema=OFF")
            con.execute("PRAGMA synchronous=FULL")
            con.execute("PRAGMA busy_timeout=10000")
            con.execute("PRAGMA journal_mode=DELETE")
            if con.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise RevisionFloorRefused("revision floor database corrupt")
            con.execute("BEGIN IMMEDIATE")
            con.execute(SCHEMA)
            sql = con.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='revision_floor'").fetchone()
            if sql != (SCHEMA.replace(" IF NOT EXISTS", ""),):
                raise RevisionFloorRefused("revision floor schema differs")
            rows = con.execute(
                "SELECT singleton, revision_hex FROM revision_floor").fetchall()
            if len(rows) > 1:
                raise RevisionFloorRefused("multiple revision floor rows")
            previous = -1
            if rows:
                row_id, encoded = rows[0]
                if (type(row_id) is not int or row_id != 1
                        or type(encoded) is not str
                        or HEX16.fullmatch(encoded) is None):
                    raise RevisionFloorRefused("revision floor row invalid")
                previous = int(encoded, 16)
            value = max(previous, revision)
            encoded = f"{value:016x}"
            if not rows:
                con.execute(
                    "INSERT INTO revision_floor(singleton,revision_hex) "
                    "VALUES(1,?)", (encoded,))
            elif value != previous:
                con.execute(
                    "UPDATE revision_floor SET revision_hex=? WHERE singleton=1",
                    (encoded,))
            con.commit()
            final = con.execute(
                "SELECT revision_hex FROM revision_floor WHERE singleton=1"
                ).fetchone()
            if final != (encoded,):
                raise RevisionFloorRefused("committed revision readback mismatched")
            return value
        except (sqlite3.DatabaseError, OSError) as exc:
            raise RevisionFloorRefused(
                "unprotected revision floor corrupt, locked or unavailable"
            ) from exc
        finally:
            if con is not None:
                if con.in_transaction:
                    con.rollback()
                con.close()
