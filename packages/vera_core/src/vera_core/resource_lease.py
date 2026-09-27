"""Live-only fenced resource leases for concurrent task work.

Adapted from VeraMesh VeraPort lane mechanics. The registry narrows
capabilities, rejects overlapping read/write claims, expires leases, and uses
monotonic fencing tokens to reject stale holders.

This is a live concurrency primitive only. It does not persist task ownership,
canonicalize filesystem paths, authenticate transports, or grant protected
effect authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import Callable, Iterable


class ResourceLeaseError(RuntimeError):
    pass


class CapabilityDenied(ResourceLeaseError):
    pass


class ResourceCollision(ResourceLeaseError):
    pass


class ResourceLeaseNotFound(ResourceLeaseError):
    pass


class StaleResourceFence(ResourceLeaseError):
    pass


class ResourceLeaseExpired(ResourceLeaseError):
    pass


class ClaimMode(StrEnum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, order=True, slots=True)
class ResourceClaim:
    key: str
    mode: ClaimMode

    def __post_init__(self) -> None:
        if type(self.key) is not str or not self.key.strip() or ":" not in self.key:
            raise ValueError(
                "resource claim key must be a namespaced non-empty exact string"
            )
        namespace, value = self.key.split(":", 1)
        if not namespace or not value:
            raise ValueError(
                "resource claim key must contain non-empty namespace and value"
            )
        if type(self.mode) is not ClaimMode:
            raise TypeError("resource claim mode must be exact ClaimMode")


@dataclass(frozen=True, slots=True)
class ResourceLease:
    lease_id: str
    task_id: str
    capabilities: frozenset[str]
    claims: tuple[ResourceClaim, ...]
    fencing_token: int
    expires_at_ns: int
    protected_effect_authority: str = "NONE"
    persistence: str = "LIVE_ONLY"


class ResourceLeaseRegistry:
    """In-process live concurrency leases with capability narrowing and fencing."""

    def __init__(
        self,
        capability_ceiling: set[str] | frozenset[str],
        *,
        max_leases: int = 32,
        fence_allocator: Callable[[], int] | None = None,
    ) -> None:
        if type(max_leases) is not int or isinstance(max_leases, bool) or max_leases < 1:
            raise ValueError("max_leases must be a positive exact integer")
        ceiling = frozenset(capability_ceiling)
        if any(type(item) is not str or not item for item in ceiling):
            raise ValueError(
                "capability_ceiling must contain non-empty exact strings"
            )
        self._capability_ceiling = ceiling
        self._max_leases = max_leases
        self._fence_allocator = fence_allocator
        self._last_fence = 0
        self._leases: dict[str, ResourceLease] = {}
        self._lock = RLock()

    @property
    def capability_ceiling(self) -> frozenset[str]:
        return self._capability_ceiling

    def open_lease(
        self,
        *,
        lease_id: str,
        task_id: str,
        capabilities: set[str] | frozenset[str],
        claims: Iterable[ResourceClaim] = (),
        ttl_ns: int,
        now_ns: int,
    ) -> ResourceLease:
        lease_id = self._require_text(lease_id, "lease_id")
        task_id = self._require_text(task_id, "task_id")
        ttl_ns = self._require_positive_int(ttl_ns, "ttl_ns")
        now_ns = self._require_nonnegative_int(now_ns, "now_ns")

        requested = frozenset(capabilities)
        if any(type(item) is not str or not item for item in requested):
            raise ValueError("capabilities must contain non-empty exact strings")
        if not requested.issubset(self._capability_ceiling):
            extra = tuple(sorted(requested - self._capability_ceiling))
            raise CapabilityDenied(
                "lease requested capabilities outside registry ceiling: "
                + ", ".join(extra)
            )

        claim_tuple = tuple(sorted(set(claims)))
        if any(type(item) is not ResourceClaim for item in claim_tuple):
            raise TypeError("claims must contain exact ResourceClaim values")

        with self._lock:
            self._reap_expired_locked(now_ns)
            if lease_id in self._leases:
                raise ResourceCollision(f"lease id already active: {lease_id}")
            if len(self._leases) >= self._max_leases:
                raise ResourceCollision("max active resource leases reached")

            for existing in self._leases.values():
                conflict = self._first_conflict(claim_tuple, existing.claims)
                if conflict is not None:
                    raise ResourceCollision(
                        "resource collision with lease "
                        f"{existing.lease_id}: {conflict}"
                    )

            fencing_token = self._next_fence()
            lease = ResourceLease(
                lease_id=lease_id,
                task_id=task_id,
                capabilities=requested,
                claims=claim_tuple,
                fencing_token=fencing_token,
                expires_at_ns=now_ns + ttl_ns,
            )
            self._leases[lease_id] = lease
            return lease

    def renew(
        self,
        lease_id: str,
        fencing_token: int,
        *,
        ttl_ns: int,
        now_ns: int,
    ) -> ResourceLease:
        ttl_ns = self._require_positive_int(ttl_ns, "ttl_ns")
        now_ns = self._require_nonnegative_int(now_ns, "now_ns")
        with self._lock:
            lease = self._require_lease_locked(
                lease_id,
                fencing_token,
                now_ns,
            )
            renewed = ResourceLease(
                lease_id=lease.lease_id,
                task_id=lease.task_id,
                capabilities=lease.capabilities,
                claims=lease.claims,
                fencing_token=lease.fencing_token,
                expires_at_ns=now_ns + ttl_ns,
            )
            self._leases[lease_id] = renewed
            return renewed

    def close(
        self,
        lease_id: str,
        fencing_token: int,
        *,
        now_ns: int,
    ) -> ResourceLease:
        now_ns = self._require_nonnegative_int(now_ns, "now_ns")
        with self._lock:
            lease = self._require_lease_locked(
                lease_id,
                fencing_token,
                now_ns,
            )
            del self._leases[lease_id]
            return lease

    def authorize(
        self,
        lease_id: str,
        fencing_token: int,
        capability: str,
        *,
        resource_key: str | None = None,
        resource_mode: ClaimMode | None = None,
        now_ns: int,
    ) -> ResourceLease:
        capability = self._require_text(capability, "capability")
        now_ns = self._require_nonnegative_int(now_ns, "now_ns")
        if (resource_key is None) != (resource_mode is None):
            raise ValueError(
                "resource_key and resource_mode must be supplied together"
            )
        with self._lock:
            lease = self._require_lease_locked(
                lease_id,
                fencing_token,
                now_ns,
            )
            if capability not in lease.capabilities:
                raise CapabilityDenied(
                    f"lease lacks capability: {capability}"
                )
            if resource_key is not None:
                probe = ResourceClaim(resource_key, resource_mode)
                if not any(
                    self._claim_covers(claim, probe)
                    for claim in lease.claims
                ):
                    raise CapabilityDenied(
                        "lease lacks "
                        f"{resource_mode.value} claim covering resource: "
                        f"{resource_key}"
                    )
            return lease

    def snapshot(self, *, now_ns: int) -> tuple[ResourceLease, ...]:
        now_ns = self._require_nonnegative_int(now_ns, "now_ns")
        with self._lock:
            self._reap_expired_locked(now_ns)
            return tuple(
                sorted(self._leases.values(), key=lambda item: item.lease_id)
            )

    def reap_expired(self, *, now_ns: int) -> tuple[ResourceLease, ...]:
        now_ns = self._require_nonnegative_int(now_ns, "now_ns")
        with self._lock:
            return self._reap_expired_locked(now_ns)

    def _next_fence(self) -> int:
        if self._fence_allocator is None:
            candidate = self._last_fence + 1
        else:
            candidate = self._fence_allocator()
        if (
            type(candidate) is not int
            or isinstance(candidate, bool)
            or candidate <= self._last_fence
        ):
            raise ResourceLeaseError(
                "fence allocator must return a strictly increasing exact integer"
            )
        self._last_fence = candidate
        return candidate

    def _require_lease_locked(
        self,
        lease_id: str,
        fencing_token: int,
        now_ns: int,
    ) -> ResourceLease:
        lease_id = self._require_text(lease_id, "lease_id")
        if (
            type(fencing_token) is not int
            or isinstance(fencing_token, bool)
            or fencing_token < 1
        ):
            raise StaleResourceFence(
                "fencing_token must be a positive exact integer"
            )
        lease = self._leases.get(lease_id)
        if lease is None:
            raise ResourceLeaseNotFound(lease_id)
        if lease.fencing_token != fencing_token:
            raise StaleResourceFence(
                f"expected fence {lease.fencing_token}, got {fencing_token}"
            )
        if now_ns >= lease.expires_at_ns:
            del self._leases[lease_id]
            raise ResourceLeaseExpired(lease_id)
        return lease

    def _reap_expired_locked(
        self,
        now_ns: int,
    ) -> tuple[ResourceLease, ...]:
        expired = tuple(
            lease
            for lease in self._leases.values()
            if now_ns >= lease.expires_at_ns
        )
        for lease in expired:
            self._leases.pop(lease.lease_id, None)
        return tuple(sorted(expired, key=lambda item: item.lease_id))

    @classmethod
    def _first_conflict(
        cls,
        left: tuple[ResourceClaim, ...],
        right: tuple[ResourceClaim, ...],
    ) -> str | None:
        for a in left:
            for b in right:
                if (
                    cls._resources_overlap(a.key, b.key)
                    and ClaimMode.WRITE in {a.mode, b.mode}
                ):
                    return (
                        f"{a.key}({a.mode.value}) vs "
                        f"{b.key}({b.mode.value})"
                    )
        return None

    @classmethod
    def _claim_covers(
        cls,
        claim: ResourceClaim,
        requested: ResourceClaim,
    ) -> bool:
        if (
            requested.mode is ClaimMode.WRITE
            and claim.mode is not ClaimMode.WRITE
        ):
            return False
        claim_namespace, claim_value = cls._parts(claim.key)
        requested_namespace, requested_value = cls._parts(requested.key)
        if claim_namespace != requested_namespace:
            return False
        return (
            requested_value == claim_value
            or requested_value.startswith(claim_value + "/")
        )

    @classmethod
    def _resources_overlap(cls, left: str, right: str) -> bool:
        left_namespace, left_value = cls._parts(left)
        right_namespace, right_value = cls._parts(right)
        if left_namespace != right_namespace:
            return False
        return (
            left_value == right_value
            or left_value.startswith(right_value + "/")
            or right_value.startswith(left_value + "/")
        )

    @staticmethod
    def _parts(key: str) -> tuple[str, str]:
        namespace, value = key.split(":", 1)
        return namespace, value.rstrip("/")

    @staticmethod
    def _require_text(value: str, label: str) -> str:
        if type(value) is not str or not value.strip():
            raise ValueError(f"{label} must be a non-empty exact string")
        return value

    @staticmethod
    def _require_positive_int(value: int, label: str) -> int:
        if type(value) is not int or isinstance(value, bool) or value < 1:
            raise ValueError(f"{label} must be a positive exact integer")
        return value

    @staticmethod
    def _require_nonnegative_int(value: int, label: str) -> int:
        if type(value) is not int or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"{label} must be a non-negative exact integer"
            )
        return value
