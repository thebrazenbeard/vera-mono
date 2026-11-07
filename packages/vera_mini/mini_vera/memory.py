"""Explicit-consent, single-process local memory with a tamper-evident journal.

This does not contain or reconstruct a ChatGPT conversation history. The user
decides exactly which entries are written to this local file. A hash chain can
detect accidental modification, not authenticate records against an adversary
who can rewrite the whole local file.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile


_MAX_BYTES = 1024 * 1024
_MAX_RECORDS = 512


class MemoryError(ValueError):
    """Refused memory operation or invalid journal."""


def _canonical(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _validate_event(event: dict, prior: list[dict]) -> None:
    """Hash-valid events must also match the exact, safe semantic schema."""
    kind = event.get("kind")
    common = {"seq", "prev_sha256", "sha256", "timestamp_utc", "kind"}
    fields = ({"content", "scope"} if kind == "remember" else
              {"target_seq"} if kind == "forget" else None)
    if fields is None or set(event) != common | fields:
        raise MemoryError("invalid memory event schema")
    stamp = event["timestamp_utc"]
    if type(stamp) is not str or len(stamp) > 60:
        raise MemoryError("invalid memory timestamp")
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError as error:
        raise MemoryError("invalid memory timestamp") from error
    if parsed.tzinfo is None:
        raise MemoryError("memory timestamp must be timezone-aware")
    if kind == "remember":
        content = event["content"]
        if (type(content) is not str or not 1 <= len(content.strip()) <= 2000 or
                event["scope"] not in ("personal", "project", "preference")):
            raise MemoryError("invalid saved memory contents/scope")
    else:
        target = event["target_seq"]
        if type(target) is not int or not any(
                item["seq"] == target and item["kind"] == "remember" for item in prior):
            raise MemoryError("invalid memory tombstone target")


class MemoryJournal:
    """Local, explicit opt-in journal; not independently verified memory."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().absolute()
        self._require_safe_path()

    def _require_safe_path(self) -> None:
        """Recheck path components at each operation, not just construction.

        On Windows, directory junctions are also reparse redirects. These
        checks catch substituted parents between calls; they cannot promise
        safety against a privileged adversary racing within one system call.
        """
        for component in (self.path, *self.path.parents):
            if component.is_symlink() or (hasattr(component, "is_junction")
                                       and component.is_junction()):
                raise MemoryError("journal path may not traverse symbolic links or junctions")

    def _load(self) -> list[dict]:
        self._require_safe_path()
        if not self.path.exists():
            return []
        if not self.path.is_file() or self.path.stat().st_size > _MAX_BYTES:
            raise MemoryError("journal is not a bounded regular file")
        records: list[dict] = []
        previous = "0" * 64
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        raise MemoryError("empty record in journal")
                    event = json.loads(line)
                    if not isinstance(event, dict) or len(records) >= _MAX_RECORDS:
                        raise MemoryError("invalid journal record count/type")
                    digest = event.pop("sha256", None)
                    if not isinstance(digest, str) or event.get("seq") != len(records) + 1 \
                            or event.get("prev_sha256") != previous \
                            or hashlib.sha256(_canonical(event)).hexdigest() != digest:
                        raise MemoryError("journal hash chain invalid")
                    event["sha256"] = digest
                    _validate_event(event, records)
                    records.append(event)
                    previous = digest
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as error:
            raise MemoryError("journal cannot be decoded and verified") from error
        return records

    def verify(self) -> bool:
        """Verify local structure/chain, not authorship or underlying truth."""
        self._load()
        return True

    def read(self) -> list[dict]:
        """Return active memories, omitting later explicitly forgotten entries."""
        events = self._load()
        forgotten = {event.get("target_seq") for event in events if event.get("kind") == "forget"}
        return [dict(event) for event in events if event.get("kind") == "remember"
                and event.get("seq") not in forgotten]

    def _append_event(self, fields: dict, *, consent: bool) -> dict:
        if consent is not True:
            raise PermissionError("explicit consent=True is required for persistent memory")
        self._require_safe_path()
        previous = self._load()
        if len(previous) >= _MAX_RECORDS:
            raise MemoryError("journal record limit reached")
        record = {
            "seq": len(previous) + 1,
            "prev_sha256": previous[-1]["sha256"] if previous else "0" * 64,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        record["sha256"] = hashlib.sha256(_canonical(record)).hexdigest()
        data = b"".join(_canonical(item) + b"\n" for item in (*previous, record))
        if len(data) > _MAX_BYTES:
            raise MemoryError("journal size limit reached")
        self._require_safe_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._require_safe_path()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=self.path.parent,
                                             prefix=".mini-vera-", delete=False) as stream:
                temporary = Path(stream.name)
                os.chmod(temporary, 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self._require_safe_path()
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        return dict(record)

    def append(self, content: str, *, consent: bool = False,
               scope: str = "personal") -> dict:
        if not isinstance(content, str) or not 1 <= len(content.strip()) <= 2000:
            raise MemoryError("memory text must have 1–2000 characters")
        if scope not in ("personal", "project", "preference"):
            raise MemoryError("unsupported memory scope")
        return self._append_event({"kind": "remember", "content": content.strip(),
                                   "scope": scope}, consent=consent)

    def forget(self, seq: int, *, consent: bool = False) -> dict:
        if not isinstance(seq, int) or seq < 1 or not any(
                item["seq"] == seq for item in self.read()):
            raise MemoryError("no active memory with that sequence")
        return self._append_event({"kind": "forget", "target_seq": seq},
                                  consent=consent)
