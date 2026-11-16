"""Host-embedded exact-ID public-record source reader; NEVER an approval issuer.

A separately trusted host must supply a fresh callable from its governed
public-memory broker. No CLI, file key, self-declared public label, model
request, memory admission or writes. This module cannot attest host issuer
identity or the quality of its external grants/revision floor.
"""

from __future__ import annotations

from collections.abc import Callable
import hmac
import json
from typing import Any

from . import compose


class HostSourceRefused(compose.CompositionRejected):
    """A public source cannot be released to the host caller safely."""


def read_public_record(provider: Callable[[], tuple[dict[str, Any], bytes, int]], *,
                       record_id: str) -> dict[str, Any]:
    """Return one host-approved PUBLIC statement by exact ID, never model prose.

    Re-observe the broker and check the entire approved projection immediately
    before returning; this cannot eliminate changes after that second check.
    A caller must not install this on a model-controlled interface or use an
    untrusted provider as its own host issuer.
    """
    if (not callable(provider) or type(record_id) is not str
            or compose.ID.fullmatch(record_id) is None):
        raise HostSourceRefused("explicit host provider and exact record ID required")

    def read_snapshot() -> tuple[dict[str, Any], bytes, int, list[dict[str, str]], str, bytes, str]:
        try:
            binding = provider()
            if type(binding) is not tuple or len(binding) != 3:
                raise HostSourceRefused("invalid host binding")
            state, key, revision = binding
            records, state_sha = compose.verify_state(
                state, key=key, expected_revision=revision)
            if type(state["source_id"]) is not str:
                raise HostSourceRefused("invalid source")
            # Never keep the provider's mutable dict for a post-check comparison.
            immutable_source = compose.canonical(state)
            if compose.sha256(immutable_source) != state_sha:
                raise HostSourceRefused('host source changed during snapshot')
            # Bind attribution to immutable verified bytes. A host-owned
            # state dict can change after the final equality checks.
            source_id = json.loads(immutable_source)['source_id']
            return state, key, revision, records, state_sha, immutable_source, source_id
        except Exception:
            # Host policy and ledger exceptions can carry private record text.
            raise HostSourceRefused("host public-source approval unavailable") from None

    _before_state, before_key, before_revision, before_records, before_sha, before_bytes, _ = read_snapshot()
    record = next((row for row in before_records if row["record_id"] == record_id), None)

    _after_state, after_key, after_revision, after_records, after_sha, after_bytes, source_id = read_snapshot()
    if (after_revision != before_revision
            or not hmac.compare_digest(before_key, after_key)
            or not hmac.compare_digest(before_sha, after_sha)
            or not hmac.compare_digest(before_bytes, after_bytes)
            or after_records != before_records):
        raise HostSourceRefused("host public-source approval changed before release")
    if record is None:
        return {
            "schema": "MINI_VERA_HOST_PUBLIC_EXACT_READ_V1",
            "status": "UNKNOWN", "answer": "UNKNOWN", "source": None,
            "origin": "CLIENT_ABSENT_APPROVED_RECORD_NOT_NEURAL",
            "authority": "HOST_CALLBACK_TRUST_NOT_INDEPENDENTLY_ATTESTED",
            "host_issuer_qualified": False, "model_http_calls": 0, "writes": 0,
        }
    return {
        "schema": "MINI_VERA_HOST_PUBLIC_EXACT_READ_V1",
        "status": "SOURCE_READ", "answer": record["text"],
        "source": {
            "record_id": record_id,
            "source_id": source_id,
            "text_sha256": record["source_sha256"],
            "state_sha256": after_sha,
            "revision": after_revision,
            "record_trust": record["trust"],
        },
        "origin": "HOST_SUPPLIED_APPROVED_PUBLIC_SOURCE_NOT_NEURAL",
        "authority": "HOST_CALLBACK_TRUST_NOT_INDEPENDENTLY_ATTESTED",
        "host_issuer_qualified": False, "model_http_calls": 0, "writes": 0,
    }