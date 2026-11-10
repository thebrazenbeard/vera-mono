"""Experimental, effectless MemoryLedger -> Mini-Vera context projection.

The caller must supply an existing ledger, an externally anchored CAS head and
revision, and a real host policy decision for *each* selected record.  Neither
the ledger's stored privacy/authority strings nor this callback's existence
proves that a host has made an appropriate authorization decision.  No memory
is admitted or changed here; the resulting HMAC is integrity, not authority.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from .compose import CompositionRejected, ID, MAX_RECORDS, MAX_RECORD_BYTES, canonical, sha256

if TYPE_CHECKING:
    from vera_memory import MemoryLedger, MemoryRecord


def project_existing_ledger(
    ledger: "MemoryLedger", *, record_ids: Sequence[str],
    expected_head: str, expected_revision: int, integrity_key: bytes,
    host_public_project_approval: Callable[["MemoryRecord", str], bool],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Export selected current records without elevating stored metadata.

    Returns a composer-compatible HMAC state and a non-model-facing source
    receipt. The host must separately verify actual policy/source authority,
    externally anchored revision, privacy and snapshot freshness.
    """
    if type(integrity_key) is not bytes or len(integrity_key) != 32:
        raise CompositionRejected("integrity key must be 32 bytes")
    if type(expected_revision) is not int or expected_revision < 0:
        raise CompositionRejected("invalid external expected revision")
    if type(expected_head) is not str or len(expected_head) != 64 or any(c not in "0123456789abcdef" for c in expected_head):
        raise CompositionRejected("invalid expected ledger CAS head")
    if not callable(host_public_project_approval):
        raise CompositionRejected("explicit host policy callback required")
    if type(record_ids) not in (tuple, list) or len(record_ids) > MAX_RECORDS:
        raise CompositionRejected("invalid selected record set")
    if any(type(i) is not str or ID.fullmatch(i) is None for i in record_ids) or len(set(record_ids)) != len(record_ids):
        raise CompositionRejected("invalid or repeated selected record ID")
    if ledger.current_head != expected_head:
        raise CompositionRejected("ledger CAS head drift before projection")

    records: list[dict[str, str]] = []
    digest_refs: list[dict[str, str]] = []
    # IDs are caller-selected, never an unbounded automatic memory search.
    for record_id in record_ids:
        try:
            record = ledger.read(record_id, expected_head=expected_head)
        except KeyError as exc:
            raise CompositionRejected("selected record missing from ledger") from exc
        if record.status != "CURRENT" or record.memory_class.value != "WORKING_PROJECT":
            raise CompositionRejected("superseded or non-project memory rejected")
        # A callback alone could accidentally bless a stored PRIVATE ref.
        # The metadata check is necessary, not sufficient authorization.
        if record.privacy_ref != "PUBLIC":
            raise CompositionRejected("stored privacy class is not PUBLIC")
        if record.project_id != ledger.project_id or record.governed_identity_id != ledger.identity_id:
            raise CompositionRejected("record project/identity mismatch")
        if not record.provenance_refs:
            raise CompositionRejected("memory lacks provenance reference")
        if not record.text.strip() or len(record.text.encode("utf-8")) > MAX_RECORD_BYTES:
            raise CompositionRejected("memory text empty or too large for projection")
        # The callback must check *more* than the stored privacy_ref label.
        if host_public_project_approval(record, expected_head) is not True:
            raise CompositionRejected("host rejected public project projection")
        records.append({
            "record_id": record_id, "record_class": "WORKING_PROJECT",
            "privacy": "PUBLIC", "instruction_trust": "DATA_NOT_INSTRUCTION",
            "authority_effect": "NONE", "source_sha256": sha256(record.text.encode("utf-8")),
            "text": record.text,
        })
        digest_refs.append({"record_id": record_id, "ledger_record_digest": record.record_digest})
    if ledger.current_head != expected_head:
        raise CompositionRejected("ledger CAS head drift after projection")
    unsigned = {
        "schema": "MINI_VERA_OPERATOR_STATE_V1", "revision": expected_revision,
        "source_id": "ledger:" + expected_head, "records": records,
    }
    state = {**unsigned, "hmac_sha256": hmac.new(integrity_key, canonical(unsigned), hashlib.sha256).hexdigest()}
    receipt = {
        "schema": "MINI_VERA_LEDGER_PROJECTION_RECEIPT_V1",
        "evidence": "SOURCE_PROJECTION_ONLY_NOT_PRIVACY_OR_HOST_ATTESTATION",
        "ledger_head": expected_head, "externally_declared_revision": expected_revision,
        "revision_authority": "DECLARED_NOT_VERIFIED",
        "record_digests": digest_refs, "state_sha256": sha256(canonical(state)),
        "writes": 0, "model_calls": 0, "authority_effect": "NONE",
    }
    return state, receipt
