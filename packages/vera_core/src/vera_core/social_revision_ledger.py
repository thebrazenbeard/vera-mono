"""Bounded synthetic social-correction archive; never a memory or authority service.

Records are CALLER-SUPPLIED. SHA-256 chains detect changes against an
independently pinned head, not authorship. Source labels are not authentication.
Nothing here admits autobiography, current consent, or a protected action.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import hashlib
import json
import re


ROOT_HEAD = hashlib.sha256(b"VERA_SOCIAL_REVISION_ROOT_V1\0").hexdigest()
SCHEMA = "VERA_SOCIAL_REVISION_LEDGER_V1"
MAX_EVENTS = 256


class RevisionConflict(ValueError):
    """A stale parent, unrelated referent, missing entry, or altered replay."""


class SourceKind(StrEnum):
    CURRENT_USER = "CURRENT_USER"
    HISTORICAL_RECORD = "HISTORICAL_RECORD"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    FOREIGN_PERSONA = "FOREIGN_PERSONA"


class PropositionType(StrEnum):
    DEFINITION = "DEFINITION"
    INTENT = "INTENT"
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    CONSENT = "CONSENT"
    COMMITMENT = "COMMITMENT"


@dataclass(frozen=True, slots=True)
class CorrectionEntry:
    event_id: str
    session_id: str
    turn_id: str
    subject_ref: str
    proposition_type: PropositionType
    source_kind: SourceKind
    statement: str
    supersedes: str | None

    def __post_init__(self) -> None:
        for field in ("event_id", "session_id", "turn_id", "subject_ref"):
            value = getattr(self, field)
            if type(value) is not str or not value.strip() or len(value) > 256:
                raise ValueError(f"{field} must be a bounded nonblank exact string")
        if type(self.statement) is not str or not self.statement.strip() or (
            len(self.statement) > 4000
        ):
            raise ValueError("statement must be nonblank and <=4000 characters")
        if type(self.proposition_type) is not PropositionType:
            raise ValueError("proposition_type must be a typed enum")
        if type(self.source_kind) is not SourceKind:
            raise ValueError("source_kind must be a typed enum")
        if self.supersedes is not None and (
            type(self.supersedes) is not str
            or not self.supersedes.strip()
            or len(self.supersedes) > 256
        ):
            raise ValueError("supersedes must be null or a bounded ID")


def _event_digest(previous: str, entry: CorrectionEntry) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", previous):
        raise RevisionConflict("invalid previous head")
    blob = json.dumps(
        asdict(entry), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(
        b"VERA_SOCIAL_REVISION_EVENT_V1\0" + previous.encode("ascii")
        + b"\0" + blob
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CorrectionLedger:
    """Append-only, not a current host witness or private-memory database."""

    entries: tuple[CorrectionEntry, ...] = ()
    archive_status: str = "LOCAL_EPHEMERAL_SOURCE_CLAIMS_ONLY"

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or len(self.entries) > MAX_EVENTS:
            raise ValueError("bounded tuple of correction entries required")
        if self.archive_status not in (
            "LOCAL_EPHEMERAL_SOURCE_CLAIMS_ONLY",
            "UNANCHORED_HISTORICAL_EVIDENCE_ONLY",
            "ANCHORED_HISTORICAL_EVIDENCE_ONLY",
        ):
            raise ValueError("invalid archive status")
        seen: set[str] = set()
        latest: dict[tuple[str, PropositionType], str] = {}
        for entry in self.entries:
            if type(entry) is not CorrectionEntry or entry.event_id in seen:
                raise RevisionConflict("untyped or duplicate correction event")
            key = (entry.subject_ref, entry.proposition_type)
            if latest.get(key) != entry.supersedes:
                raise RevisionConflict("correction lacks exact latest same-subject parent")
            latest[key] = entry.event_id
            seen.add(entry.event_id)

    @property
    def head(self) -> str:
        previous = ROOT_HEAD
        for entry in self.entries:
            previous = _event_digest(previous, entry)
        return previous

    @property
    def current_position_authorized(self) -> bool:
        return False

    @property
    def external_action_authorized(self) -> bool:
        return False

    def latest(self, subject_ref: str, proposition_type: PropositionType
               ) -> CorrectionEntry | None:
        if type(subject_ref) is not str or type(proposition_type) is not PropositionType:
            raise ValueError("typed exact subject and proposition required")
        return next(
            (entry for entry in reversed(self.entries)
             if entry.subject_ref == subject_ref
             and entry.proposition_type is proposition_type),
            None,
        )

    def append(self, entry: CorrectionEntry, *, expected_head: str
               ) -> CorrectionLedger:
        if type(entry) is not CorrectionEntry:
            raise TypeError("typed correction entry required")
        if type(expected_head) is not str or expected_head != self.head:
            raise RevisionConflict("stale or incorrect expected head")
        if len(self.entries) >= MAX_EVENTS:
            raise RevisionConflict("bounded journal is full")
        if any(existing.event_id == entry.event_id for existing in self.entries):
            raise RevisionConflict("duplicate event ID")
        parent = self.latest(entry.subject_ref, entry.proposition_type)
        if entry.supersedes != (parent.event_id if parent else None):
            raise RevisionConflict("exact latest same-subject parent required")
        return replace(self, entries=self.entries + (entry,))

    def current_turn_evidence(self, session_id: str, turn_id: str
                              ) -> CorrectionEntry | None:
        """Unsigned candidate from a local live turn; NEVER from any restore.

        Caller-supplied source labels and session IDs do not prove authorship.
        """
        if self.archive_status != "LOCAL_EPHEMERAL_SOURCE_CLAIMS_ONLY":
            return None
        if (type(session_id) is not str or not session_id.strip()
                or type(turn_id) is not str or not turn_id.strip()):
            return None
        for entry in reversed(self.entries):
            if (
                entry.source_kind is SourceKind.CURRENT_USER
                and entry.session_id == session_id and entry.turn_id == turn_id
                and self.latest(entry.subject_ref, entry.proposition_type) == entry
            ):
                return entry
        return None

    def snapshot(self, *, allow_sensitive_export: bool = False) -> str:
        """Explicitly serialize raw text for source-only tests, NOT host permission.

        The opt-in prevents accidental full-text export. Real private storage,
        consent, data rights and canonical memory admission remain separate.
        """
        if allow_sensitive_export is not True:
            raise PermissionError("raw correction export requires explicit opt-in")
        head = ROOT_HEAD
        hashes = []
        for entry in self.entries:
            head = _event_digest(head, entry)
            hashes.append(head)
        payload = {
            "schema": SCHEMA,
            "entries": [asdict(e) for e in self.entries],
            "chain_hashes": hashes,
            "head": head,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True)

    @classmethod
    def restore(cls, raw: str, *, expected_head: str | None = None
                ) -> CorrectionLedger:
        if type(raw) is not str or len(raw) > 2_000_000:
            raise ValueError("bounded JSON snapshot required")
        payload = json.loads(raw)
        if type(payload) is not dict or set(payload) != {
            "schema", "entries", "chain_hashes", "head"
        } or payload["schema"] != SCHEMA:
            raise ValueError("wrong revision snapshot schema")
        events = payload["entries"]
        hashes = payload["chain_hashes"]
        if (type(events) is not list or len(events) > MAX_EVENTS or
                type(hashes) is not list or len(hashes) != len(events)):
            raise ValueError("malformed bounded revision snapshot")
        ledger = cls()
        expected_keys = set(CorrectionEntry.__dataclass_fields__)
        for event, recorded_hash in zip(events, hashes):
            if type(event) is not dict or set(event) != expected_keys:
                raise ValueError("unexpected revision event fields")
            entry = CorrectionEntry(
                **{**event,
                   "proposition_type": PropositionType(event["proposition_type"]),
                   "source_kind": SourceKind(event["source_kind"])}
            )
            ledger = ledger.append(entry, expected_head=ledger.head)
            if type(recorded_hash) is not str or recorded_hash != ledger.head:
                raise RevisionConflict("revision chain diverged")
        if type(payload["head"]) is not str or payload["head"] != ledger.head:
            raise RevisionConflict("revision head diverged")
        if expected_head is not None and (
            type(expected_head) is not str or expected_head != ledger.head
        ):
            raise RevisionConflict("external anchor does not match")
        return replace(
            ledger, archive_status=(
                "ANCHORED_HISTORICAL_EVIDENCE_ONLY" if expected_head is not None
                else "UNANCHORED_HISTORICAL_EVIDENCE_ONLY"
            ),
        )

    def public_receipt(self) -> dict[str, object]:
        # No text, subject, turn/session IDs, or low-entropy text hashes emitted.
        return {
            "schema": SCHEMA,
            "event_count": len(self.entries),
            "archive_status": self.archive_status,
            "qualification": "SOURCE_ONLY_UNTRUSTED",
            "current_position_authorized": False,
            "external_action_authorized": False,
            "memory_admitted": False,
        }
