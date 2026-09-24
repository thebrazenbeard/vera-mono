from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any, Mapping, TYPE_CHECKING

from portfolio_runtime.lantern.canonical import sha256_hex

from .provider_execution_binding import ProviderExecutionBinding

if TYPE_CHECKING:
    from .source_mutation import PreparedSourceMutation


class SourceMutationBindingError(ValueError):
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
class SourceMutationBinding:
    binding_digest: str
    mutation_id: str
    task_id: str
    dependency_id: str
    packet_digest: str
    repository: str
    ref: str
    subject: str
    actor_ref: str
    operation: str
    path: str
    destination_path: str | None
    expected_ref_head: str
    expected_blob_id: str
    expected_destination_blob_id: str | None
    content_digest: str | None
    writable_scope_entries: tuple[str, ...]
    delegation_ref: Mapping[str, str] | None
    provider_binding_digest: str
    provider_effect_id: str
    provider_id: str
    provider_operation: str
    provider_request_digest: str
    lifecycle_permit_digest: str


class SourceMutationBindingStore:
    """Durable nonsecret evidence for prepared qualified source mutations.

    Source bytes are deliberately not persisted. The provider request digest
    commits to the full request (including content), while content_digest allows
    a restart path to verify caller-resupplied WRITE_FILE bytes before reuse.
    """

    SCHEMA = "VERA_MONO_SOURCE_MUTATION_BINDING_V1"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS source_mutation_bindings (
                    mutation_id TEXT PRIMARY KEY,
                    binding_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    @classmethod
    def _payload(
        cls,
        prepared: "PreparedSourceMutation",
        provider_binding: ProviderExecutionBinding,
    ) -> dict[str, Any]:
        from .source_mutation import PreparedSourceMutation

        if type(prepared) is not PreparedSourceMutation:
            raise SourceMutationBindingError(
                "prepared must be exact PreparedSourceMutation"
            )
        if type(provider_binding) is not ProviderExecutionBinding:
            raise SourceMutationBindingError(
                "provider_binding must be exact ProviderExecutionBinding"
            )
        request = prepared.request
        dispatch = prepared.provider_dispatch
        if provider_binding.effect_id != request.mutation_id:
            raise SourceMutationBindingError(
                "provider binding effect id does not match source mutation"
            )
        if dispatch.effect_id != request.mutation_id:
            raise SourceMutationBindingError(
                "prepared provider effect id does not match source mutation"
            )
        if provider_binding.binding_digest == "":
            raise SourceMutationBindingError(
                "provider binding digest must be non-empty"
            )
        if (
            provider_binding.provider_id != dispatch.provider_id
            or provider_binding.operation != dispatch.operation
            or provider_binding.request_digest != dispatch.request_digest
            or provider_binding.authority_subject != dispatch.authority_subject
            or provider_binding.permit.permit_digest
            != dispatch.permit.permit_digest
        ):
            raise SourceMutationBindingError(
                "provider binding diverges from prepared source mutation"
            )
        return {
            "schema": cls.SCHEMA,
            "mutation_id": request.mutation_id,
            "task_id": prepared.task_id,
            "dependency_id": prepared.dependency_id,
            "packet_digest": prepared.packet_digest,
            "request": {
                "repository": request.repository,
                "ref": request.ref,
                "subject": request.subject,
                "actor_ref": request.actor_ref,
                "operation": request.operation,
                "path": request.normalized_path,
                "destination_path": request.normalized_destination_path,
                "expected_ref_head": request.expected_ref_head,
                "expected_blob_id": request.expected_blob_id,
                "expected_destination_blob_id": (
                    request.expected_destination_blob_id
                ),
                "content_digest": request.content_digest,
                "content_persisted": False,
            },
            "writable_scope_entries": list(
                prepared.writable_scope_entries
            ),
            "delegation_ref": (
                None
                if prepared.delegation_ref is None
                else prepared.delegation_ref.canonical_body()
            ),
            "provider": {
                "binding_digest": provider_binding.binding_digest,
                "effect_id": provider_binding.effect_id,
                "provider_id": provider_binding.provider_id,
                "operation": provider_binding.operation,
                "request_digest": provider_binding.request_digest,
                "authority_subject": provider_binding.authority_subject,
                "lifecycle_permit_digest": (
                    provider_binding.permit.permit_digest
                ),
                "task_dependency": (
                    None
                    if provider_binding.task_dependency is None
                    else provider_binding.task_dependency.canonical_body()
                ),
            },
        }

    def bind(
        self,
        prepared: "PreparedSourceMutation",
        provider_binding: ProviderExecutionBinding,
    ) -> SourceMutationBinding:
        payload = self._payload(prepared, provider_binding)
        payload_json = _exact_json(payload)
        digest = sha256_hex(payload_json.encode("utf-8"))
        mutation_id = str(payload["mutation_id"])
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT * FROM source_mutation_bindings
                WHERE mutation_id=?
                """,
                (mutation_id,),
            ).fetchone()
            if row is not None:
                if (
                    str(row["binding_digest"]) != digest
                    or str(row["payload_json"]) != payload_json
                ):
                    raise SourceMutationBindingError(
                        "source mutation id already binds different restart evidence"
                    )
                db.commit()
                return self._decode(
                    str(row["binding_digest"]),
                    str(row["payload_json"]),
                )
            db.execute(
                """
                INSERT INTO source_mutation_bindings(
                    mutation_id,binding_digest,payload_json
                ) VALUES(?,?,?)
                """,
                (mutation_id, digest, payload_json),
            )
            db.commit()
        return self._decode(digest, payload_json)

    def read(self, mutation_id: str) -> SourceMutationBinding:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """
                SELECT * FROM source_mutation_bindings
                WHERE mutation_id=?
                """,
                (mutation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(mutation_id)
        return self._decode(
            str(row["binding_digest"]),
            str(row["payload_json"]),
        )

    def all(self) -> tuple[SourceMutationBinding, ...]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT * FROM source_mutation_bindings
                ORDER BY mutation_id
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
            "schema": "VERA_MONO_SOURCE_MUTATION_BINDING_CONTEXT_V1",
            "binding_count": len(bindings),
            "bindings": [
                {
                    "binding_digest": item.binding_digest,
                    "mutation_id": item.mutation_id,
                    "task_id": item.task_id,
                    "dependency_id": item.dependency_id,
                    "repository": item.repository,
                    "ref": item.ref,
                    "subject": item.subject,
                    "actor_ref": item.actor_ref,
                    "operation": item.operation,
                    "path": item.path,
                    "destination_path": item.destination_path,
                    "expected_ref_head": item.expected_ref_head,
                    "expected_blob_id": item.expected_blob_id,
                    "expected_destination_blob_id": (
                        item.expected_destination_blob_id
                    ),
                    "content_digest": item.content_digest,
                    "content_persisted": False,
                    "writable_scope_entries": list(
                        item.writable_scope_entries
                    ),
                    "delegation_ref": (
                        None
                        if item.delegation_ref is None
                        else dict(item.delegation_ref)
                    ),
                    "provider_binding_digest": (
                        item.provider_binding_digest
                    ),
                    "provider_effect_id": item.provider_effect_id,
                    "provider_id": item.provider_id,
                    "provider_operation": item.provider_operation,
                    "provider_request_digest": (
                        item.provider_request_digest
                    ),
                    "lifecycle_permit_digest": (
                        item.lifecycle_permit_digest
                    ),
                }
                for item in bindings
            ],
        }

    @classmethod
    def _decode(
        cls,
        binding_digest: str,
        payload_json: str,
    ) -> SourceMutationBinding:
        if sha256_hex(payload_json.encode("utf-8")) != binding_digest:
            raise SourceMutationBindingError(
                "source mutation binding digest mismatch"
            )
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise SourceMutationBindingError(
                "source mutation binding is not valid JSON"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != cls.SCHEMA
        ):
            raise SourceMutationBindingError(
                "unsupported source mutation binding schema"
            )
        request = payload.get("request")
        provider = payload.get("provider")
        if not isinstance(request, dict) or not isinstance(provider, dict):
            raise SourceMutationBindingError(
                "source mutation binding sections are missing"
            )
        if request.get("content_persisted") is not False:
            raise SourceMutationBindingError(
                "source mutation binding must not persist content bytes"
            )
        delegation_ref = payload.get("delegation_ref")
        if delegation_ref is not None:
            if not isinstance(delegation_ref, dict):
                raise SourceMutationBindingError(
                    "source mutation delegation ref must be an object"
                )
            required_delegation = {
                "task_id",
                "delegation_id",
                "repository",
                "ref",
                "subject",
                "assignee_ref",
                "binding_event_digest",
            }
            if set(delegation_ref) != required_delegation:
                raise SourceMutationBindingError(
                    "source mutation delegation ref field set mismatch"
                )
        scopes = payload.get("writable_scope_entries")
        if (
            not isinstance(scopes, list)
            or not all(type(item) is str and item for item in scopes)
        ):
            raise SourceMutationBindingError(
                "source mutation writable scope evidence is invalid"
            )
        required_request = {
            "repository",
            "ref",
            "subject",
            "actor_ref",
            "operation",
            "path",
            "destination_path",
            "expected_ref_head",
            "expected_blob_id",
            "expected_destination_blob_id",
            "content_digest",
            "content_persisted",
        }
        if set(request) != required_request:
            raise SourceMutationBindingError(
                "source mutation request evidence field set mismatch"
            )
        required_provider = {
            "binding_digest",
            "effect_id",
            "provider_id",
            "operation",
            "request_digest",
            "authority_subject",
            "lifecycle_permit_digest",
            "task_dependency",
        }
        if set(provider) != required_provider:
            raise SourceMutationBindingError(
                "source mutation provider evidence field set mismatch"
            )
        if provider["effect_id"] != payload["mutation_id"]:
            raise SourceMutationBindingError(
                "source mutation provider effect identity mismatch"
            )
        if provider["task_dependency"] is not None:
            dependency = provider["task_dependency"]
            if (
                not isinstance(dependency, dict)
                or dependency.get("task_id") != payload["task_id"]
                or dependency.get("dependency_id")
                != payload["dependency_id"]
                or dependency.get("kind") != "PROVIDER_EFFECT"
                or dependency.get("target_id") != payload["mutation_id"]
            ):
                raise SourceMutationBindingError(
                    "source mutation task dependency evidence mismatch"
                )

        expected_payload = {
            "schema": cls.SCHEMA,
            "mutation_id": payload["mutation_id"],
            "task_id": payload["task_id"],
            "dependency_id": payload["dependency_id"],
            "packet_digest": payload["packet_digest"],
            "request": request,
            "writable_scope_entries": scopes,
            "delegation_ref": delegation_ref,
            "provider": provider,
        }
        if _exact_json(expected_payload) != payload_json:
            raise SourceMutationBindingError(
                "source mutation binding canonical readback mismatch"
            )
        return SourceMutationBinding(
            binding_digest=binding_digest,
            mutation_id=str(payload["mutation_id"]),
            task_id=str(payload["task_id"]),
            dependency_id=str(payload["dependency_id"]),
            packet_digest=str(payload["packet_digest"]),
            repository=str(request["repository"]),
            ref=str(request["ref"]),
            subject=str(request["subject"]),
            actor_ref=str(request["actor_ref"]),
            operation=str(request["operation"]),
            path=str(request["path"]),
            destination_path=request["destination_path"],
            expected_ref_head=str(request["expected_ref_head"]),
            expected_blob_id=str(request["expected_blob_id"]),
            expected_destination_blob_id=(
                request["expected_destination_blob_id"]
            ),
            content_digest=request["content_digest"],
            writable_scope_entries=tuple(scopes),
            delegation_ref=delegation_ref,
            provider_binding_digest=str(provider["binding_digest"]),
            provider_effect_id=str(provider["effect_id"]),
            provider_id=str(provider["provider_id"]),
            provider_operation=str(provider["operation"]),
            provider_request_digest=str(provider["request_digest"]),
            lifecycle_permit_digest=str(
                provider["lifecycle_permit_digest"]
            ),
        )
