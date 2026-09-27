import pytest

from vera_core.resource_lease import (
    CapabilityDenied,
    ClaimMode,
    ResourceClaim,
    ResourceCollision,
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
