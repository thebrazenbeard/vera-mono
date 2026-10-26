"""Adversarial synthetic-only restart and review probes for supervised feedback."""

from dataclasses import asdict, replace
import json
import sqlite3
import subprocess
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import pytest

from vera_memory.local_feedback_learning import FeedbackSample, HeldoutCase, LearningBlocked
from vera_memory.supervised_feedback import SupervisedFeedbackJournal


def _sample(cue="the synthetic planet", answer="violet", number=1):
    return FeedbackSample(
        sample_id=f"sample-{number}", source_id=f"train-source-{number}", cue=cue,
        answer=answer, consent_ref="test-synthetic-opt-in",
        privacy_review_ref="test-synthetic-privacy", provenance_ref="test-synthetic-origin",
    )


def _holdout(cue="the synthetic planet", expected="violet", number=1):
    return HeldoutCase(
        case_id=f"holdout-{number}", source_id=f"holdout-source-{number}",
        cue=cue, expected=expected,
    )


@pytest.fixture
def broker(tmp_path):
    signing_key = Ed25519PrivateKey.generate()
    public_key = signing_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    db = tmp_path / "feedback.sqlite3"

    def open_journal(*, head=None, key=public_key, path=db, installation="lappy-test"):
        return SupervisedFeedbackJournal(
            path, installation_id=installation, trusted_reviewer_key=key,
            trusted_checkpoint_head=head, synthetic_fixture_mode=True,
        )

    def signed(journal, action, target, reference, *, signature_key=signing_key, **kwargs):
        challenge = journal.review_challenge(
            action=action, revision=target, approval_ref=reference, **kwargs,
        )
        return replace(challenge, signature=signature_key.sign(challenge.signable_bytes()).hex())

    return open_journal, signed, public_key, db


def test_default_off_and_external_checkpoint_required(tmp_path, broker):
    open_journal, _, public_key, db = broker
    with pytest.raises(LearningBlocked):
        SupervisedFeedbackJournal(db, installation_id="lappy-test", trusted_reviewer_key=public_key)
    j = open_journal()
    with pytest.raises(LearningBlocked, match="checkpoint"):
        open_journal()
    assert open_journal(head=j.head).active_revision == j.active_revision
    with pytest.raises(LearningBlocked, match="checkpoint"):
        open_journal(head="0" * 64)


def test_approval_and_rollback_survive_independent_processes(broker):
    open_journal, signed, _, db = broker
    first = open_journal()
    genesis = first.active_revision
    evaluation = first.stage((_sample(),), (_holdout(),))
    assert evaluation.qualified
    assert first.lookup("the synthetic planet") is None
    next_process = open_journal(head=first.head)
    decision = signed(next_process, "APPROVE", evaluation.candidate_revision, "review-1")
    approved = next_process.apply_review(decision)
    assert approved == evaluation.candidate_revision
    third_process = open_journal(head=next_process.head)
    assert third_process.lookup("THE SYNTHETIC PLANET") == "violet"
    runner = 'import sys; from vera_memory.supervised_feedback import SupervisedFeedbackJournal; j=SupervisedFeedbackJournal(sys.argv[1],installation_id="lappy-test",trusted_reviewer_key=bytes.fromhex(sys.argv[2]),trusted_checkpoint_head=sys.argv[3],synthetic_fixture_mode=True); print(j.active_revision); print(j.lookup("the synthetic planet"))'
    before_rollback = subprocess.run(
        [sys.executable, "-c", runner, str(db), broker[2].hex(), next_process.head],
        check=True, capture_output=True, text=True,
    )
    assert before_rollback.stdout.strip().splitlines() == [approved, "violet"]
    rollback = signed(third_process, "ROLLBACK", genesis, "review-rollback")
    third_process.apply_review(rollback)
    after_restart = open_journal(head=third_process.head)
    assert after_restart.active_revision == genesis
    assert after_restart.lookup("the synthetic planet") is None
    # A fourth Python interpreter must independently reconstruct the approved state.
    env = __import__("os").environ.copy()
    result = subprocess.run(
        [sys.executable, "-c", runner, str(db), broker[2].hex(), third_process.head],
        check=True, capture_output=True, text=True, env=env,
    )
    assert result.stdout.strip().splitlines() == [genesis, "None"]


def test_forgery_wrong_scope_and_key_substitution_fail_closed(broker):
    open_journal, signed, _, db = broker
    first = open_journal()
    evidence = first.stage((_sample(),), (_holdout(),))
    signing_other = Ed25519PrivateKey.generate()
    other_key = signing_other.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    with pytest.raises(LearningBlocked, match="key"):
        open_journal(head=first.head, key=other_key)
    j = open_journal(head=first.head)
    with pytest.raises(LearningBlocked, match="signature"):
        j.apply_review(signed(j, "APPROVE", evidence.candidate_revision, "forged", signature_key=signing_other))
    valid = signed(j, "APPROVE", evidence.candidate_revision, "valid")
    with pytest.raises(LearningBlocked):
        j.apply_review(replace(valid, installation_id="other-pc"))
    with pytest.raises(LearningBlocked):
        j.apply_review(replace(valid, candidate_revision="0" * 64))
    with pytest.raises(LearningBlocked):
        j.apply_review(replace(valid, signature="a" * 128))
    assert j.lookup("the synthetic planet") is None
    j.apply_review(valid)
    assert j.lookup("the synthetic planet") == "violet"
    # An attacker who can edit the writable DB may replace its metadata with
    # their own key fingerprint, but cannot replace the externally trusted key.
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE feedback_meta SET value=? WHERE name='reviewer_key_sha256'",
            (__import__("hashlib").sha256(other_key).hexdigest(),),
        )
    with pytest.raises(LearningBlocked, match="key mismatch"):
        open_journal(head=j.head)


def test_stale_replays_and_retained_canary_after_rollback(broker):
    open_journal, signed, _, _ = broker
    j = open_journal()
    genesis = j.active_revision
    evidence = j.stage((_sample(),), (_holdout(),))
    decision = signed(j, "APPROVE", evidence.candidate_revision, "old-approval")
    j.apply_review(decision)
    with pytest.raises(LearningBlocked):
        j.apply_review(decision)
    j.apply_review(signed(j, "ROLLBACK", genesis, "rollback-1"))
    with pytest.raises(LearningBlocked):
        j.stage((_sample("unrelated cue", "different", 2),), (_holdout("unrelated cue", "different", 2),))
    rebuilt = j.stage(
        (_sample(), _sample("unrelated cue", "different", 2)),
        (_holdout("unrelated cue", "different", 2),),
    )
    assert rebuilt.heldout_cases == 2
    with pytest.raises(LearningBlocked):
        j.apply_review(decision)


def test_signed_revoke_is_durable_and_cannot_restore_revoked_version(broker):
    open_journal, signed, _, _ = broker
    j = open_journal()
    genesis = j.active_revision
    ev = j.stage((_sample(),), (_holdout(),))
    j.apply_review(signed(j, "APPROVE", ev.candidate_revision, "approve-1"))
    j.apply_review(signed(j, "REVOKE", ev.candidate_revision, "revoke-1"))
    assert j.active_revision == genesis
    assert j.lookup("the synthetic planet") is None
    j2 = open_journal(head=j.head)
    assert j2.revoked_revisions == (ev.candidate_revision,)
    with pytest.raises(LearningBlocked):
        j2.review_challenge(action="ROLLBACK", revision=ev.candidate_revision, approval_ref="bad")


def test_truncated_tail_and_corrupt_event_detected_with_out_of_band_head(broker):
    open_journal, signed, _, db = broker
    j = open_journal()
    ev = j.stage((_sample(),), (_holdout(),))
    j.apply_review(signed(j, "APPROVE", ev.candidate_revision, "approve-1"))
    high_watermark = j.head
    with sqlite3.connect(db) as con:
        con.execute("DELETE FROM feedback_events WHERE sequence=(SELECT MAX(sequence) FROM feedback_events)")
    with pytest.raises(LearningBlocked, match="checkpoint"):
        open_journal(head=high_watermark)
    with sqlite3.connect(db) as con:
        con.execute("UPDATE feedback_events SET payload_json=? WHERE sequence=1", (json.dumps({"bad": "payload"}),))
    with pytest.raises(LearningBlocked, match="integrity"):
        open_journal(head=high_watermark)


def test_duplicate_json_keys_are_rejected_before_replay(broker):
    open_journal, _, _, db = broker
    journal = open_journal()
    journal.stage((_sample(),), (_holdout(),))
    head = journal.head
    # Python JSON normally accepts the last duplicate key. SQLite JSON
    # extraction can choose a different occurrence. Exact canonicality is required.
    with sqlite3.connect(db) as conn:
        original = conn.execute("SELECT payload_json FROM feedback_events WHERE sequence=1").fetchone()[0]
        conn.execute(
            "UPDATE feedback_events SET payload_json=? WHERE sequence=1",
            ('{"samples":[],"samples":' + original.split('"samples":', 1)[1],),
        )
    with pytest.raises(LearningBlocked, match="integrity"):
        open_journal(head=head)


def test_journal_ancestor_symlink_and_hardlink_are_rejected(tmp_path, broker):
    open_journal, _, _, db = broker
    first = open_journal()
    alias = tmp_path / "alias-dir"
    alias.symlink_to(db.parent, target_is_directory=True)
    with pytest.raises(LearningBlocked, match="symlink"):
        open_journal(head=first.head, path=alias / db.name)
    hardlink = tmp_path / "other-name.sqlite3"
    __import__("os").link(db, hardlink)
    with pytest.raises(LearningBlocked, match="hard-linked"):
        open_journal(head=first.head, path=hardlink)


def test_stale_concurrent_writer_is_rejected_and_cannot_overwrite(broker):
    open_journal, _, _, _ = broker
    writer_a = open_journal()
    writer_b = open_journal(head=writer_a.head)
    ev = writer_a.stage((_sample(),), (_holdout(),))
    with pytest.raises(LearningBlocked, match="checkpoint"):
        writer_b.stage((_sample("else", "yes", 2),), (_holdout("else", "yes", 2),))
    assert open_journal(head=writer_a.head).active_revision == ev.baseline_revision


def test_revoke_survives_new_interpreter_and_invalidates_lookup(broker):
    open_journal, signed, public_key, db = broker
    first = open_journal()
    ev = first.stage((_sample(),), (_holdout(),))
    approved = signed(first, "APPROVE", ev.candidate_revision, "review-1")
    first.apply_review(approved)
    revoke = signed(first, "REVOKE", ev.candidate_revision, "review-revoke")
    first.apply_review(revoke)
    runner = 'import sys; from vera_memory.supervised_feedback import SupervisedFeedbackJournal; j=SupervisedFeedbackJournal(sys.argv[1],installation_id="lappy-test",trusted_reviewer_key=bytes.fromhex(sys.argv[2]),trusted_checkpoint_head=sys.argv[3],synthetic_fixture_mode=True); print(j.lookup("the synthetic planet")); print(j.revoked_revisions[0])'
    result = subprocess.run(
        [sys.executable, "-c", runner, str(db), public_key.hex(), first.head],
        check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip().splitlines() == ["None", ev.candidate_revision]


def test_long_lived_consumer_fails_closed_after_independent_signed_revoke(broker):
    open_journal, signed, public_key, db = broker
    writer = open_journal()
    ev = writer.stage((_sample(),), (_holdout(),))
    writer.apply_review(signed(writer, "APPROVE", ev.candidate_revision, "first-approve"))
    consumer = open_journal(head=writer.head)
    assert consumer.lookup("the synthetic planet") == "violet"
    other_process = open_journal(head=writer.head)
    signed_revoke = signed(other_process, "REVOKE", ev.candidate_revision, "second-revoke")
    runner = 'import sys,json; from vera_memory.supervised_feedback import SupervisedFeedbackJournal,ReviewDecision; j=SupervisedFeedbackJournal(sys.argv[1],installation_id="lappy-test",trusted_reviewer_key=bytes.fromhex(sys.argv[2]),trusted_checkpoint_head=sys.argv[3],synthetic_fixture_mode=True); j.apply_review(ReviewDecision(**json.loads(sys.argv[4]))); print(j.head)'
    child = subprocess.run(
        [sys.executable, "-c", runner, str(db), public_key.hex(), other_process.head, json.dumps(asdict(signed_revoke))],
        check=True, capture_output=True, text=True,
    )
    newest_head = child.stdout.strip()
    assert open_journal(head=newest_head).lookup("the synthetic planet") is None
    # The old process must never keep serving a superseded answer from cache.
    with pytest.raises(LearningBlocked, match="checkpoint"):
        consumer.lookup("the synthetic planet")


def test_failed_or_modified_holdout_never_promotes(broker):
    open_journal, signed, _, _ = broker
    j = open_journal()
    with pytest.raises(LearningBlocked):
        j.stage((_sample(),), (_holdout(expected="magenta"),))
    ev = j.stage((_sample(),), (_holdout(),))
    decision = signed(j, "APPROVE", ev.candidate_revision, "valid")
    with pytest.raises(LearningBlocked):
        j.apply_review(replace(decision, heldout_sha256="0" * 64))
    assert j.lookup("the synthetic planet") is None
