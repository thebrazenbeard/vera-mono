"""Host-owned candidate seam: signed, single-use, untrusted reviewed memory.

This module is intentionally NOT callable from the production chat CLI. The
trusted_public_key_bytes input is only meaningful when a separately authenticated
host review broker provides it from an operator-owned trust registry. The
untrusted caller cannot make its own signer independently reviewed.

Signature evidence, local evidence-split records, CAS memory currentness, and
durable one-cue use are all necessary here; none grants tool effect authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from vera_memory import (
    DurableLearnedInfluenceGate, LearnedRevision, MemoryClass, MemoryLedger,
)

from .signed_review_attestation import (
    ReviewAttestationRejected, verify_signed_review_attestation,
)


@dataclass(frozen=True, slots=True)
class AttestedReviewedMemory:
    text: str
    record_id: str
    record_digest: str
    review_evidence_ref: str
    claim_ceiling: str = "UNTRUSTED_REVIEWED_MEMORY_DATA_NOT_EFFECT_AUTHORITY"
    authorization_effect: str = "NONE"


def _existing_bound_file(root: Path, candidate: Path) -> tuple[int, int, int]:
    """Reject file aliases that could bypass the approved state-root binding.

    This covers source-checkable symlink/junction/hardlink cases. It does not
    establish Windows ACL protection or defeat privileged directory replacement.
    """
    try:
        resolved_root = root.resolve(strict=True)
        relative = candidate.relative_to(root)
        path = root
        for part in relative.parts:
            path = path / part
            if path.is_symlink() or path.is_junction():
                raise ReviewAttestationRejected("reviewed database alias")
        if not candidate.is_file() or not candidate.resolve(strict=True).is_relative_to(resolved_root):
            raise ReviewAttestationRejected("reviewed database escapes state root")
        stat = candidate.stat()
    except (OSError, ValueError) as exc:
        raise ReviewAttestationRejected("reviewed database unavailable") from exc
    if stat.st_nlink != 1:
        raise ReviewAttestationRejected("reviewed database hardlink alias")
    return stat.st_dev, stat.st_ino, stat.st_size


def consume_attested_reviewed_memory(
    state,
    *,
    capsule_json: bytes,
    trusted_public_key_bytes: bytes,
    record_id: str,
    association_id: str,
    cue_event_id: str,
    use_evidence_id: str,
    now_unix: int,
) -> AttestedReviewedMemory:
    """Consume a signed and qualified current record exactly once as untrusted data.

    The caller MUST already be an authenticated host-owned broker. This
    function cannot authenticate the source of its trusted key parameter.
    """
    root = state.paths.root
    if not root.is_dir() or root.resolve(strict=True) != root:
        raise ReviewAttestationRejected("state root is not canonical")
    memory_identity = _existing_bound_file(root, state.paths.memory)
    memory = MemoryLedger(state.paths.memory, project_id=state.project_id,
                          identity_id=state.identity_id)
    expected_head = memory.current_head
    record = memory.read(record_id, expected_head=expected_head)
    if (record.status != "CURRENT" or record.superseded_by is not None or
            record.memory_class is not MemoryClass.WORKING_PROJECT or
            record.project_id != state.project_id or
            record.governed_identity_id != state.identity_id or
            not 0 < len(record.text) <= 1024):
        raise ReviewAttestationRejected("record is stale, private or out of scope")
    signature = verify_signed_review_attestation(
        capsule_json, trusted_public_key_bytes=trusted_public_key_bytes,
        expected_project_id=state.project_id,
        expected_identity_id=state.identity_id,
        expected_state_root_sha256=sha256(str(root).encode("utf-8")).hexdigest(),
        expected_record_id=record.record_id,
        expected_record_digest=record.record_digest,
        expected_memory_head=expected_head,
        expected_privacy_ref=record.privacy_ref,
        expected_association_id=association_id,
        expected_cue_event_id=cue_event_id,
        expected_use_evidence_id=use_evidence_id,
        now_unix=now_unix,
    )
    if _existing_bound_file(root, state.paths.memory) != memory_identity:
        raise ReviewAttestationRejected("memory file changed during review")
    gate_path = root / "learning" / "learned-influence.sqlite"
    if gate_path.exists():
        _existing_bound_file(root, gate_path)
    gate = DurableLearnedInfluenceGate(gate_path)
    gate_identity = _existing_bound_file(root, gate_path)
    receipt = gate.consume(
        LearnedRevision(association_id=association_id,
                        memory_revision_id=record.record_digest),
        cue_event_id=cue_event_id, use_evidence_id=use_evidence_id,
        require_qualified=True,
        expected_review_evidence_ref=signature.review_evidence_ref,
    )
    if (receipt.review_evidence_ref != signature.review_evidence_ref
            or not receipt.evidence_split_qualified):
        raise ReviewAttestationRejected("independent signed review reference mismatched the durable gate")
    if (memory.current_head != expected_head or
            _existing_bound_file(root, state.paths.memory) != memory_identity or
            _existing_bound_file(root, gate_path) != gate_identity):
        raise ReviewAttestationRejected("reviewed state changed before data consumption")
    return AttestedReviewedMemory(
        text=record.text, record_id=record.record_id,
        record_digest=record.record_digest,
        review_evidence_ref=signature.review_evidence_ref,
    )