from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any

from portfolio_runtime.lantern.canonical import canonical_json, canonical_json_bytes, sha256_hex


class OutboundTrustError(PermissionError):
    pass


TRUST_ROLES = frozenset({"PC", "PROVIDER", "RECONCILIATION"})


@dataclass(frozen=True, slots=True)
class AuthorityTrustState:
    authority_id: str
    role: str
    provider_id: str | None
    authority_generation: int
    revocation_epoch: int
    key_id: str
    key_digest: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class AuthorityCurrentnessReceipt:
    schema: str
    authority_id: str
    role: str
    provider_id: str | None
    authority_generation: int
    revocation_epoch: int
    key_id: str
    key_digest: str
    registry_generation: int
    registry_head_digest: str
    receipt_digest: str


class OutboundTrustRegistry:
    """Persistent outbound trust metadata; key material is never stored here.

    The registry tracks who is trusted for a role/provider, which verifier key
    identity is current, rotation generation, and revocation epoch. Actual key
    material remains host-provisioned and must match key_id/key_digest at use.
    """

    GENESIS_HEAD = sha256_hex(b"vera-mono-outbound-trust-genesis-v1")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS authorities (
                    scope_key TEXT PRIMARY KEY,
                    authority_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    provider_id TEXT,
                    authority_generation INTEGER NOT NULL,
                    revocation_epoch INTEGER NOT NULL,
                    key_id TEXT NOT NULL,
                    key_digest TEXT NOT NULL,
                    enabled INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    registry_generation INTEGER PRIMARY KEY,
                    scope_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    predecessor_digest TEXT NOT NULL,
                    event_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );
                """
            )
            if db.execute("SELECT 1 FROM meta WHERE key='generation'").fetchone() is None:
                db.execute("INSERT INTO meta(key,value) VALUES('generation','0')")
                db.execute("INSERT INTO meta(key,value) VALUES('head',?)", (self.GENESIS_HEAD,))

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        if type(value) is not str or not value:
            raise OutboundTrustError(f"{label} must be a non-empty exact string")
        return value

    @staticmethod
    def _require_digest(value: str, label: str) -> str:
        if type(value) is not str or len(value) != 64:
            raise OutboundTrustError(f"{label} must be an exact SHA-256 digest")
        try:
            int(value, 16)
        except ValueError as exc:
            raise OutboundTrustError(f"{label} must be hexadecimal") from exc
        return value.lower()

    @classmethod
    def _scope_key(cls, role: str, provider_id: str | None) -> str:
        role = cls._require_text(role, "role")
        if role not in TRUST_ROLES:
            raise OutboundTrustError(f"unsupported outbound trust role: {role}")
        if role == "PROVIDER":
            provider = cls._require_text(provider_id, "provider_id")
            return f"{role}:{provider}"
        if provider_id is not None:
            raise OutboundTrustError(f"{role} trust scope must not carry provider_id")
        return role

    @staticmethod
    def _meta(db: sqlite3.Connection) -> tuple[int, str]:
        generation = int(
            db.execute("SELECT value FROM meta WHERE key='generation'").fetchone()[0]
        )
        head = str(db.execute("SELECT value FROM meta WHERE key='head'").fetchone()[0])
        return generation, head

    @property
    def generation(self) -> int:
        with self._connect() as db:
            return self._meta(db)[0]

    @property
    def head(self) -> str:
        with self._connect() as db:
            return self._meta(db)[1]

    def read_scope(
        self,
        *,
        role: str,
        provider_id: str | None = None,
    ) -> AuthorityTrustState:
        scope_key = self._scope_key(role, provider_id)
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM authorities WHERE scope_key=?",
                (scope_key,),
            ).fetchone()
        if row is None:
            raise KeyError(scope_key)
        return AuthorityTrustState(
            authority_id=str(row["authority_id"]),
            role=str(row["role"]),
            provider_id=row["provider_id"],
            authority_generation=int(row["authority_generation"]),
            revocation_epoch=int(row["revocation_epoch"]),
            key_id=str(row["key_id"]),
            key_digest=str(row["key_digest"]),
            enabled=bool(row["enabled"]),
        )

    def has_scope(
        self,
        *,
        role: str,
        provider_id: str | None = None,
    ) -> bool:
        try:
            self.read_scope(role=role, provider_id=provider_id)
        except KeyError:
            return False
        return True

    def register(
        self,
        *,
        authority_id: str,
        role: str,
        key_id: str,
        key_digest: str,
        provider_id: str | None = None,
        expected_registry_generation: int,
    ) -> AuthorityCurrentnessReceipt:
        scope_key = self._scope_key(role, provider_id)
        authority_id = self._require_text(authority_id, "authority_id")
        key_id = self._require_text(key_id, "key_id")
        key_digest = self._require_digest(key_digest, "key_digest")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            generation, head = self._meta(db)
            if generation != expected_registry_generation:
                raise OutboundTrustError("stale outbound trust registry generation")
            if db.execute(
                "SELECT 1 FROM authorities WHERE scope_key=?", (scope_key,)
            ).fetchone() is not None:
                raise OutboundTrustError("outbound trust scope is already registered")
            next_generation = generation + 1
            db.execute(
                """
                INSERT INTO authorities(
                    scope_key,authority_id,role,provider_id,authority_generation,
                    revocation_epoch,key_id,key_digest,enabled
                ) VALUES(?,?,?,?,1,0,?,?,1)
                """,
                (
                    scope_key,
                    authority_id,
                    role,
                    provider_id,
                    key_id,
                    key_digest,
                ),
            )
            event_head = self._append_event_locked(
                db,
                registry_generation=next_generation,
                scope_key=scope_key,
                event_type="REGISTER",
                predecessor=head,
                payload={
                    "authority_id": authority_id,
                    "role": role,
                    "provider_id": provider_id,
                    "authority_generation": 1,
                    "revocation_epoch": 0,
                    "key_id": key_id,
                    "key_digest": key_digest,
                    "enabled": True,
                },
            )
            self._advance_meta(db, next_generation, event_head)
            db.commit()
        return self.assert_current(
            authority_id=authority_id,
            role=role,
            provider_id=provider_id,
            key_id=key_id,
            key_digest=key_digest,
        )

    def rotate(
        self,
        *,
        authority_id: str,
        role: str,
        key_id: str,
        key_digest: str,
        provider_id: str | None = None,
        expected_registry_generation: int,
        expected_authority_generation: int,
    ) -> AuthorityCurrentnessReceipt:
        scope_key = self._scope_key(role, provider_id)
        key_id = self._require_text(key_id, "key_id")
        key_digest = self._require_digest(key_digest, "key_digest")
        authority_id = self._require_text(authority_id, "authority_id")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            registry_generation, head = self._meta(db)
            if registry_generation != expected_registry_generation:
                raise OutboundTrustError("stale outbound trust registry generation")
            row = db.execute(
                "SELECT * FROM authorities WHERE scope_key=?", (scope_key,)
            ).fetchone()
            if row is None:
                raise OutboundTrustError("outbound trust scope is not registered")
            if row["authority_id"] != authority_id:
                raise OutboundTrustError("authority_id mismatch for trust rotation")
            if int(row["authority_generation"]) != expected_authority_generation:
                raise OutboundTrustError("stale authority generation")
            if int(row["enabled"]) != 1:
                raise OutboundTrustError("revoked authority cannot rotate without re-registration")
            if row["key_id"] == key_id and row["key_digest"] == key_digest:
                raise OutboundTrustError("rotation must change verifier key identity")
            next_authority_generation = expected_authority_generation + 1
            db.execute(
                """
                UPDATE authorities
                SET authority_generation=?, key_id=?, key_digest=?
                WHERE scope_key=?
                """,
                (
                    next_authority_generation,
                    key_id,
                    key_digest,
                    scope_key,
                ),
            )
            next_registry_generation = registry_generation + 1
            event_head = self._append_event_locked(
                db,
                registry_generation=next_registry_generation,
                scope_key=scope_key,
                event_type="ROTATE",
                predecessor=head,
                payload={
                    "authority_id": authority_id,
                    "role": role,
                    "provider_id": provider_id,
                    "authority_generation": next_authority_generation,
                    "revocation_epoch": int(row["revocation_epoch"]),
                    "key_id": key_id,
                    "key_digest": key_digest,
                    "enabled": True,
                },
            )
            self._advance_meta(db, next_registry_generation, event_head)
            db.commit()
        return self.assert_current(
            authority_id=authority_id,
            role=role,
            provider_id=provider_id,
            key_id=key_id,
            key_digest=key_digest,
        )

    def revoke(
        self,
        *,
        authority_id: str,
        role: str,
        provider_id: str | None = None,
        expected_registry_generation: int,
        expected_revocation_epoch: int,
    ) -> int:
        scope_key = self._scope_key(role, provider_id)
        authority_id = self._require_text(authority_id, "authority_id")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            registry_generation, head = self._meta(db)
            if registry_generation != expected_registry_generation:
                raise OutboundTrustError("stale outbound trust registry generation")
            row = db.execute(
                "SELECT * FROM authorities WHERE scope_key=?", (scope_key,)
            ).fetchone()
            if row is None or row["authority_id"] != authority_id:
                raise OutboundTrustError("outbound authority scope mismatch")
            if int(row["revocation_epoch"]) != expected_revocation_epoch:
                raise OutboundTrustError("stale revocation epoch")
            if int(row["enabled"]) != 1:
                raise OutboundTrustError("authority is already revoked")
            next_epoch = expected_revocation_epoch + 1
            db.execute(
                """
                UPDATE authorities SET revocation_epoch=?, enabled=0
                WHERE scope_key=?
                """,
                (next_epoch, scope_key),
            )
            next_registry_generation = registry_generation + 1
            event_head = self._append_event_locked(
                db,
                registry_generation=next_registry_generation,
                scope_key=scope_key,
                event_type="REVOKE",
                predecessor=head,
                payload={
                    "authority_id": authority_id,
                    "role": role,
                    "provider_id": provider_id,
                    "authority_generation": int(row["authority_generation"]),
                    "revocation_epoch": next_epoch,
                    "key_id": str(row["key_id"]),
                    "key_digest": str(row["key_digest"]),
                    "enabled": False,
                },
            )
            self._advance_meta(db, next_registry_generation, event_head)
            db.commit()
            return next_epoch

    def reactivate(
        self,
        *,
        authority_id: str,
        role: str,
        key_id: str,
        key_digest: str,
        provider_id: str | None = None,
        expected_registry_generation: int,
        expected_authority_generation: int,
        expected_revocation_epoch: int,
    ) -> AuthorityCurrentnessReceipt:
        scope_key = self._scope_key(role, provider_id)
        authority_id = self._require_text(authority_id, "authority_id")
        key_id = self._require_text(key_id, "key_id")
        key_digest = self._require_digest(key_digest, "key_digest")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            registry_generation, head = self._meta(db)
            if registry_generation != expected_registry_generation:
                raise OutboundTrustError("stale outbound trust registry generation")
            row = db.execute(
                "SELECT * FROM authorities WHERE scope_key=?",
                (scope_key,),
            ).fetchone()
            if row is None:
                raise OutboundTrustError("outbound trust scope is not registered")
            if int(row["enabled"]) != 0:
                raise OutboundTrustError("only revoked authority may be reactivated")
            if int(row["authority_generation"]) != expected_authority_generation:
                raise OutboundTrustError("stale authority generation")
            if int(row["revocation_epoch"]) != expected_revocation_epoch:
                raise OutboundTrustError("stale revocation epoch")
            next_authority_generation = expected_authority_generation + 1
            db.execute(
                """
                UPDATE authorities
                SET authority_id=?, authority_generation=?, key_id=?, key_digest=?,
                    enabled=1
                WHERE scope_key=?
                """,
                (
                    authority_id,
                    next_authority_generation,
                    key_id,
                    key_digest,
                    scope_key,
                ),
            )
            next_registry_generation = registry_generation + 1
            event_head = self._append_event_locked(
                db,
                registry_generation=next_registry_generation,
                scope_key=scope_key,
                event_type="REACTIVATE",
                predecessor=head,
                payload={
                    "authority_id": authority_id,
                    "role": role,
                    "provider_id": provider_id,
                    "authority_generation": next_authority_generation,
                    "revocation_epoch": expected_revocation_epoch,
                    "key_id": key_id,
                    "key_digest": key_digest,
                    "enabled": True,
                },
            )
            self._advance_meta(db, next_registry_generation, event_head)
            db.commit()
        return self.assert_current(
            authority_id=authority_id,
            role=role,
            provider_id=provider_id,
            key_id=key_id,
            key_digest=key_digest,
        )

    def assert_current(
        self,
        *,
        authority_id: str,
        role: str,
        key_id: str,
        key_digest: str,
        provider_id: str | None = None,
    ) -> AuthorityCurrentnessReceipt:
        self.verify_chain()
        scope_key = self._scope_key(role, provider_id)
        authority_id = self._require_text(authority_id, "authority_id")
        key_id = self._require_text(key_id, "key_id")
        key_digest = self._require_digest(key_digest, "key_digest")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM authorities WHERE scope_key=?", (scope_key,)
            ).fetchone()
            registry_generation, registry_head = self._meta(db)
        if row is None:
            raise OutboundTrustError("outbound trust scope is not registered")
        if int(row["enabled"]) != 1:
            raise OutboundTrustError("outbound authority is revoked")
        if row["authority_id"] != authority_id:
            raise OutboundTrustError("outbound authority identity mismatch")
        if row["key_id"] != key_id or row["key_digest"] != key_digest:
            raise OutboundTrustError("outbound verifier key is stale or untrusted")
        body = {
            "schema": "VERA_MONO_AUTHORITY_CURRENTNESS_RECEIPT_V1",
            "authority_id": authority_id,
            "role": role,
            "provider_id": provider_id,
            "authority_generation": int(row["authority_generation"]),
            "revocation_epoch": int(row["revocation_epoch"]),
            "key_id": key_id,
            "key_digest": key_digest,
            "registry_generation": registry_generation,
            "registry_head_digest": registry_head,
        }
        return AuthorityCurrentnessReceipt(
            **body,
            receipt_digest=sha256_hex(canonical_json_bytes(body)),
        )

    def verify_chain(self) -> str:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM events ORDER BY registry_generation"
            ).fetchall()
            generation, head = self._meta(db)
        predecessor = self.GENESIS_HEAD
        expected_generation = 1
        for row in rows:
            if int(row["registry_generation"]) != expected_generation:
                raise OutboundTrustError("outbound trust event generation gap")
            if row["predecessor_digest"] != predecessor:
                raise OutboundTrustError("outbound trust predecessor mismatch")
            import json
            payload = json.loads(row["payload_json"])
            body = {
                "schema": "VERA_MONO_OUTBOUND_TRUST_EVENT_V1",
                "registry_generation": expected_generation,
                "scope_key": str(row["scope_key"]),
                "event_type": str(row["event_type"]),
                "predecessor_digest": predecessor,
                "payload": payload,
            }
            observed = sha256_hex(canonical_json_bytes(body))
            if observed != row["event_digest"]:
                raise OutboundTrustError("outbound trust event digest mismatch")
            predecessor = observed
            expected_generation += 1
        if generation != expected_generation - 1:
            raise OutboundTrustError("outbound trust meta generation mismatch")
        expected_head = predecessor if rows else self.GENESIS_HEAD
        if head != expected_head:
            raise OutboundTrustError("outbound trust meta head mismatch")
        return head

    @staticmethod
    def _advance_meta(
        db: sqlite3.Connection,
        generation: int,
        head: str,
    ) -> None:
        db.execute(
            "UPDATE meta SET value=? WHERE key='generation'",
            (str(generation),),
        )
        db.execute("UPDATE meta SET value=? WHERE key='head'", (head,))

    @staticmethod
    def _append_event_locked(
        db: sqlite3.Connection,
        *,
        registry_generation: int,
        scope_key: str,
        event_type: str,
        predecessor: str,
        payload: dict[str, Any],
    ) -> str:
        body = {
            "schema": "VERA_MONO_OUTBOUND_TRUST_EVENT_V1",
            "registry_generation": registry_generation,
            "scope_key": scope_key,
            "event_type": event_type,
            "predecessor_digest": predecessor,
            "payload": payload,
        }
        digest = sha256_hex(canonical_json_bytes(body))
        db.execute(
            """
            INSERT INTO events(
                registry_generation,scope_key,event_type,predecessor_digest,
                event_digest,payload_json
            ) VALUES(?,?,?,?,?,?)
            """,
            (
                registry_generation,
                scope_key,
                event_type,
                predecessor,
                digest,
                canonical_json(payload),
            ),
        )
        return digest
