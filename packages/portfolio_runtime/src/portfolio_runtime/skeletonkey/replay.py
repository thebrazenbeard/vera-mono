"""Content-bound manifests for reproducible deterministic derivations."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class ReplayMismatchError(ValueError):
    """Raised when identical derivation inputs reproduce different bytes."""


_CONTENT_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_json(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("parameters must be finite canonical JSON values") from exc
    return encoded.encode("utf-8")


@dataclass(frozen=True)
class DerivationManifest:
    evidence_class: str
    derivation_id: str
    parent_content_ids: tuple[str, ...]
    procedure_id: str
    procedure_version: str
    parameter_digest: str
    output_content_id: str


def build_derivation_manifest(
    *,
    parent_content_ids: tuple[str, ...],
    procedure_id: str,
    procedure_version: str,
    parameters: Mapping[str, Any],
    output: bytes,
) -> DerivationManifest:
    if not parent_content_ids or not all(
        _CONTENT_ID_PATTERN.fullmatch(content_id)
        for content_id in parent_content_ids
    ):
        raise ValueError("parent_content_ids must contain lowercase sha256 identifiers")
    if not procedure_id or not procedure_version:
        raise ValueError("procedure_id and procedure_version are required")
    if not isinstance(output, bytes):
        raise TypeError("derived output must be bytes")

    parameter_digest = _digest(_canonical_json(parameters))
    identity_payload = {
        "parameter_digest": parameter_digest,
        "parent_content_ids": list(parent_content_ids),
        "procedure_id": procedure_id,
        "procedure_version": procedure_version,
    }
    return DerivationManifest(
        evidence_class="DERIVED",
        derivation_id=_digest(_canonical_json(identity_payload)),
        parent_content_ids=parent_content_ids,
        procedure_id=procedure_id,
        procedure_version=procedure_version,
        parameter_digest=parameter_digest,
        output_content_id=_digest(output),
    )


def assert_replay_match(
    original: DerivationManifest,
    replayed: DerivationManifest,
) -> None:
    if original.derivation_id != replayed.derivation_id:
        raise ValueError("cannot compare outputs from different derivations")
    if original.output_content_id != replayed.output_content_id:
        raise ReplayMismatchError(
            f"replay output differs for {original.derivation_id}"
        )

