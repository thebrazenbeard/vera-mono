from __future__ import annotations

from hashlib import sha256

from vera_core import VeraStateDirectory
from vera_memory import LatentBlock, LossClass, Resolution


def _block(source: bytes = b"exact source") -> LatentBlock:
    return LatentBlock.create(
        source_refs=("source:a",),
        source_digest=sha256(source).hexdigest(),
        resolution=Resolution.L2_SEMANTIC_LATENT,
        codec_id="test-codec",
        codec_version="1",
        representation=b"compact state",
        loss_class=LossClass.LOSSY,
        exact_recoverable=True,
        provenance=("test:fixture",),
        created_at="2026-10-02T12:00:00Z",
    )


def test_state_directory_latent_store_survives_restart_without_moving_memory_head(
    tmp_path,
):
    root = tmp_path / "state"
    state = VeraStateDirectory(
        root,
        project_id="vera-mono",
        identity_id="vera",
    )
    lifecycle = state.open()
    memory_head = lifecycle.memory.current_head
    block = _block()

    store = state.latent_memory_store()
    store.put(block)

    reopened = VeraStateDirectory(
        root,
        project_id="vera-mono",
        identity_id="vera",
    )
    assert reopened.paths.latent_memory == root.resolve() / "memory" / "latent.sqlite"
    assert reopened.latent_memory_store().get(block.block_id) == block
    assert reopened.open().memory.current_head == memory_head
    assert reopened.resume_context()["latent_memory"]["block_count"] == 1
