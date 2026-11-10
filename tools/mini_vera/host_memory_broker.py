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
from copy import deepcopy
from dataclasses import astuple, dataclass
import hashlib
import hmac
from threading import Lock
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
    anchor ``ledger_head``, ``revision`` and selected ``record_digests``
    outside the ledger being read,
    and issue a new bounded grant after any genuine change of selected memory.
    The separate required ``current_authority_revision`` host reader must
    advance even when an issuer mistakenly reuses this grant's old epoch.
    ``None`` from the host reader means revoked or unavailable. A *separate*
    atomic host-persisted revision floor must survive broker/process restarts.
    """

    project_id: str
    identity_id: str
    ledger_head: str
    revision: int
    record_ids: tuple[str, ...]
    record_digests: tuple[tuple[str, str], ...]
    approval_epoch: int
    authority_revision: int
    expires_at_unix: int


def _grant_binding(grant: PublicMemoryGrant, authority_revision: int) -> bytes:
    """Immutable snapshot, never an equality check against a mutable object."""
    return canonical({
        "schema": "MINI_VERA_HOST_GRANT_BINDING_V3",
        "project_id": grant.project_id, "identity_id": grant.identity_id,
        "ledger_head": grant.ledger_head, "revision": grant.revision,
        "record_ids": list(grant.record_ids),
        "record_digests": [list(pair) for pair in grant.record_digests],
        "approval_epoch": grant.approval_epoch,
        "authority_revision": authority_revision,
        "expires_at_unix": grant.expires_at_unix,
    })


def bind_host_public_memory(
    ledger: "MemoryLedger", *,
    integrity_key: bytes,
    current_grant: Callable[[], PublicMemoryGrant | None],
    approve_record: Callable[["MemoryRecord", PublicMemoryGrant], bool],
    current_authority_revision: Callable[[], int] | None = None,
    atomic_host_revision_floor: Callable[[int], int] | None = None,
    now_seconds: Callable[[], float] = time.time,
) -> Callable[[], tuple[dict[str, Any], bytes, int]]:
    """Create a callable suitable for ``local_session.main``'s provider.

    Callbacks are *trusted host dependencies*, not user/model arguments.  The
    provider obtains a fresh grant and an independently maintained durable host
    authority revision twice during each projection. A distinct host-owned
    atomic floor callback MUST durably store max(previous_floor, supplied_revision)
    and return the resulting floor; the broker requires it to equal the current
    revision. Its persistence, authentication, and atomicity are trusted host
    obligations, not established by this source. The broker refuses drift or
    revocation even before inference and delegates actual record filtering
    and CAS checks to the existing ledger projection.  The local-session caller
    must still recheck the returned provider **after** inference; it does so in
    PR #201.  No active model inference is attempted by this function.
    """
    if not callable(current_grant) or not callable(approve_record) or not callable(now_seconds):
        raise CompositionRejected("trusted host grant, record policy and clock required")
    if not callable(current_authority_revision):
        raise CompositionRejected("host-owned monotonic authority revision reader required")
    if not callable(atomic_host_revision_floor):
        raise CompositionRejected("host-owned atomic durable authority floor required")
    if type(integrity_key) is not bytes or len(integrity_key) != 32:
        raise CompositionRejected("host integrity key must be 32 bytes")
    # The process-local check protects this instance.  The externally trusted
    # atomic floor is what must protect fresh processes and concurrent brokers.
    revision_lock = Lock()
    highest_observed_revision = -1

    def checked_grant() -> tuple[PublicMemoryGrant, int]:
        nonlocal highest_observed_revision
        # A revocation can legitimately return no grant. The newer authority
        # revision must still be durably observed, otherwise a fresh broker
        # after a host-state rollback can resurrect the old grant.
        try:
            authority_revision = current_authority_revision()
        except Exception as exc:
            raise CompositionRejected("host public-memory authority unavailable") from exc
        if (type(authority_revision) is not int
                or not (0 <= authority_revision < 2**64)):
            raise CompositionRejected("invalid host authority revision")
        with revision_lock:
            if authority_revision < highest_observed_revision:
                raise CompositionRejected("host authority revision rollback")
            try:
                durable_floor = atomic_host_revision_floor(authority_revision)
            except Exception as exc:
                raise CompositionRejected("host durable authority floor unavailable") from exc
            if type(durable_floor) is not int or not (0 <= durable_floor < 2**64):
                raise CompositionRejected("invalid host durable authority floor")
            if durable_floor > authority_revision:
                raise CompositionRejected("host authority revision rollback across broker restart")
            if durable_floor != authority_revision:
                raise CompositionRejected("host durable authority floor mismatch")
            highest_observed_revision = authority_revision
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
                or type(grant.record_ids) is not tuple or type(grant.record_digests) is not tuple):
            raise CompositionRejected("host public-memory grant fields must be immutable and exact")
        if (len(grant.record_ids) > MAX_RECORDS
                or any(type(record_id) is not str or ID.fullmatch(record_id) is None
                       for record_id in grant.record_ids)
                or len(set(grant.record_ids)) != len(grant.record_ids)):
            raise CompositionRejected("invalid host public-memory record selection")
        # The event head is necessary but not a sufficient content witness:
        # a mutable ledger row and its digest can both be rewritten without
        # advancing its metadata head. Pin each admitted row digest in the
        # independently issued host grant before reading any selected text.
        if (len(grant.record_digests) != len(grant.record_ids)
                or any(type(pair) is not tuple or len(pair) != 2
                       or type(pair[0]) is not str or pair[0] != selected_id
                       or type(pair[1]) is not str or len(pair[1]) != 64
                       or any(c not in "0123456789abcdef" for c in pair[1])
                       for pair, selected_id in zip(grant.record_digests, grant.record_ids))):
            raise CompositionRejected("invalid host public-memory record digest selection")
        if grant.project_id != ledger.project_id or grant.identity_id != ledger.identity_id:
            raise CompositionRejected("host public-memory grant scope mismatch")
        if type(grant.approval_epoch) is not int or not (0 <= grant.approval_epoch < 2**64):
            raise CompositionRejected("invalid host approval epoch")
        if (type(grant.authority_revision) is not int
                or not (0 <= grant.authority_revision < 2**64)):
            raise CompositionRejected("invalid issued host grant authority revision")
        if type(grant.expires_at_unix) is not int or type(current_time) not in (int, float):
            raise CompositionRejected("invalid host grant expiry or clock")
        # Limit lifetime to one hour; an authorized host can rotate leases.
        if not (0 < grant.expires_at_unix - current_time <= 3600):
            raise CompositionRejected("host public-memory grant expired or invalid")
        # The grant and independent revision reader are different host paths.
        # Never elevate a stale cached grant by HMAC-rebinding it to a new
        # authority revision. A new host-issued grant must carry that revision.
        if grant.authority_revision != authority_revision:
            raise CompositionRejected("host grant authority revision mismatch")
        return grant, authority_revision

    def resolve() -> tuple[dict[str, Any], bytes, int]:
        grant, authority_revision = checked_grant()
        # The existing session's post-inference check compares the state SHA.
        # Re-signing with a grant-scoped key means revocation/regrant with an
        # otherwise identical record set still changes that SHA.  The host MUST
        # advance approval_epoch for any intervening policy revocation/change.
        grant_binding = _grant_binding(grant, authority_revision)
        epoch_key = hmac.new(integrity_key, b"mini-vera-host-grant-v1\x00" + grant_binding,
                             hashlib.sha256).digest()
        issued_digests = dict(grant.record_digests)

        def policy(record: "MemoryRecord", _head: str) -> bool:
            if (type(record.record_digest) is not str
                    or len(record.record_digest) != 64
                    or any(c not in "0123456789abcdef" for c in record.record_digest)
                    or record.record_id not in issued_digests
                    or not hmac.compare_digest(
                        record.record_digest, issued_digests[record.record_id])):
                raise CompositionRejected("selected record digest mismatch against host grant")
            # The ledger projector emits record.text *after* this callback.
            # Even frozen MemoryRecord objects can be mutated through
            # object.__setattr__. Review an isolated copy, and reject any
            # changed original or review copy before yielding to the
            # projector. The snapshot deep-copies nested values as well.
            try:
                approved_snapshot = astuple(record)
                reviewed_record = deepcopy(record)
            except Exception:
                snapshot_failed = True
            else:
                snapshot_failed = False
            if snapshot_failed:
                raise CompositionRejected("host public-memory record snapshot unavailable")
            try:
                # Every exception from *host policy* (including its own
                # CompositionRejected) is private to the issuer. Do not
                # propagate callback text into CLI stderr or caller errors.
                approved = approve_record(reviewed_record, grant) is True
            except Exception:
                policy_failed = True
            else:
                policy_failed = False
            if policy_failed:
                # Raise outside the exception handler so even __cause__ and
                # __context__ cannot expose a host-private denial message.
                raise CompositionRejected("host public-memory record policy unavailable")
            try:
                changed = (astuple(record) != approved_snapshot
                           or astuple(reviewed_record) != approved_snapshot)
            except Exception:
                snapshot_failed = True
            else:
                snapshot_failed = False
            if snapshot_failed:
                raise CompositionRejected("host public-memory record snapshot unavailable")
            if changed:
                raise CompositionRejected("host public-memory record mutated during policy")
            return approved

        provider = approved_ledger_provider(
            ledger, record_ids=grant.record_ids,
            expected_head=grant.ledger_head, expected_revision=grant.revision,
            integrity_key=epoch_key, host_public_project_approval=policy,
        )
        state, key, revision = provider()
        # Compare the before/after *serialized values* even when the trusted
        # host returns the same object on both reads. Equality against the
        # same dataclass instance cannot detect in-place object mutation.
        after_grant, after_authority_revision = checked_grant()
        if _grant_binding(after_grant, after_authority_revision) != grant_binding:
            raise CompositionRejected("host public-memory grant changed during projection")
        return state, key, revision

    return resolve
