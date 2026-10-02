from __future__ import annotations

import importlib

import pytest


def _module():
    return importlib.import_module("runtime_cohesion.resolution_binding")


def test_binding_digest_changes_when_candidate_order_changes():
    module = _module()
    left = module.ResolutionRouteBinding.create(
        ("a" * 64, "b" * 64, "c" * 64)
    )
    right = module.ResolutionRouteBinding.create(
        ("b" * 64, "a" * 64, "c" * 64)
    )

    assert left.binding_digest != right.binding_digest


def test_chunk_route_resolves_to_bound_durable_block_id():
    module = _module()
    binding = module.ResolutionRouteBinding.create(
        ("a" * 64, "b" * 64, "c" * 64)
    )

    route = module.resolve_resolution_route(binding, "chunk:1")

    assert route.status is module.BoundRouteStatus.PROMOTE
    assert route.evidence_ref == "b" * 64
    assert route.chunk_index == 1
    assert route.binding_digest == binding.binding_digest


def test_direct_route_carries_no_evidence_ref():
    module = _module()
    binding = module.ResolutionRouteBinding.create(("a" * 64,))

    route = module.resolve_resolution_route(binding, "DIRECT")

    assert route.status is module.BoundRouteStatus.DIRECT
    assert route.evidence_ref is None
    assert route.chunk_index is None


def test_insufficient_route_carries_no_evidence_ref():
    module = _module()
    binding = module.ResolutionRouteBinding.create(("a" * 64,))

    route = module.resolve_resolution_route(
        binding,
        "INSUFFICIENT_FIDELITY",
    )

    assert route.status is module.BoundRouteStatus.INSUFFICIENT_FIDELITY
    assert route.evidence_ref is None


def test_out_of_range_chunk_route_fails_closed():
    module = _module()
    binding = module.ResolutionRouteBinding.create(
        ("a" * 64, "b" * 64)
    )

    with pytest.raises(module.ResolutionBindingError, match="outside"):
        module.resolve_resolution_route(binding, "chunk:2")


def test_binding_rejects_duplicate_or_malformed_block_ids():
    module = _module()

    with pytest.raises(module.ResolutionBindingError, match="unique"):
        module.ResolutionRouteBinding.create(("a" * 64, "a" * 64))

    with pytest.raises(module.ResolutionBindingError, match="sha256"):
        module.ResolutionRouteBinding.create(("not-a-digest",))


def test_forged_binding_digest_is_rejected_on_resolution():
    module = _module()
    binding = module.ResolutionRouteBinding.create(
        ("a" * 64, "b" * 64)
    )
    forged = module.ResolutionRouteBinding(
        block_ids=binding.block_ids,
        binding_digest="0" * 64,
    )

    with pytest.raises(module.ResolutionBindingError, match="binding_digest"):
        module.resolve_resolution_route(forged, "chunk:0")
