"""Cross-platform inter-process lock backed by SQLite."""
from __future__ import annotations

from pathlib import Path
import sqlite3


class PortableLockError(RuntimeError):
    pass


class PortableFileLock:
    """Serialize a critical section across processes without OS-specific APIs.

    SQLite supplies the platform locking primitive. The lock database contains no
    application authority or runtime state; it only holds an EXCLUSIVE transaction
    for the duration of the context manager.
    """

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0):
        self.path = Path(path)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = float(timeout_seconds)
        self._db: sqlite3.Connection | None = None

    def __enter__(self) -> "PortableFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            db = sqlite3.connect(
                self.path,
                timeout=self.timeout_seconds,
                isolation_level=None,
            )
            db.execute(f"PRAGMA busy_timeout={int(self.timeout_seconds * 1000)}")
            db.execute(
                "CREATE TABLE IF NOT EXISTS lock_metadata "
                "(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL)"
            )
            db.execute(
                "INSERT OR IGNORE INTO lock_metadata(id,version) VALUES(1,1)"
            )
            db.execute("BEGIN EXCLUSIVE")
        except sqlite3.Error as exc:
            try:
                db.close()
            except Exception:
                pass
            raise PortableLockError(f"failed to acquire portable lock: {self.path}") from exc
        self._db = db
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        db = self._db
        self._db = None
        if db is None:
            return False
        try:
            if exc_type is None:
                db.commit()
            else:
                db.rollback()
        finally:
            db.close()
        return False
