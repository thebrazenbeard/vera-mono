from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
from typing import Any

from portfolio_runtime.lantern.canonical import sha256_hex

from .execution_adapters import SourceMutationTransportResult
from .source_mutation_binding import SourceMutationBinding


class SourceMutationOutcomeError(ValueError):
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
class SourceMutationOutcome:
    outcome_digest: str
    mutation_id: str
    source_binding_digest: str
    provider_binding_digest: str
    mechanical_effect_id: str
    effect_request_digest: str
    effect_result_digest: str
    repository: str
    ref: str
    operation: str
    path: str
    destination_path: str | None
    previous_ref_head: str
    new_ref_head: str
    result_id: str


class SourceMutationOutcomeStore:
    """Append-once durable source result required after effect COMMITTED.

    This closes the crash window between a provider effect reaching COMMITTED
    and Vera preserving the exact new source head/result identity needed for
    restart verification and task closeout.
    """

    SCHEMA = "VERA_MONO_SOURCE_MUTATION_OUTCOME_V1"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS source_mutation_outcomes (
                    mutation_id TEXT PRIMARY KEY,
                    outcome_digest TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _require_digest(value: str, label: str) -> str:
        if type(value) is not str or len(value) != 64:
            raise SourceMutationOutcomeError(
                f"{label} must be an exact SHA-256 digest"
            )
        try:
            int(value, 16)
        except ValueError as exc:
            raise SourceMutationOutcomeError(
                f"{label} must be hexadecimal"
            ) from exc
        return value.lower()

    @classmethod
    def _payload(
        cls,
        *,
        binding: SourceMutationBinding,
        transport_result: SourceMutationTransportResult,
        mechanical_effect_id: str,
        effect_request_digest: str,
        effect_result_digest: str,
    ) -> dict[str, Any]:
        if type(binding) is not SourceMutationBinding:
            raise SourceMutationOutcomeError(
                "binding must be exact SourceMutationBinding"
            )
        if type(transport_result) is not SourceMutationTransportResult:
            raise SourceMutationOutcomeError(
                "transport_result must be exact SourceMutationTransportResult"
            )
        if (
            transport_result.repository != binding.repository
            or transport_result.ref != binding.ref
            or transport_result.operation != binding.operation
            or transport_result.path != binding.path
            or transport_result.destination_path != binding.destination_path
            or transport_result.previous_ref_head != binding.expected_ref_head
        ):
            raise SourceMutationOutcomeError(
                "source transport outcome diverges from durable mutation binding"
            )
        if type(transport_result.new_ref_head) is not str or not transport_result.new_ref_head:
            raise SourceMutationOutcomeError(
                "source transport outcome lacks new_ref_head"
            )
        if type(transport_result.result_id) is not str or not transport_result.result_id:
            raise SourceMutationOutcomeError(
                "source transport outcome lacks result_id"
            )
        expected_effect_id = (
            f"provider:{binding.provider_id}:{binding.provider_effect_id}"
        )
        if mechanical_effect_id != expected_effect_id:
            raise SourceMutationOutcomeError(
                "source outcome mechanical effect identity mismatch"
            )
        effect_request_digest = cls._require_digest(
            effect_request_digest,
            "effect_request_digest",
        )
        effect_result_digest = cls._require_digest(
            effect_result_digest,
            "effect_result_digest",
        )
        return {
            "schema": cls.SCHEMA,
            "mutation_id": binding.mutation_id,
            "source_binding_digest": binding.binding_digest,
            "provider_binding_digest": binding.provider_binding_digest,
            "mechanical_effect_id": mechanical_effect_id,
            "effect_request_digest": effect_request_digest,
            "effect_result_digest": effect_result_digest,
            "repository": transport_result.repository,
            "ref": transport_result.ref,
            "operation": transport_result.operation,
            "path": transport_result.path,
            "destination_path": transport_result.destination_path,
            "previous_ref_head": transport_result.previous_ref_head,
            "new_ref_head": transport_result.new_ref_head,
            "result_id": transport_result.result_id,
        }

    def record(
        self,
        *,
        binding: SourceMutationBinding,
        transport_result: SourceMutationTransportResult,
        mechanical_effect_id: str,
        effect_request_digest: str,
        effect_result_digest: str,
    ) -> SourceMutationOutcome:
        payload = self._payload(
            binding=binding,
            transport_result=transport_result,
            mechanical_effect_id=mechanical_effect_id,
            effect_request_digest=effect_request_digest,
            effect_result_digest=effect_result_digest,
        )
        payload_json = _exact_json(payload)
        digest = sha256_hex(payload_json.encode("utf-8"))
        mutation_id = binding.mutation_id
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT * FROM source_mutation_outcomes
                WHERE mutation_id=?
                """,
                (mutation_id,),
            ).fetchone()
            if row is not None:
                if (
                    str(row["outcome_digest"]) != digest
                    or str(row["payload_json"]) != payload_json
                ):
                    raise SourceMutationOutcomeError(
                        "source mutation already has a different durable outcome"
                    )
                db.commit()
                return self._decode(
                    str(row["outcome_digest"]),
                    str(row["payload_json"]),
                )
            db.execute(
                """
                INSERT INTO source_mutation_outcomes(
                    mutation_id,outcome_digest,payload_json
                ) VALUES(?,?,?)
                """,
                (mutation_id, digest, payload_json),
            )
            db.commit()
        return self._decode(digest, payload_json)

    def read(self, mutation_id: str) -> SourceMutationOutcome:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """
                SELECT * FROM source_mutation_outcomes
                WHERE mutation_id=?
                """,
                (mutation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(mutation_id)
        return self._decode(
            str(row["outcome_digest"]),
            str(row["payload_json"]),
        )

    def all(self) -> tuple[SourceMutationOutcome, ...]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT * FROM source_mutation_outcomes
                ORDER BY mutation_id
                """
            ).fetchall()
        return tuple(
            self._decode(
                str(row["outcome_digest"]),
                str(row["payload_json"]),
            )
            for row in rows
        )

    def context(self) -> dict[str, Any]:
        outcomes = self.all()
        return {
            "schema": "VERA_MONO_SOURCE_MUTATION_OUTCOME_CONTEXT_V1",
            "outcome_count": len(outcomes),
            "outcomes": [
                {
                    "outcome_digest": item.outcome_digest,
                    "mutation_id": item.mutation_id,
                    "source_binding_digest": item.source_binding_digest,
                    "provider_binding_digest": item.provider_binding_digest,
                    "mechanical_effect_id": item.mechanical_effect_id,
                    "effect_request_digest": item.effect_request_digest,
                    "effect_result_digest": item.effect_result_digest,
                    "repository": item.repository,
                    "ref": item.ref,
                    "operation": item.operation,
                    "path": item.path,
                    "destination_path": item.destination_path,
                    "previous_ref_head": item.previous_ref_head,
                    "new_ref_head": item.new_ref_head,
                    "result_id": item.result_id,
                }
                for item in outcomes
            ],
        }

    @classmethod
    def _decode(
        cls,
        outcome_digest: str,
        payload_json: str,
    ) -> SourceMutationOutcome:
        if sha256_hex(payload_json.encode("utf-8")) != outcome_digest:
            raise SourceMutationOutcomeError(
                "source mutation outcome digest mismatch"
            )
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise SourceMutationOutcomeError(
                "source mutation outcome is not valid JSON"
            ) from exc
        required = {
            "schema",
            "mutation_id",
            "source_binding_digest",
            "provider_binding_digest",
            "mechanical_effect_id",
            "effect_request_digest",
            "effect_result_digest",
            "repository",
            "ref",
            "operation",
            "path",
            "destination_path",
            "previous_ref_head",
            "new_ref_head",
            "result_id",
        }
        if (
            not isinstance(payload, dict)
            or set(payload) != required
            or payload.get("schema") != cls.SCHEMA
        ):
            raise SourceMutationOutcomeError(
                "unsupported source mutation outcome schema"
            )
        for key in (
            "source_binding_digest",
            "provider_binding_digest",
            "effect_request_digest",
            "effect_result_digest",
        ):
            cls._require_digest(str(payload[key]), key)
        expected_json = _exact_json(
            {key: payload[key] for key in payload}
        )
        if expected_json != payload_json:
            raise SourceMutationOutcomeError(
                "source mutation outcome canonical readback mismatch"
            )
        return SourceMutationOutcome(
            outcome_digest=outcome_digest,
            mutation_id=str(payload["mutation_id"]),
            source_binding_digest=str(payload["source_binding_digest"]),
            provider_binding_digest=str(payload["provider_binding_digest"]),
            mechanical_effect_id=str(payload["mechanical_effect_id"]),
            effect_request_digest=str(payload["effect_request_digest"]),
            effect_result_digest=str(payload["effect_result_digest"]),
            repository=str(payload["repository"]),
            ref=str(payload["ref"]),
            operation=str(payload["operation"]),
            path=str(payload["path"]),
            destination_path=payload["destination_path"],
            previous_ref_head=str(payload["previous_ref_head"]),
            new_ref_head=str(payload["new_ref_head"]),
            result_id=str(payload["result_id"]),
        )
