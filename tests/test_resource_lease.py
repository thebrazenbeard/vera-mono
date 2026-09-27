import pytest

from vera_core.resource_lease import (
    CapabilityDenied,
    ClaimMode,
    ResourceClaim,
    ResourceCollision,
    ResourceLease,
    ResourceLeaseBusy,
    ResourceLeaseExpired,
    ResourceLeaseRegistry,
    StaleResourceFence,
)


def test_resource_leases_narrow_capabilities_detect_overlap_and_fence_stale_holders():
    registry = ResourceLeaseRegistry(
        {"repo.read", "repo.write"},
        fence_allocator=iter((41, 42, 43)).__next__,
    )

    writer = registry.open_lease(
        lease_id="lease-writer",
        task_id="task-a",
        capabilities={"repo.write"},
        claims=(ResourceClaim("repo:thebrazenbeard/vera-mono", ClaimMode.WRITE),),
        ttl_ns=100,
        now_ns=1_000,
    )
    assert writer.fencing_token == 41
    assert writer.protected_effect_authority == "NONE"

    with pytest.raises(CapabilityDenied):
        registry.open_lease(
            lease_id="too-powerful",
            task_id="task-b",
            capabilities={"provider.execute"},
            ttl_ns=100,
            now_ns=1_000,
        )

    with pytest.raises(ResourceCollision):
        registry.open_lease(
            lease_id="overlap",
            task_id="task-b",
            capabilities={"repo.read"},
            claims=(
                ResourceClaim(
                    "repo:thebrazenbeard/vera-mono/packages",
                    ClaimMode.READ,
                ),
            ),
            ttl_ns=100,
            now_ns=1_000,
        )

    registry.authorize(
        writer.lease_id,
        writer.fencing_token,
        "repo.write",
        resource_key="repo:thebrazenbeard/vera-mono/packages/vera_core",
        resource_mode=ClaimMode.WRITE,
        now_ns=1_050,
    )

    with pytest.raises(StaleResourceFence):
        registry.authorize(
            writer.lease_id,
            40,
            "repo.write",
            now_ns=1_050,
        )

    with pytest.raises(ResourceLeaseExpired):
        registry.authorize(
            writer.lease_id,
            writer.fencing_token,
            "repo.write",
            now_ns=1_100,
        )

    reader = registry.open_lease(
        lease_id="lease-reader",
        task_id="task-c",
        capabilities={"repo.read"},
        claims=(ResourceClaim("repo:thebrazenbeard/vera-mono", ClaimMode.READ),),
        ttl_ns=100,
        now_ns=1_100,
    )
    peer_reader = registry.open_lease(
        lease_id="lease-reader-2",
        task_id="task-d",
        capabilities={"repo.read"},
        claims=(
            ResourceClaim(
                "repo:thebrazenbeard/vera-mono/packages",
                ClaimMode.READ,
            ),
        ),
        ttl_ns=100,
        now_ns=1_100,
    )
    assert reader.fencing_token == 42
    assert peer_reader.fencing_token == 43


def test_resource_claim_rejects_noncanonical_logical_hierarchy_aliases():
    for key in (
        "repo:thebrazenbeard/vera-mono/../other",
        "repo:thebrazenbeard//vera-mono",
        "repo:thebrazenbeard/vera-mono/",
    ):
        with pytest.raises(ValueError, match="canonical"):
            ResourceClaim(key, ClaimMode.READ)


def test_resource_lease_authority_ceiling_is_not_caller_forgeable():
    with pytest.raises(TypeError):
        ResourceLease(
            lease_id="fake",
            task_id="task",
            capabilities=frozenset(),
            claims=(),
            fencing_token=1,
            expires_at_ns=10,
            protected_effect_authority="GRANTED",
        )

    with pytest.raises(TypeError):
        ResourceLease(
            lease_id="fake",
            task_id="task",
            capabilities=frozenset(),
            claims=(),
            fencing_token=1,
            expires_at_ns=10,
            persistence="DURABLE",
        )


def test_inflight_hold_is_quiescence_barrier_for_close_and_expiry_reap():
    registry = ResourceLeaseRegistry({"repo.write"})
    writer = registry.open_lease(
        lease_id="writer",
        task_id="task-a",
        capabilities={"repo.write"},
        claims=(ResourceClaim("repo:portfolio/root", ClaimMode.WRITE),),
        ttl_ns=100,
        now_ns=1_000,
    )

    with registry.hold(
        writer.lease_id,
        writer.fencing_token,
        "repo.write",
        resource_key="repo:portfolio/root/file",
        resource_mode=ClaimMode.WRITE,
        now_ns=1_050,
    ):
        with pytest.raises(ResourceLeaseBusy, match="in-flight"):
            registry.close(
                writer.lease_id,
                writer.fencing_token,
                now_ns=1_050,
            )

        with pytest.raises(ResourceCollision):
            registry.open_lease(
                lease_id="conflict",
                task_id="task-b",
                capabilities={"repo.write"},
                claims=(
                    ResourceClaim(
                        "repo:portfolio/root/other",
                        ClaimMode.WRITE,
                    ),
                ),
                ttl_ns=100,
                now_ns=1_200,
            )

    replacement = registry.open_lease(
        lease_id="replacement",
        task_id="task-b",
        capabilities={"repo.write"},
        claims=(
            ResourceClaim(
                "repo:portfolio/root/other",
                ClaimMode.WRITE,
            ),
        ),
        ttl_ns=100,
        now_ns=1_200,
    )
    assert replacement.fencing_token > writer.fencing_token
