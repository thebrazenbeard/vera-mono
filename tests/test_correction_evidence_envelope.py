"""Source-level signed correction envelope: only authenticity of bounded bytes.

Neither signing nor a matching host-provided verifier proves honest labels,
independent evaluator custody, chronological issuance, or AGI/self-learning.
"""
from dataclasses import replace
import hashlib
import hmac

import pytest

from vera_assurance.evaluation_commitment import (
    ComparisonConditions, commit_prediction, compare_committed_predictions,
)
from vera_assurance.verified_correction import EvidenceSplit, PairedOutcome
from vera_assurance.correction_evidence_envelope import (
    EvaluatorRequirement, SignedCorrectionEnvelope,
    correction_envelope_subject, verify_correction_envelope,
)


class TestVerifier:
    __test__ = False

    def __init__(self, *, provider="external-evaluator", key="lab-key", secret=b"synthetic-test-key"):
        self.provider_id = provider
        self.key_id = key
        self.key_digest = hashlib.sha256(secret).hexdigest()
        self.secret = secret

    def sign(self, subject):
        return hmac.new(self.secret, subject, hashlib.sha256).hexdigest()

    def verify(self, subject, signature):
        return hmac.compare_digest(self.sign(subject), signature)


def trial(case_id, step, split, *, label="1", learner="1", frozen="0"):
    left = commit_prediction(candidate_id="adaptive", step=step, prediction={"case_id": case_id, "label": learner})
    right = commit_prediction(candidate_id="frozen", step=step, prediction={"case_id": case_id, "label": frozen})
    issued = ComparisonConditions(
        information_condition_id="info-" + case_id,
        opportunity_condition_id="opp-" + case_id,
        resource_condition_id="matched",
        representation_version="bit-v1",
    )
    return PairedOutcome(
        comparison=compare_committed_predictions(left, right, conditions=issued),
        issued_conditions=issued,
        learner=left,
        frozen=right,
        case_id=case_id,
        expected_label=label,
        evaluator_ref="external-" + case_id,
        split=split,
    )


def fixture():
    verifier = TestVerifier()
    observations = (
        trial("calibration", 0, EvidenceSplit.CALIBRATION),
        trial("heldout-1", 1, EvidenceSplit.QUALIFICATION),
        trial("heldout-2", 2, EvidenceSplit.QUALIFICATION),
    )
    packet = SignedCorrectionEnvelope(
        correction_id="corr-17",
        preoutcome_head="a" * 64,
        nonce="unique-observation-nonce",
        evaluator_instance_id="evaluator-process-01",
        learner_instance_id="learner-process-02",
        observations=observations,
    )
    requirement = EvaluatorRequirement(
        provider_id=verifier.provider_id,
        key_id=verifier.key_id,
        key_digest=verifier.key_digest,
        preoutcome_head=packet.preoutcome_head,
        evaluator_instance_id=packet.evaluator_instance_id,
    )
    signature = verifier.sign(correction_envelope_subject(packet))
    return verifier, packet, requirement, signature


def check(verifier, packet, requirement, signature, **kw):
    return verify_correction_envelope(
        envelope=packet,
        signature=signature,
        verifier=verifier,
        requirement=requirement,
        previously_seen_nonces=frozenset(),
        **kw,
    )


def test_valid_source_only_signature_gives_provisional_review_not_authority():
    v, p, requirement, signature = fixture()
    result = check(v, p, requirement, signature)
    assert result.status == "SIGNATURE_VALID_PROVISIONAL_ONLY"
    assert result.assessment.eligible_for_review is True
    assert result.qualified_as_independent is False
    assert result.qualified_as_self_learning is False
    assert result.authorization_effect == "NONE"
    assert result.nonce == p.nonce


def test_altered_feedback_label_invalidates_signed_subject():
    v, p, requirement, signature = fixture()
    altered = replace(p.observations[2], expected_label="0")
    with pytest.raises(ValueError, match="signature"):
        check(v, replace(p, observations=p.observations[:2] + (altered,)), requirement, signature)


def test_substituted_issued_conditions_invalidates_packet():
    v, p, requirement, signature = fixture()
    different = ComparisonConditions("new-info", "new-opp", "matched", "bit-v1")
    altered = replace(p.observations[1], issued_conditions=different)
    with pytest.raises(ValueError):
        check(v, replace(p, observations=(p.observations[0], altered, p.observations[2])),
              requirement, signature)


def test_verifier_key_and_provider_pinned_by_host():
    v, p, requirement, signature = fixture()
    with pytest.raises(ValueError, match="provider|key"):
        check(TestVerifier(provider="impostor"), p, requirement, signature)
    with pytest.raises(ValueError, match="provider|key"):
        check(TestVerifier(secret=b"substituted-secret"), p, requirement, signature)


def test_replayed_nonce_is_rejected_before_review():
    v, p, requirement, signature = fixture()
    with pytest.raises(ValueError, match="nonce|replay"):
        verify_correction_envelope(envelope=p, signature=signature, verifier=v,
            requirement=requirement, previously_seen_nonces=frozenset({p.nonce}))


def test_preoutcome_head_must_equal_host_pinned_snapshot():
    v, p, requirement, signature = fixture()
    with pytest.raises(ValueError, match="preoutcome"):
        check(v, replace(p, preoutcome_head="0" * 64), requirement, signature)


def test_evaluator_instance_requirement_prevents_identity_swap():
    v, p, requirement, signature = fixture()
    with pytest.raises(ValueError, match="evaluator"):
        check(v, replace(p, evaluator_instance_id="pretend-same-model"), requirement, signature)


def test_same_labeled_process_is_not_independent_evaluator():
    v, p, requirement, signature = fixture()
    same = replace(p, learner_instance_id=p.evaluator_instance_id)
    forged = v.sign(correction_envelope_subject(same))
    with pytest.raises(ValueError, match="same|distinct"):
        check(v, same, requirement, forged)



def test_untyped_split_fails_with_clear_validation_error():
    _, packet, _, _ = fixture()
    bad = replace(packet.observations[0], split="CALIBRATION")
    altered = replace(packet, observations=(bad,) + packet.observations[1:])
    with pytest.raises(ValueError, match="split"):
        correction_envelope_subject(altered)


def test_blank_or_invalid_signature_is_not_a_receipt():
    v, p, requirement, _ = fixture()
    for signature in ("", "not-a-signature", "0" * 64):
        with pytest.raises(ValueError, match="signature"):
            check(v, p, requirement, signature)


def test_caller_with_key_can_forge_trusted_looking_truth_so_claim_stays_limited():
    v, p, requirement, _ = fixture()
    fabricated_rows = tuple(replace(r, expected_label="1") for r in p.observations)
    fabricated_packet = replace(p, observations=fabricated_rows)
    fabricated_signature = v.sign(correction_envelope_subject(fabricated_packet))
    record = check(v, fabricated_packet, requirement, fabricated_signature)
    assert record.qualified_as_independent is False
    assert record.qualified_as_self_learning is False
