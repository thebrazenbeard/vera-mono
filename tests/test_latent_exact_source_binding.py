from __future__ import annotations

from hashlib import sha256

import pytest

from vera_memory import LatentBlock, LatentMemoryError, LossClass, Resolution


def _create(*, exact_recoverable: bool):
    return LatentBlock.create(
        source_refs=("source:a", "source:b"),
        source_digest=sha256(b"source a").hexdigest(),
        resolution=Resolution.L2_SEMANTIC_LATENT,
        codec_id="test",
        codec_version="1",
        representation=b"multi-source compact state",
        loss_class=LossClass.LOSSY,
        exact_recoverable=exact_recoverable,
        provenance=("test:fixture",),
        created_at="2026-10-02T12:00:00Z",
    )


def test_v1_exact_recoverable_block_rejects_multiple_source_refs():
    with pytest.raises(LatentMemoryError, match="exactly one source_ref"):
        _create(exact_recoverable=True)


def test_v1_nonexact_block_also_rejects_multiple_source_refs():
    with pytest.raises(LatentMemoryError, match="exactly one source_ref"):
        _create(exact_recoverable=False)
