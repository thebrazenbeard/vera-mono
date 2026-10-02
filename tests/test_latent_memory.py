from __future__ import annotations

from dataclasses import replace
import importlib

import pytest


def _latent():
    try:
        return importlib.import_module("vera_memory.latent")
    except ModuleNotFoundError:
        pytest.fail("vera_memory.latent is missing")


def _make_block(module, **overrides):
    values = {
        "source_refs": ("ingest:sha256:source-a",),
        "source_digest": "a" * 64,
        "resolution": module.Resolution.L2_SEMANTIC_LATENT,
        "codec_id": "deterministic-summary",
        "codec_version": "1",
        "representation": b"patrick bought a red screwdriver",
        "loss_class": module.LossClass.LOSSY,
        "exact_recoverable": True,
        "provenance": ("receipt:ingest-a",),
        "created_at": "2026-10-02T12:00:00Z",
    }
    values.update(overrides)
    return module.LatentBlock.create(**values)


def test_latent_block_identity_is_deterministic_and_ignores_observation_time():
    module = _latent()
    first = _make_block(module)
    second = _make_block(module, created_at="2026-10-02T12:01:00Z")

    assert first.block_id == second.block_id
    assert first.representation_digest == second.representation_digest


def test_latent_block_identity_changes_when_bound_metadata_changes():
    module = _latent()
    base = _make_block(module)

    assert _make_block(module, codec_version="2").block_id != base.block_id
    assert _make_block(module, source_digest="b" * 64).block_id != base.block_id
    assert _make_block(
        module, source_refs=("ingest:sha256:source-b",)
    ).block_id != base.block_id


def test_latent_store_round_trips_durably(tmp_path):
    module = _latent()
    path = tmp_path / "latent.sqlite"
    block = _make_block(module)

    stored = module.LatentMemoryStore(path).put(block)
    reopened = module.LatentMemoryStore(path)

    assert stored == block
    assert reopened.get(block.block_id) == block
    assert reopened.all() == (block,)
    context = reopened.context()
    assert context["block_count"] == 1
    assert context["exact_recoverable_count"] == 1
    assert context["by_resolution"] == {"L2_SEMANTIC_LATENT": 1}


def test_latent_store_rejects_forged_block_identity(tmp_path):
    module = _latent()
    block = _make_block(module)
    forged = replace(block, block_id="0" * 64)

    with pytest.raises(module.LatentMemoryError, match="block_id"):
        module.LatentMemoryStore(tmp_path / "latent.sqlite").put(forged)


def test_exact_recoverable_block_requires_source_binding():
    module = _latent()

    with pytest.raises(module.LatentMemoryError, match="source_refs"):
        _make_block(module, source_refs=())


def test_latent_block_rejects_non_bytes_representation():
    module = _latent()

    with pytest.raises(module.LatentMemoryError, match="representation"):
        _make_block(module, representation="not-bytes")
