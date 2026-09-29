import pytest

from vera_assurance.mechanism_admission import (
    MechanismEvidencePacket,
    MechanismAdmissionError,
    assert_mechanism_admissible,
)


def test_mechanism_admission_requires_falsification_holdout_ablation_and_rivals():
    good = MechanismEvidencePacket(
        mechanism_id="bounded-recall-gate",
        clarity_pass=True,
        identifiability="IDENTIFIABLE_ENOUGH_FOR_TEST",
        kill_test_id="kill:replay",
        kill_test_survived=True,
        holdout_or_invariant_target="holdout:unseen-cue",
        holdout_or_invariant_value_pass=True,
        ablation_expectation="Removing the gate increases replay violations.",
        ablation_value_pass=True,
        structural_rival_analysis="Compare against a stateless dedup-only rival.",
        complexity_proportionate=True,
        numerical_integrity="PASS",
        unresolved_negative_transfer_defects=(),
    )
    assert_mechanism_admissible(good)

    bad = MechanismEvidencePacket(
        mechanism_id="ornamental-complexity",
        clarity_pass=True,
        identifiability="IDENTIFIABLE_ENOUGH_FOR_TEST",
        kill_test_id="kill:none",
        kill_test_survived=True,
        holdout_or_invariant_target="holdout:any",
        holdout_or_invariant_value_pass=True,
        ablation_expectation=None,
        ablation_value_pass=False,
        structural_rival_analysis="simple rival exists",
        complexity_proportionate=False,
        numerical_integrity="PASS",
        unresolved_negative_transfer_defects=(),
    )
    with pytest.raises(MechanismAdmissionError) as exc:
        assert_mechanism_admissible(bad)
    assert "ablation" in str(exc.value)
    assert "complexity" in str(exc.value)
