"""Host-owned, public-only memory approval broker for local Mini-Vera.

This is an *in-process Python API*, not a CLI approval switch.  The trusted
host supplies an already-open MemoryLedger, an independently checked grant
reader, a per-record policy callback, and an integrity key.  An untrusted
model, a stored PUBLIC label, or a self-authored JSON file cannot grant access.

The broker does not admit, modify, migrate, discover, or persist memories.
It deliberately does not claim to authenticate the host or pin Vera's identity
resources: those are separate external controls.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import hmac
import time
from typing import TYPE_CHECKING, Any

from .compose import CompositionRejected, ID, MAX_RECORDS, canonical
from .live_ledger import approved_ledger_provider

if TYPE_CHECKING:
    from vera_memory import MemoryLedger, MemoryRecord


@dataclass(frozen=True, slots=True)
class PublicMemoryGrant:
    """A current host-issued decision, not a self-authenticating capability.

    The host must advance ``approval_epoch`` on revocation or policy changes,
    anchor ``ledger_head`` and ``revision`` outside the ledger being read,
    and issue a new bounded grant after any genuine change of selected memory.
    ``None`` from the host reader means revoked or unavailable.
    """

    project_id: str
    identity_id: str
    ledger_head: str
    revision: int
    record_ids: tuple[str, ...]
    approval_epoch: int
    expires_at_unix: int


def _grant_binding(grant: PublicMemoryGrant) -> bytes:
    """Immutable snapshot, never an equality check against a mutable object."""
    return canonical({
        "schema": "MINI_VERA_HOST_GRANT_BINDING_V1",
        "project_id": grant.project_id, "identity_id": grant.identity_id,
        "ledger_head": grant.ledger_head, "revision": grant.revision,
        "record_ids": list(grant.record_ids), "approval_epoch": grant.approval_epoch,
        "expires_at_unix": grant.expires_at_unix,
    })


def bind_host_public_memory(
    ledger: "MemoryLedger", *,
    integrity_key: bytes,
    current_grant: Callable[[], PublicMemoryGrant | None],
    approve_record: Callable[["MemoryRecord", PublicMemoryGrant], bool],
    now_seconds: Callable[[], float] = time.time,
) -> Callable[[], tuple[dict[str, Any], bytes, int]]:
    """Create a callable suitable for ``local_session.main``'s provider.

    Callbacks are *trusted host dependencies*, not user/model arguments.  The
    provider obtains a fresh grant twice during each projection, refuses drift
    or revocation even before inference, and delegates actual record filtering
    and CAS checks to the existing ledger projection.  The local-session caller
    must still recheck the returned provider **after** inference; it does so in
    PR #201.  No active model inference is attempted by this function.
    """
    if not callable(current_grant) or not callable(approve_record) or not callable(now_seconds):
        raise CompositionRejected("trusted host grant, record policy and clock required")
    if type(integrity_key) is not bytes or len(integrity_key) != 32:
        raise CompositionRejected("host integrity key must be 32 bytes")

    def checked_grant() -> PublicMemoryGrant:
        try:
            grant = current_grant()
            current_time = now_seconds()
        except Exception as exc:
            raise CompositionRejected("host public-memory authority unavailable") from exc
        if grant is None:
            raise CompositionRejected("host public-memory grant revoked or unavailable")
        if type(grant) is not PublicMemoryGrant:
            raise CompositionRejected("invalid host public-memory grant type")
        # Frozen dataclass is only shallowly frozen: a list of IDs could be
        # mutated by the policy callback while comparing equal to itself.
        # All grant fields must be exact immutable primitives/tuples.
        if (type(grant.project_id) is not str or type(grant.identity_id) is not str
                or type(grant.ledger_head) is not str or type(grant.revision) is not int
                or type(grant.record_ids) is not tuple):
            raise CompositionRejected("host public-memory grant fields must be immutable and exact")
        if (len(grant.record_ids) > MAX_RECORDS
                or any(type(record_id) is not str or ID.fullmatch(record_id) is None
                       for record_id in grant.record_ids)
                or len(set(grant.record_ids)) != len(grant.record_ids)):
            raise CompositionRejected("invalid host public-memory record selection")
        if grant.project_id != ledger.project_id or grant.identity_id != ledger.identity_id:
            raise CompositionRejected("host public-memory grant scope mismatch")
        if type(grant.approval_epoch) is not int or not (0 <= grant.approval_epoch < 2**64):
            raise CompositionRejected("invalid host approval epoch")
        if type(grant.expires_at_unix) is not int or type(current_time) not in (int, float):
            raise CompositionRejected("invalid host grant expiry or clock")
        # Limit lifetime to one hour; an authorized host can rotate leases.
        if not (0 < grant.expires_at_unix - current_time <= 3600):
            raise CompositionRejected("host public-memory grant expired or invalid")
        return grant

    def resolve() -> tuple[dict[str, Any], bytes, int]:
        grant = checked_grant()
        # The existing session's post-inference check compares the state SHA.
        # Re-signing with a grant-scoped key means revocation/regrant with an
        # otherwise identical record set still changes that SHA.  The host MUST
        # advance approval_epoch for any intervening policy revocation/change.
        grant_binding = _grant_binding(grant)
        epoch_key = hmac.new(integrity_key, b"mini-vera-host-grant-v1\x00" + grant_binding,
                             hashlib.sha256).digest()

        def policy(record: "MemoryRecord", _head: str) -> bool:
            try:
                return approve_record(record, grant) is True
            except Exception as exc:
                raise CompositionRejected("host public-memory record policy unavailable") from exc

        provider = approved_ledger_provider(
            ledger, record_ids=grant.record_ids,
            expected_head=grant.ledger_head, expected_revision=grant.revision,
            integrity_key=epoch_key, host_public_project_approval=policy,
        )
        state, key, revision = provider()
        # Compare the before/after *serialized values* even when the trusted
        # host returns the same object on both reads. Equality against the
        # same dataclass instance cannot detect in-place object mutation.
        after_grant = checked_grant()
        if _grant_binding(after_grant) != grant_binding:
            raise CompositionRejected("host public-memory grant changed during projection")
        return state, key, revision

    return resolve
