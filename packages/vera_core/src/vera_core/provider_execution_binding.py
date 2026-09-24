from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex

from .lifecycle import AcceptedLifecyclePermit
from .outbound_authority import provider_authority_subject
from .task_execution import TaskDependencyRef


class ProviderExecutionBindingError(ValueError):
    pass


def _exact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


@dataclass(frozen=True, slots=True)
class PreparedProviderDispatch:
    permit: AcceptedLifecyclePermit
    effect_id: str
    provider_id: str
    operation: str
    request_payload: Any
    request_digest: str
    authority_subject: str
    task_dependency: TaskDependencyRef | None = None


@dataclass(frozen=True, slots=True)
class ProviderExecutionRecoveryAssessment:
    effect_id: str
    mechanical_effect_id: str
    provider_id: str
    operation: str
    fence_state: str | None
    lifecycle_permit_current: bool
    dispatch_candidate_allowed: bool
    recovery_required: bool
    terminal: bool
    reason: str


@dataclass(frozen=True, slots=True)
class ProviderExecutionBinding:
    binding_digest: str
    effect_id: str
    provider_id: str
    operation: str
    request_digest: str
    authority_subject: str
    permit: AcceptedLifecyclePermit
    task_dependency: TaskDependencyRef | None


class ProviderExecutionBindingStore:
    """Persist provider-effect identity without persisting request payload bytes.

    The store preserves enough metadata to recognize and safely rehydrate the
    same request after restart if the caller can re-supply the payload. It does
    not persist provider credentials, verifier secrets, or arbitrary payload
    content that may itself contain secrets.
    """

    SCHEMA = "VERA_MONO_PROVIDER_EXECUTION_BINDING_V2"
    LEGACY_SCHEMA = "VERA_MONO_PROVIDER_EXECUTION_BINDING_V1"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS provider_execution_bindings (
                    effect_id TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    @classmethod
    def _payload(
        cls,
        prepared: PreparedProviderDispatch,
    ) -> dict[str, Any]:
        if type(prepared) is not PreparedProviderDispatch:
            raise ProviderExecutionBindingError(
                "prepared must be exact PreparedProviderDispatch"
            )
        return {
            "schema": cls.SCHEMA,
            "effect_id": prepared.effect_id,
            "provider_id": prepared.provider_id,
            "operation": prepared.operation,
            "request_digest": prepared.request_digest,
            "authority_subject": prepared.authority_subject,
            "permit": {
                **prepared.permit.canonical_body(),
                "permit_digest": prepared.permit.permit_digest,
            },
            "request_payload_persisted": False,
            "task_dependency": (
                None
                if prepared.task_dependency is None
                else prepared.task_dependency.canonical_body()
            ),
        }

    def bind(
        self,
        prepared: PreparedProviderDispatch,
    ) -> ProviderExecutionBinding:
        payload = self._payload(prepared)
        payload_json = _exact_json(payload)
        digest = sha256_hex(payload_json.encode("utf-8"))
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT * FROM provider_execution_bindings
                WHERE effect_id=?
                """,
                (prepared.effect_id,),
            ).fetchone()
            if row is not None:
                if (
                    str(row["binding_digest"]) != digest
                    or str(row["payload_json"]) != payload_json
                ):
                    raise ProviderExecutionBindingError(
                        "provider effect identity already binds different request metadata"
                    )
                db.commit()
                return self._decode(
                    str(row["binding_digest"]),
                    str(row["payload_json"]),
                )
            db.execute(
                """
                INSERT INTO provider_execution_bindings(
                    effect_id,binding_digest,payload_json
                ) VALUES(?,?,?)
                """,
                (
                    prepared.effect_id,
                    digest,
                    payload_json,
                ),
            )
            db.commit()
        return ProviderExecutionBinding(
            binding_digest=digest,
            effect_id=prepared.effect_id,
            provider_id=prepared.provider_id,
            operation=prepared.operation,
            request_digest=prepared.request_digest,
            authority_subject=prepared.authority_subject,
            permit=prepared.permit,
            task_dependency=prepared.task_dependency,
        )

    def read(self, effect_id: str) -> ProviderExecutionBinding:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """
                SELECT * FROM provider_execution_bindings
                WHERE effect_id=?
                """,
                (effect_id,),
            ).fetchone()
        if row is None:
            raise KeyError(effect_id)
        return self._decode(
            str(row["binding_digest"]),
            str(row["payload_json"]),
        )

    def all(self) -> tuple[ProviderExecutionBinding, ...]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT * FROM provider_execution_bindings
                ORDER BY effect_id
                """
            ).fetchall()
        return tuple(
            self._decode(
                str(row["binding_digest"]),
                str(row["payload_json"]),
            )
            for row in rows
        )

    def context(self) -> dict[str, Any]:
        bindings = self.all()
        return {
            "schema": "VERA_MONO_PROVIDER_EXECUTION_BINDING_CONTEXT_V1",
            "binding_count": len(bindings),
            "bindings": [
                {
                    "binding_digest": binding.binding_digest,
                    "effect_id": binding.effect_id,
                    "provider_id": binding.provider_id,
                    "operation": binding.operation,
                    "request_digest": binding.request_digest,
                    "authority_subject": binding.authority_subject,
                    "lifecycle_permit_digest": binding.permit.permit_digest,
                    "request_payload_persisted": False,
                    "task_dependency": (
                        None
                        if binding.task_dependency is None
                        else binding.task_dependency.canonical_body()
                    ),
                }
                for binding in bindings
            ],
        }

    @classmethod
    def _decode(
        cls,
        binding_digest: str,
        payload_json: str,
    ) -> ProviderExecutionBinding:
        if sha256_hex(payload_json.encode("utf-8")) != binding_digest:
            raise ProviderExecutionBindingError(
                "provider execution binding digest mismatch"
            )
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise ProviderExecutionBindingError(
                "provider execution binding is not valid JSON"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema") not in {cls.SCHEMA, cls.LEGACY_SCHEMA}
            or payload.get("request_payload_persisted") is not False
        ):
            raise ProviderExecutionBindingError(
                "unsupported provider execution binding schema"
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
            raise ProviderExecutionBindingError(
                "stored provider lifecycle permit digest mismatch"
            )
        subject = provider_authority_subject(
            effect_id=payload["effect_id"],
            provider_id=payload["provider_id"],
            operation=payload["operation"],
            request_digest=payload["request_digest"],
            lifecycle_permit_digest=permit.permit_digest,
        )
        if subject != payload["authority_subject"]:
            raise ProviderExecutionBindingError(
                "stored provider authority subject mismatch"
            )
        raw_task_dependency = payload.get("task_dependency")
        task_dependency = None
        if raw_task_dependency is not None:
            if not isinstance(raw_task_dependency, dict):
                raise ProviderExecutionBindingError(
                    "stored provider task dependency must be an object"
                )
            try:
                task_dependency = TaskDependencyRef(
                    task_id=str(raw_task_dependency["task_id"]),
                    dependency_id=str(raw_task_dependency["dependency_id"]),
                    kind=str(raw_task_dependency["kind"]),
                    target_id=str(raw_task_dependency["target_id"]),
                    binding_event_digest=str(
                        raw_task_dependency["binding_event_digest"]
                    ),
                )
            except KeyError as exc:
                raise ProviderExecutionBindingError(
                    "stored provider task dependency is incomplete"
                ) from exc
            if (
                task_dependency.kind != "PROVIDER_EFFECT"
                or task_dependency.target_id != payload["effect_id"]
                or len(task_dependency.binding_event_digest) != 64
            ):
                raise ProviderExecutionBindingError(
                    "stored provider task dependency binding mismatch"
                )
        expected_payload = {
            "schema": payload["schema"],
            "effect_id": payload["effect_id"],
            "provider_id": payload["provider_id"],
            "operation": payload["operation"],
            "request_digest": payload["request_digest"],
            "authority_subject": subject,
            "permit": {
                **permit.canonical_body(),
                "permit_digest": permit.permit_digest,
            },
            "request_payload_persisted": False,
        }
        if payload["schema"] == cls.SCHEMA:
            expected_payload["task_dependency"] = (
                None
                if task_dependency is None
                else task_dependency.canonical_body()
            )
        if _exact_json(expected_payload) != payload_json:
            raise ProviderExecutionBindingError(
                "provider execution binding canonical readback mismatch"
            )
        return ProviderExecutionBinding(
            binding_digest=binding_digest,
            effect_id=payload["effect_id"],
            provider_id=payload["provider_id"],
            operation=payload["operation"],
            request_digest=payload["request_digest"],
            authority_subject=subject,
            permit=permit,
            task_dependency=task_dependency,
        )
