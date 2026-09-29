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
