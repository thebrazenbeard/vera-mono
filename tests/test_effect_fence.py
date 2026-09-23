import hashlib

from vera_assurance.effect_fence import (
    AtomicCurrentnessStore,
    EffectFence,
    EffectFenceError,
    EffectState,
)


def d(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_effect_fence_blocks_retry_after_ambiguous_dispatch(tmp_path):
    fence = EffectFence(tmp_path / "effects.sqlite")
    args = {
        "effect_id": "e1",
        "request_digest": d("request"),
        "mechanical_permit_digest": d("permit"),
        "authority_evidence_digest": d("authority"),
        "currentness_evidence_digest": d("current"),
    }
    assert fence.claim_dispatch(**args).state is EffectState.EXECUTING
    assert fence.settle("e1", result_digest=None, completion_known=False).state is EffectState.ATTEMPTED_UNKNOWN
    try:
        fence.claim_dispatch(**args)
    except EffectFenceError:
        pass
    else:
        raise AssertionError("ambiguous effect was incorrectly retryable")


def test_operator_cannot_abort_after_dispatch_claim(tmp_path):
    fence = EffectFence(tmp_path / "effects.sqlite")
    args = {
        "effect_id": "e1",
        "request_digest": d("request"),
        "mechanical_permit_digest": d("permit"),
        "authority_evidence_digest": d("authority"),
        "currentness_evidence_digest": d("current"),
    }
    fence.claim_dispatch(**args)
    try:
        fence.cancel_before_dispatch("e1")
    except EffectFenceError:
        pass
    else:
        raise AssertionError("post-dispatch operator abort was accepted")


def test_atomic_currentness_store_uses_generation_cas(tmp_path):
    store = AtomicCurrentnessStore(tmp_path / "current.sqlite")
    first = store.publish("runtime-config", {"v": 1}, expected_generation=None)
    assert first.generation == 0
    second = store.publish("runtime-config", {"v": 2}, expected_generation=0)
    assert second.generation == 1
    try:
        store.publish("runtime-config", {"v": 3}, expected_generation=0)
    except EffectFenceError:
        pass
    else:
        raise AssertionError("stale currentness generation was accepted")
