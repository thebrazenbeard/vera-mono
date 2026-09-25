from vera_core.capability_state import (
    CapabilityActivation,
    CapabilityHealth,
    CapabilityImplementationStatus,
    CapabilityLearningPolicy,
    CapabilityMaturity,
    CapabilityPresence,
    CapabilityState,
)


def test_capability_axes_remain_orthogonal_and_do_not_mint_authority():
    active = CapabilityState(
        capability_id="semantic-transfer",
        presence=CapabilityPresence.PRESENT,
        activation=CapabilityActivation.ACTIVE,
        maturity=CapabilityMaturity.STABLE_WITHIN_SCOPE,
        health=CapabilityHealth.NOMINAL,
        implementation_status=CapabilityImplementationStatus.QUALIFIED_WITHIN_SCOPE,
        learning_policy=CapabilityLearningPolicy.FULL_LEARNING_WITHIN_SCOPE,
    )
    assert active.is_active is True
    assert active.is_implemented is True
    assert active.may_learn is True
    assert active.effect_authorization == "EXTERNAL_DECISION_REQUIRED"
    assert active.authorization_effect == "NONE"

    latent = CapabilityState(
        capability_id="future-vision",
        presence=CapabilityPresence.PRESENT,
        activation=CapabilityActivation.DISABLED,
        maturity=CapabilityMaturity.UNDEVELOPED,
        health=CapabilityHealth.UNKNOWN,
        implementation_status=CapabilityImplementationStatus.UNIMPLEMENTED,
        learning_policy=CapabilityLearningPolicy.NO_LEARNING,
    )
    assert latent.presence is CapabilityPresence.PRESENT
    assert latent.is_implemented is False
    assert latent.is_active is False
    assert latent.may_learn is False
