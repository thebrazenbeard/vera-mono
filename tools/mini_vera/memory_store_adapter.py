"""Read-only host-admitted MemoryStore records as a MemoryLedger-shaped source.

This is an integration *candidate* for a trusted host embedding Mini-Vera.
It does not install, create, migrate or authenticate a memory store or grant.
The host MUST preapprove each explicit ID before a record is read, separately
issue the external head/revision/epoch grant, and approve the content after
the read through ``host_memory_broker.bind_host_public_memory``.

The source database's ``collaborator_shared`` privacy scope is NOT promoted to
PUBLIC. Only an explicitly marked PUBLIC record can pass this adapter, and
even that label is insufficient without independent host approval.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .compose import CompositionRejected, ID, MAX_RECORD_BYTES, canonical, sha256


_ALLOW_CLASSES = frozenset({"current_state", "decision", "procedural", "semantic"})


class ReadOnlyMemoryStoreAsLedger:
    """Structural adapter; use with an *existing* read-only MemoryStore.

    Expected source API is the actual workspace-local ``MemoryStore``:
    ``store.read_only``, ``store.conn`` and ``store.get_memory(memory_id)``.
    This adapter reads only the latest event hash and host-preapproved IDs.
    Its ``current_head`` is NOT a trusted anchor by itself; the current host
    grant must pin it independently.  No memory writes occur here.
    """

    def __init__(
        self, store: Any, *, project_id: str, identity_id: str,
        branch_id: str, subject_id: str,
        allow_public_id: Callable[[str, str], bool],
        now_utc: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if (type(project_id) is not str or not project_id or
                type(identity_id) is not str or not identity_id or
                type(branch_id) is not str or not branch_id or
                type(subject_id) is not str or not subject_id or
                not callable(allow_public_id) or not callable(now_utc)):
            raise CompositionRejected("explicit host memory scope and ID approval required")
        self._store = store
        self.project_id = project_id
        self.identity_id = identity_id
        self.branch_id = branch_id
        self.subject_id = subject_id
        self._allow_public_id = allow_public_id
        self._now_utc = now_utc
        self._require_query_only()

    def _require_query_only(self) -> None:
        if getattr(self._store, "read_only", None) is not True:
            raise CompositionRejected("MemoryStore must be opened read-only")
        try:
            result = self._store.conn.execute("PRAGMA query_only").fetchone()
        except Exception as exc:
            raise CompositionRejected("MemoryStore read-only state unavailable") from exc
        if result is None or result[0] != 1:
            raise CompositionRejected("MemoryStore SQLite query_only is not active")

    @property
    def current_head(self) -> str:
        self._require_query_only()
        try:
            row = self._store.conn.execute(
                "SELECT event_hash FROM events ORDER BY event_seq DESC LIMIT 1"
            ).fetchone()
        except Exception as exc:
            raise CompositionRejected("MemoryStore event head unavailable") from exc
        head = row[0] if row is not None else "0" * 64
        if type(head) is not str or len(head) != 64 or any(c not in "0123456789abcdef" for c in head):
            raise CompositionRejected("invalid MemoryStore event head")
        return head

    @staticmethod
    def _valid_time(value: Any, now: datetime, *, future: bool) -> bool:
        if value is None:
            return True
        if type(value) is not str:
            return False
        try:
            bound = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        if bound.tzinfo is None:
            return False
        return now <= bound if future else bound <= now

    def read(self, record_id: str, *, expected_head: str | None = None) -> Any:
        """Return a compatible MemoryRecord ONLY after host ID approval.

        ``allow_public_id`` must be authenticated by the host independently of
        the MemoryStore labels, and must reject IDs outside the current grant.
        The outer ``host_memory_broker`` still rechecks content policy and the
        grant around the whole projection, including post-inference.
        """
        if type(record_id) is not str or ID.fullmatch(record_id) is None:
            raise CompositionRejected("invalid approved MemoryStore ID")
        if type(expected_head) is not str or expected_head != self.current_head:
            raise CompositionRejected("MemoryStore event head drift before record read")
        try:
            allowed = self._allow_public_id(record_id, expected_head)
        except Exception as exc:
            raise CompositionRejected("host MemoryStore ID approval unavailable") from exc
        if allowed is not True:
            raise CompositionRejected("host MemoryStore ID was not preapproved")
        try:
            row = self._store.get_memory(record_id)
        except KeyError:
            raise
        except Exception as exc:
            raise CompositionRejected("host MemoryStore selected record read failed") from exc
        if type(row) is not dict or row.get("memory_id") != record_id:
            raise CompositionRejected("invalid MemoryStore selected record")
        required = (
            "source_id", "source_locator", "content_hash", "statement", "author",
            "memory_class", "scope", "branch_id", "subject_id", "privacy_scope", "consent",
            "endorsement", "lifecycle", "instruction_status", "risk_flags", "revision",
        )
        if any(field not in row for field in required):
            raise CompositionRejected("MemoryStore selected record lacks provenance fields")
        statement = row["statement"]
        if (type(statement) is not str or not statement.strip()
                or len(statement.encode("utf-8")) > MAX_RECORD_BYTES
                or type(row["content_hash"]) is not str
                or row["content_hash"] != sha256(statement.encode("utf-8"))):
            raise CompositionRejected("MemoryStore statement/source hash mismatch or out of bounds")
        if (row["privacy_scope"] != "PUBLIC" or row["consent"] != "granted"
                or row["scope"] != "project" or row["branch_id"] != self.branch_id
                or row["subject_id"] != self.subject_id
                or row["endorsement"] != "endorsed_current"
                or row["lifecycle"] != "active"
                or row["instruction_status"] != "data_only"
                or type(row["risk_flags"]) is not list or row["risk_flags"]
                or row["memory_class"] not in _ALLOW_CLASSES):
            raise CompositionRejected("MemoryStore record not qualified for PUBLIC project projection")
        # The current MemoryStore 0.4.0 schema has no project_id field: it
        # expresses scope through branch_id, subject_id and source_locator.
        # If a future host export *does* supply project_id, never discard a
        # contradictory/empty value and relabel its record to this project.
        if "project_id" in row and (type(row["project_id"]) is not str
                                     or row["project_id"] != self.project_id):
            raise CompositionRejected("MemoryStore source project scope mismatch")
        if (type(row["revision"]) is not int or row["revision"] < 1
                or any(type(row[field]) is not str or not row[field]
                       for field in ("source_id", "source_locator", "author"))):
            raise CompositionRejected("invalid MemoryStore provenance or revision")
        try:
            now = self._now_utc()
        except Exception as exc:
            raise CompositionRejected("host MemoryStore clock unavailable") from exc
        if type(now) is not datetime or now.tzinfo is None:
            raise CompositionRejected("invalid host MemoryStore UTC clock")
        if (not self._valid_time(row.get("valid_from"), now, future=False)
                or not self._valid_time(row.get("valid_until"), now, future=True)):
            raise CompositionRejected("MemoryStore record outside approved validity window")
        if self.current_head != expected_head:
            raise CompositionRejected("MemoryStore event head drift after record read")

        # Existing MemoryLedger projector verifies these required typed fields.
        # Projected record digest is local consistency, NOT authority.
        from vera_memory import MemoryClass, MemoryRecord

        digest = sha256(canonical({
            "memory_id": record_id, "source_id": row["source_id"],
            "source_locator": row["source_locator"],
            "content_hash": row["content_hash"], "revision": row["revision"],
            "event_head": expected_head,
        }))
        return MemoryRecord(
            record_id=record_id, text=statement,
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor=row["author"],
            authority_ref="MEMORY_STORE_SOURCE_NOT_HOST_AUTHORITY",
            privacy_ref="PUBLIC",
            provenance_refs=(row["source_id"], row["source_locator"]),
            operation_id=f"memory-store:{record_id}:{row['revision']}",
            project_id=self.project_id, governed_identity_id=self.identity_id,
            supersedes=None, status="CURRENT", superseded_by=None,
            record_digest=digest,
        )
