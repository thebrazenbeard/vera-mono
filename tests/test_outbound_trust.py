import sqlite3

import pytest

from vera_core import (
    HmacPCJobAuthority,
    HmacProviderAuthority,
    OutboundTrustError,
    OutboundTrustRegistry,
)


def test_outbound_trust_register_rotate_revoke_reactivate(tmp_path):
    registry = OutboundTrustRegistry(tmp_path / "outbound-trust.sqlite")
    first = HmacProviderAuthority(
        "provider-authority",
        "provider-a",
        b"a" * 32,
        key_id="provider-key-v1",
    )
    receipt1 = registry.register(
        authority_id=first.authority_id,
        role="PROVIDER",
        provider_id="provider-a",
        key_id=first.key_id,
        key_digest=first.key_digest,
        expected_registry_generation=0,
    )
    assert receipt1.authority_generation == 1
    assert receipt1.revocation_epoch == 0
    assert receipt1.registry_generation == 1
    assert registry.verify_chain() == receipt1.registry_head_digest

    second = HmacProviderAuthority(
        "provider-authority",
        "provider-a",
        b"b" * 32,
        key_id="provider-key-v2",
    )
    receipt2 = registry.rotate(
        authority_id=second.authority_id,
        role="PROVIDER",
        provider_id="provider-a",
        key_id=second.key_id,
        key_digest=second.key_digest,
        expected_registry_generation=1,
        expected_authority_generation=1,
    )
    assert receipt2.authority_generation == 2
    assert receipt2.revocation_epoch == 0
    with pytest.raises(OutboundTrustError):
        registry.assert_current(
            authority_id=first.authority_id,
            role="PROVIDER",
            provider_id="provider-a",
            key_id=first.key_id,
            key_digest=first.key_digest,
        )

    epoch = registry.revoke(
        authority_id=second.authority_id,
        role="PROVIDER",
        provider_id="provider-a",
        expected_registry_generation=2,
        expected_revocation_epoch=0,
    )
    assert epoch == 1
    assert registry.read_scope(
        role="PROVIDER",
        provider_id="provider-a",
    ).enabled is False
    with pytest.raises(OutboundTrustError):
        registry.assert_current(
            authority_id=second.authority_id,
            role="PROVIDER",
            provider_id="provider-a",
            key_id=second.key_id,
            key_digest=second.key_digest,
        )

    third = HmacProviderAuthority(
        "replacement-authority",
        "provider-a",
        b"c" * 32,
        key_id="provider-key-v3",
    )
    receipt3 = registry.reactivate(
        authority_id=third.authority_id,
        role="PROVIDER",
        provider_id="provider-a",
        key_id=third.key_id,
        key_digest=third.key_digest,
        expected_registry_generation=3,
        expected_authority_generation=2,
        expected_revocation_epoch=1,
    )
    assert receipt3.authority_generation == 3
    assert receipt3.revocation_epoch == 1
    assert receipt3.registry_generation == 4
    assert registry.verify_chain() == receipt3.registry_head_digest


def test_outbound_trust_cas_rejects_stale_registry_generation(tmp_path):
    registry = OutboundTrustRegistry(tmp_path / "outbound-trust.sqlite")
    pc = HmacPCJobAuthority(
        "issuer/pc",
        b"p" * 32,
        key_id="pc-v1",
    )
    registry.register(
        authority_id=pc.authority_id,
        role="PC",
        key_id=pc.key_id,
        key_digest=pc.key_digest,
        expected_registry_generation=0,
    )
    provider = HmacProviderAuthority(
        "issuer/provider",
        "provider-a",
        b"q" * 32,
        key_id="provider-v1",
    )
    with pytest.raises(OutboundTrustError):
        registry.register(
            authority_id=provider.authority_id,
            role="PROVIDER",
            provider_id="provider-a",
            key_id=provider.key_id,
            key_digest=provider.key_digest,
            expected_registry_generation=0,
        )


def test_outbound_trust_chain_tamper_fails_currentness_read(tmp_path):
    registry = OutboundTrustRegistry(tmp_path / "outbound-trust.sqlite")
    pc = HmacPCJobAuthority(
        "issuer/pc",
        b"p" * 32,
        key_id="pc-v1",
    )
    registry.register(
        authority_id=pc.authority_id,
        role="PC",
        key_id=pc.key_id,
        key_digest=pc.key_digest,
        expected_registry_generation=0,
    )

    with sqlite3.connect(registry.path) as db:
        db.execute(
            "UPDATE events SET payload_json='{}' WHERE registry_generation=1"
        )

    with pytest.raises(OutboundTrustError):
        registry.assert_current(
            authority_id=pc.authority_id,
            role="PC",
            key_id=pc.key_id,
            key_digest=pc.key_digest,
        )
