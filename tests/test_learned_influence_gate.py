import pytest

from vera_memory.learned_influence import (
    LearnedInfluenceBlocked,
    LearnedInfluenceGate,
    LearnedInfluenceReplay,
    LearnedInfluenceStale,
    LearnedRevision,
    ReviewDisposition,
)


def test_learned_influence_is_revision_bound_quarantinable_and_replay_safe():
    gate = LearnedInfluenceGate()
    revision = LearnedRevision("cue->outcome", "rev-1")
    gate.review(
        association_id="cue->outcome",
        memory_revision_id="rev-1",
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="review:initial-pass",
    )

    first = gate.consume(revision, cue_event_id="cue-1")
    assert first.association_id == "cue->outcome"
    assert first.memory_revision_id == "rev-1"

    with pytest.raises(LearnedInfluenceReplay):
        gate.consume(revision, cue_event_id="cue-1")

    gate.review(
        association_id="cue->outcome",
        memory_revision_id="rev-1",
        disposition=ReviewDisposition.QUARANTINED,
        evidence_ref="holdout:contradiction",
    )
    with pytest.raises(LearnedInfluenceBlocked):
        gate.consume(revision, cue_event_id="cue-2")

    gate.review(
        association_id="cue->outcome",
        memory_revision_id="rev-1",
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="holdout:clear",
    )
    second = gate.consume(revision, cue_event_id="cue-2")
    assert second.cue_event_id == "cue-2"

    changed = LearnedRevision("cue->outcome", "rev-2")
    with pytest.raises(LearnedInfluenceStale):
        gate.consume(changed, cue_event_id="cue-3")


def test_unreviewed_learned_revision_is_blocked_until_explicit_review():
    gate = LearnedInfluenceGate()
    revision = LearnedRevision("novel-cue", "rev-1")

    with pytest.raises(LearnedInfluenceBlocked, match="explicit review"):
        gate.consume(revision, cue_event_id="cue-1")

    gate.review(
        association_id="novel-cue",
        memory_revision_id="rev-1",
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="review:held-out-pass",
    )
    receipt = gate.consume(revision, cue_event_id="cue-1")
    assert receipt.review_disposition is ReviewDisposition.ADMITTED
    assert receipt.review_evidence_ref == "review:held-out-pass"



def test_durable_learned_influence_survives_restart_and_preserves_replay(tmp_path):
    from vera_memory import DurableLearnedInfluenceGate

    path = tmp_path / "learned-influence.db"
    revision = LearnedRevision("durable-cue", "rev-7")

    first = DurableLearnedInfluenceGate(path)
    first.review(
        association_id=revision.association_id,
        memory_revision_id=revision.memory_revision_id,
        disposition=ReviewDisposition.ADMITTED,
        evidence_ref="review:durable-pass",
    )
    receipt = first.consume(revision, cue_event_id="cue-1")
    assert receipt.review_evidence_ref == "review:durable-pass"

    reopened = DurableLearnedInfluenceGate(path)
    with pytest.raises(LearnedInfluenceReplay):
        reopened.consume(revision, cue_event_id="cue-1")

    next_receipt = reopened.consume(revision, cue_event_id="cue-2")
    assert next_receipt.memory_revision_id == "rev-7"


def test_durable_quarantine_and_stale_review_survive_restart(tmp_path):
    from vera_memory import DurableLearnedInfluenceGate

    path = tmp_path / "learned-influence.db"
    gate = DurableLearnedInfluenceGate(path)
    gate.review(
        association_id="durable-cue",
        memory_revision_id="rev-1",
        disposition=ReviewDisposition.QUARANTINED,
        evidence_ref="review:quarantine",
    )

    reopened = DurableLearnedInfluenceGate(path)
    with pytest.raises(LearnedInfluenceBlocked):
        reopened.consume(
            LearnedRevision("durable-cue", "rev-1"),
            cue_event_id="cue-1",
        )
    with pytest.raises(LearnedInfluenceStale):
        reopened.consume(
            LearnedRevision("durable-cue", "rev-2"),
            cue_event_id="cue-2",
        )
