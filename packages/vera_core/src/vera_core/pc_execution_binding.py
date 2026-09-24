from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any

from pc_connection.envelopes import AuthorizationEnvelope, JobEnvelope
from portfolio_runtime.lantern.canonical import (
    canonical_json,
    canonical_json_bytes,
    sha256_hex,
)

from .lifecycle import AcceptedLifecyclePermit
from .outbound_authority import pc_authority_subject


class PCExecutionBindingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PCExecutionLease:
    """Exact server/host attempt identity; no job-id inference is allowed."""

    job_id: str
    attempt_id: str
    claim_generation: int
    lease_id: str
    lease_fence: int


@dataclass(frozen=True, slots=True)
class PreparedPCDispatch:
    permit: AcceptedLifecyclePermit
    job: JobEnvelope
    authorization: AuthorizationEnvelope
    job_digest: str
    authorization_digest: str
    authority_subject: str


@dataclass(frozen=True, slots=True)
class PCExecutionBinding:
    binding_digest: str
    effect_id: str
    prepared: PreparedPCDispatch
    lease: PCExecutionLease


class PCExecutionBindingStore:
    """Append-only durable Vera-side binding for a PCCC execution attempt.

    This is not the Windows host's JobJournal and does not claim machine
    execution. It preserves the exact lifecycle permit, job, authorization,
    effect identity, and lease tuple needed to explain/recover an interrupted
    attempt when conversational state is gone.
    """

    SCHEMA = "VERA_MONO_PC_EXECUTION_BINDING_V1"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS pc_execution_bindings (
                    job_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    binding_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(job_id, attempt_id)
                )
                """
            )

    @staticmethod
    def _mapping(value: object, fields: tuple[str, ...]) -> dict[str, Any]:
        return {field: getattr(value, field) for field in fields}

    @classmethod
    def _payload(
        cls,
        prepared: PreparedPCDispatch,
        lease: PCExecutionLease,
    ) -> dict[str, Any]:
        if type(prepared) is not PreparedPCDispatch:
            raise PCExecutionBindingError(
                "prepared must be exact PreparedPCDispatch"
            )
        if type(lease) is not PCExecutionLease:
            raise PCExecutionBindingError(
                "lease must be exact PCExecutionLease"
            )
        return {
            "schema": cls.SCHEMA,
            "effect_id": f"pc:{prepared.job.envelope_id}",
            "job": cls._mapping(prepared.job, JobEnvelope.FIELDS),
            "authorization": cls._mapping(
                prepared.authorization,
                AuthorizationEnvelope.FIELDS,
            ),
            "permit": {
                **prepared.permit.canonical_body(),
                "permit_digest": prepared.permit.permit_digest,
            },
            "prepared": {
                "job_digest": prepared.job_digest,
                "authorization_digest": prepared.authorization_digest,
                "authority_subject": prepared.authority_subject,
            },
            "lease": {
                "job_id": lease.job_id,
                "attempt_id": lease.attempt_id,
                "claim_generation": lease.claim_generation,
                "lease_id": lease.lease_id,
                "lease_fence": lease.lease_fence,
            },
        }

    def bind(
        self,
        prepared: PreparedPCDispatch,
        lease: PCExecutionLease,
    ) -> PCExecutionBinding:
        payload = self._payload(prepared, lease)
        payload_json = canonical_json(payload)
        digest = sha256_hex(payload_json.encode("utf-8"))
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT * FROM pc_execution_bindings
                WHERE job_id=? AND attempt_id=?
                """,
                (lease.job_id, lease.attempt_id),
            ).fetchone()
            if row is not None:
                if (
                    row["binding_digest"] != digest
                    or row["payload_json"] != payload_json
                ):
                    raise PCExecutionBindingError(
                        "PC attempt identity already binds different execution evidence"
                    )
                db.commit()
                return self._decode(
                    str(row["binding_digest"]),
                    str(row["payload_json"]),
                )
            db.execute(
                """
                INSERT INTO pc_execution_bindings(
                    job_id,attempt_id,binding_digest,payload_json
                ) VALUES(?,?,?,?)
                """,
                (
                    lease.job_id,
                    lease.attempt_id,
                    digest,
                    payload_json,
                ),
            )
            db.commit()
        return PCExecutionBinding(digest, payload["effect_id"], prepared, lease)

    def read(
        self,
        job_id: str,
        attempt_id: str,
    ) -> PCExecutionBinding:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """
                SELECT * FROM pc_execution_bindings
                WHERE job_id=? AND attempt_id=?
                """,
                (job_id, attempt_id),
            ).fetchone()
        if row is None:
            raise KeyError((job_id, attempt_id))
        return self._decode(
            str(row["binding_digest"]),
            str(row["payload_json"]),
        )

    def all(self) -> tuple[PCExecutionBinding, ...]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT * FROM pc_execution_bindings
                ORDER BY job_id,attempt_id
                """
            ).fetchall()
        return tuple(
            self._decode(
                str(row["binding_digest"]),
                str(row["payload_json"]),
            )
            for row in rows
        )

    @classmethod
    def _decode(
        cls,
        binding_digest: str,
        payload_json: str,
    ) -> PCExecutionBinding:
        if sha256_hex(payload_json.encode("utf-8")) != binding_digest:
            raise PCExecutionBindingError(
                "PC execution binding digest mismatch"
            )
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise PCExecutionBindingError(
                "PC execution binding is not valid JSON"
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema") != cls.SCHEMA:
            raise PCExecutionBindingError(
                "unsupported PC execution binding schema"
            )

        job = JobEnvelope.from_mapping(payload["job"])
        authorization = AuthorizationEnvelope.from_mapping(
            payload["authorization"]
        )
        raw_permit = dict(payload["permit"])
        permit_digest = raw_permit.pop("permit_digest")
        permit = AcceptedLifecyclePermit(
            **raw_permit,
            permit_digest=permit_digest,
        )
        if (
            sha256_hex(canonical_json_bytes(permit.canonical_body()))
            != permit.permit_digest
        ):
            raise PCExecutionBindingError(
                "stored lifecycle permit digest mismatch"
            )

        job_digest = job.digest()
        authorization_digest = authorization.digest()
        prepared_fields = payload["prepared"]
        if prepared_fields["job_digest"] != job_digest:
            raise PCExecutionBindingError("stored PC job digest mismatch")
        if prepared_fields["authorization_digest"] != authorization_digest:
            raise PCExecutionBindingError(
                "stored PC authorization digest mismatch"
            )
        authority_subject = pc_authority_subject(
            job_digest=job_digest,
            authorization_digest=authorization_digest,
            lifecycle_permit_digest=permit.permit_digest,
        )
        if prepared_fields["authority_subject"] != authority_subject:
            raise PCExecutionBindingError(
                "stored PC authority subject mismatch"
            )

        prepared = PreparedPCDispatch(
            permit=permit,
            job=job,
            authorization=authorization,
            job_digest=job_digest,
            authorization_digest=authorization_digest,
            authority_subject=authority_subject,
        )
        raw_lease = payload["lease"]
        lease = PCExecutionLease(
            job_id=raw_lease["job_id"],
            attempt_id=raw_lease["attempt_id"],
            claim_generation=raw_lease["claim_generation"],
            lease_id=raw_lease["lease_id"],
            lease_fence=raw_lease["lease_fence"],
        )
        expected_effect_id = f"pc:{job.envelope_id}"
        if payload["effect_id"] != expected_effect_id:
            raise PCExecutionBindingError(
                "stored PC effect identity mismatch"
            )
        if canonical_json(cls._payload(prepared, lease)) != payload_json:
            raise PCExecutionBindingError(
                "PC execution binding canonical readback mismatch"
            )
        return PCExecutionBinding(
            binding_digest=binding_digest,
            effect_id=expected_effect_id,
            prepared=prepared,
            lease=lease,
        )
