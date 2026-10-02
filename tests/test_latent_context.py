from __future__ import annotations

from hashlib import sha256
import importlib

import pytest

from vera_memory import LatentBlock, LossClass, Resolution


def _module():
    try:
        return importlib.import_module("runtime_cohesion.latent_context")
    except ModuleNotFoundError:
        pytest.fail("runtime_cohesion.latent_context is missing")


def _block(
    source_ref: str,
    source: bytes,
    representation: bytes,
    *,
    resolution: Resolution = Resolution.L2_SEMANTIC_LATENT,
    exact_recoverable: bool = True,
) -> LatentBlock:
    return LatentBlock.create(
        source_refs=(source_ref,),
        source_digest=sha256(source).hexdigest(),
        resolution=resolution,
        codec_id="test-codec",
        codec_version="1",
        representation=representation,
        loss_class=LossClass.LOSSY,
        exact_recoverable=exact_recoverable,
        provenance=("test:fixture",),
        created_at="2026-10-02T12:00:00Z",
    )


def test_exact_required_candidate_rehydrates_verified_backing_bytes():
    module = _module()
    source = b"Patrick bought a red screwdriver."
    block = _block("source:red-tool", source, b"Patrick bought a tool.")

    receipt = module.assemble_context(
        (
            module.ContextCandidate(
                block=block,
                task_relevance=10,
                exactness_required=True,
            ),
        ),
        active_budget_bytes=128,
        backing_loader=lambda ref: source,
    )

    assert receipt.active_bytes == len(source)
    assert receipt.rehydration_count == 1
    assert receipt.rehydration_bytes == len(source)
    assert receipt.items[0].content == source
    assert receipt.items[0].resolution is Resolution.L0_EXACT
    assert receipt.items[0].exact is True


def test_rehydration_fails_closed_on_source_digest_mismatch():
    module = _module()
    source = b"exact source"
    block = _block("source:a", source, b"compressed")

    with pytest.raises(module.LatentContextError, match="source digest"):
        module.assemble_context(
            (
                module.ContextCandidate(
                    block=block,
                    task_relevance=10,
                    exactness_required=True,
                ),
            ),
            active_budget_bytes=128,
            backing_loader=lambda ref: b"tampered source",
        )


def test_only_exact_required_block_touches_backing_loader():
    module = _module()
    first_source = b"first exact source"
    second_source = b"second exact source"
    first = _block("source:first", first_source, b"first compact")
    second = _block("source:second", second_source, b"second compact")
    calls: list[str] = []

    def load(ref: str) -> bytes:
        calls.append(ref)
        return {"source:first": first_source, "source:second": second_source}[ref]

    receipt = module.assemble_context(
        (
            module.ContextCandidate(
                block=first,
                task_relevance=10,
                exactness_required=True,
            ),
            module.ContextCandidate(
                block=second,
                task_relevance=9,
                exactness_required=False,
            ),
        ),
        active_budget_bytes=128,
        backing_loader=load,
    )

    assert calls == ["source:first"]
    assert receipt.rehydration_count == 1
    assert [item.block_id for item in receipt.items] == [
        first.block_id,
        second.block_id,
    ]
    assert receipt.items[1].content == second.representation
    assert receipt.items[1].exact is False


def test_compact_candidate_does_not_load_backing_when_fidelity_is_sufficient():
    module = _module()
    source = b"source bytes"
    block = _block("source:a", source, b"compact state")

    def forbidden_loader(ref: str) -> bytes:
        raise AssertionError(f"backing loader should not be called for {ref}")

    receipt = module.assemble_context(
        (
            module.ContextCandidate(
                block=block,
                task_relevance=5,
                exactness_required=False,
            ),
        ),
        active_budget_bytes=64,
        backing_loader=forbidden_loader,
    )

    assert receipt.rehydration_count == 0
    assert receipt.items[0].content == b"compact state"
    assert receipt.items[0].resolution is Resolution.L2_SEMANTIC_LATENT


def test_exact_promotion_that_exceeds_active_budget_fails_instead_of_truncating():
    module = _module()
    source = b"0123456789"
    block = _block("source:a", source, b"x")

    with pytest.raises(module.LatentContextError, match="active budget"):
        module.assemble_context(
            (
                module.ContextCandidate(
                    block=block,
                    task_relevance=10,
                    exactness_required=True,
                ),
            ),
            active_budget_bytes=5,
            backing_loader=lambda ref: source,
        )


def test_nonexact_lower_priority_block_is_omitted_when_budget_is_exhausted():
    module = _module()
    source_a = b"a"
    source_b = b"b"
    first = _block("source:a", source_a, b"12345")
    second = _block("source:b", source_b, b"67890")

    receipt = module.assemble_context(
        (
            module.ContextCandidate(
                block=second,
                task_relevance=1,
                exactness_required=False,
            ),
            module.ContextCandidate(
                block=first,
                task_relevance=10,
                exactness_required=False,
            ),
        ),
        active_budget_bytes=5,
        backing_loader=lambda ref: b"should-not-load",
    )

    assert [item.block_id for item in receipt.items] == [first.block_id]
    assert receipt.omitted_block_ids == (second.block_id,)


def test_runtime_package_exports_latent_context_api():
    import runtime_cohesion

    assert runtime_cohesion.ContextCandidate is not None
    assert runtime_cohesion.ContextAssemblyReceipt is not None
    assert runtime_cohesion.RehydrationRequest is not None
    assert runtime_cohesion.assemble_context is not None
