from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import importlib

import pytest

from runtime_cohesion import ContextCandidate, assemble_context
from vera_memory import LatentBlock, LossClass, Resolution


def _module():
    try:
        return importlib.import_module("vera_assurance.latent_memory")
    except ModuleNotFoundError:
        pytest.fail("vera_assurance.latent_memory is missing")


def _block(
    source: bytes = b"exact source bytes",
    *,
    resolution: Resolution = Resolution.L2_SEMANTIC_LATENT,
    loss_class: LossClass = LossClass.LOSSY,
    representation: bytes = b"compact",
) -> LatentBlock:
    return LatentBlock.create(
        source_refs=("source:a",),
        source_digest=sha256(source).hexdigest(),
        resolution=resolution,
        codec_id="test-codec",
        codec_version="1",
        representation=representation,
        loss_class=loss_class,
        exact_recoverable=True,
        provenance=("test:fixture",),
        created_at="2026-10-02T12:00:00Z",
    )


def test_assurance_flags_lossy_block_declared_at_exact_resolution():
    module = _module()
    block = _block(
        resolution=Resolution.L0_EXACT,
        loss_class=LossClass.LOSSY,
        representation=b"exact source bytes",
    )

    report = module.audit_latent_blocks((block,))

    assert report.valid is False
    assert {finding.code for finding in report.findings} == {
        "LOSSY_DECLARED_EXACT"
    }


def test_assurance_flags_source_detached_latent_record_without_raising():
    module = _module()
    block = _block()
    detached = replace(block, source_refs=())

    report = module.audit_latent_blocks((detached,))

    assert report.valid is False
    assert "SOURCE_DETACHED" in {finding.code for finding in report.findings}


def test_assurance_flags_context_receipt_byte_count_inconsistency():
    module = _module()
    source = b"exact source bytes"
    block = _block(source)
    receipt = assemble_context(
        (
            ContextCandidate(
                block=block,
                task_relevance=10,
                exactness_required=True,
            ),
        ),
        active_budget_bytes=128,
        backing_loader=lambda ref: source,
    )
    forged = replace(receipt, active_bytes=receipt.active_bytes + 1)

    report = module.audit_context_receipt(forged, (block,))

    assert report.valid is False
    assert "ACTIVE_BYTE_MISMATCH" in {
        finding.code for finding in report.findings
    }


def test_assurance_accepts_verified_exact_backed_context_assembly():
    module = _module()
    source = b"Patrick bought a red screwdriver."
    block = _block(source, representation=b"Patrick bought a tool.")
    receipt = assemble_context(
        (
            ContextCandidate(
                block=block,
                task_relevance=10,
                exactness_required=True,
            ),
        ),
        active_budget_bytes=128,
        backing_loader=lambda ref: source,
    )

    report = module.audit_context_receipt(receipt, (block,))

    assert report.valid is True
    assert report.findings == ()
    assert report.checked_blocks == 1


def test_assurance_detects_exact_item_whose_bytes_do_not_match_bound_source():
    module = _module()
    source = b"exact source bytes"
    block = _block(source)
    receipt = assemble_context(
        (
            ContextCandidate(
                block=block,
                task_relevance=10,
                exactness_required=True,
            ),
        ),
        active_budget_bytes=128,
        backing_loader=lambda ref: source,
    )
    item = replace(
        receipt.items[0],
        content=b"fabricated exact bytes",
        content_digest=sha256(b"fabricated exact bytes").hexdigest(),
        bytes_used=len(b"fabricated exact bytes"),
    )
    forged = replace(
        receipt,
        items=(item,),
        active_bytes=item.bytes_used,
        rehydration_bytes=item.bytes_used,
    )

    report = module.audit_context_receipt(forged, (block,))

    assert report.valid is False
    assert "EXACT_SOURCE_MISMATCH" in {
        finding.code for finding in report.findings
    }


def test_assurance_package_exports_latent_audit_api():
    import vera_assurance

    assert vera_assurance.LatentAssuranceReport is not None
    assert vera_assurance.audit_latent_blocks is not None
    assert vera_assurance.audit_context_receipt is not None
