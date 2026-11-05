"""Synthetic signed-grant qualification; no real issuer or consent is asserted."""

import base64
from dataclasses import FrozenInstanceError
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vera_core.host_authz.grants import (
    ApprovedGrant,
    GrantVerificationError,
    SIGNATURE_CONTEXT,
    SignedGrantVerifier,
)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def fixture(now=1000):
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    verifier = SignedGrantVerifier(
        public,
        issuer_id="issuer-1",
        host_id="host-1",
        epoch=3,
        trusted_clock=lambda: now,
    )
    grant = dict(
        grant_id="grant-1", issuer_id="issuer-1", host_id="host-1",
        epoch=3, peer_key="uid:1001", model_id="model-a",
        adapter_id="adapter-a", runtime_id="runtime-a", subject_id="subject-a",
        participant_id="participant-1", purpose="experimental-pleasure",
        provider_id="provider-1", provider_instance_id="provider-instance-1",
        operation="evaluate",
        request_digest="e" * 64, not_before=900, expires_at=1100,
    )
    return key, verifier, grant


def sign(key, grant):
    signature = base64.urlsafe_b64encode(key.sign(SIGNATURE_CONTEXT + canonical(grant))).rstrip(b"=").decode()
    return canonical({"schema": "HOST_AUTHZ_SIGNED_GRANT_V1", "grant": grant, "signature": signature})


def test_good_signature_preserves_exact_scope():
    key, verifier, grant = fixture()
    actual = verifier.verify(sign(key, grant))
    assert type(actual) is ApprovedGrant
    assert actual.canonical_body() == grant
    assert actual.peer_key == "uid:1001"
    assert actual.model_id == "model-a"


def test_pinned_verifier_bindings_are_read_only():
    _, verifier, _ = fixture()
    assert (verifier.issuer_id, verifier.host_id, verifier.epoch) == (
        "issuer-1", "host-1", 3,
    )
    with pytest.raises(FrozenInstanceError):
        verifier._issuer_id = "issuer-2"
    with pytest.raises(FrozenInstanceError):
        verifier._clock = lambda: 1000000


@pytest.mark.parametrize("field,value", [
    ("model_id", "model-b"), ("peer_key", "uid:1002"),
    ("host_id", "host-2"), ("epoch", 4),
    ("participant_id", "participant-2"), ("subject_id", "subject-b"),
    ("provider_id", "provider-2"),
    ("provider_instance_id", "attacker-rebound-provider"),
    ("operation", "commit"),
    ("purpose", "other"), ("request_digest", "f" * 64),
])
def test_signed_grant_tampering_fails(field, value):
    key, verifier, grant = fixture()
    envelope = json.loads(sign(key, grant))
    envelope["grant"][field] = value
    with pytest.raises(GrantVerificationError):
        verifier.verify(canonical(envelope))


def test_wrong_issuer_key_fails():
    _, verifier, grant = fixture()
    attacker = Ed25519PrivateKey.generate()
    with pytest.raises(GrantVerificationError):
        verifier.verify(sign(attacker, grant))


def test_provider_instance_id_required_even_for_authentic_signature():
    key, verifier, grant = fixture()
    grant.pop("provider_instance_id")
    with pytest.raises(GrantVerificationError):
        verifier.verify(sign(key, grant))


def test_provider_instance_id_cannot_be_added_without_resigning():
    key, verifier, grant = fixture()
    envelope = json.loads(sign(key, grant))
    envelope["grant"]["provider_instance_id"] = "same-name-different-provider"
    with pytest.raises(GrantVerificationError):
        verifier.verify(canonical(envelope))


@pytest.mark.parametrize("field,value", [
    ("host_id", "host-2"), ("issuer_id", "issuer-2"), ("epoch", 4),
])
def test_scope_signed_by_issuer_still_rejected_if_wrong_host_context(field, value):
    key, verifier, grant = fixture()
    grant[field] = value
    with pytest.raises(GrantVerificationError):
        verifier.verify(sign(key, grant))


@pytest.mark.parametrize("now", [899, 1100, 5000])
def test_not_yet_valid_or_expired(now):
    key, verifier, grant = fixture(now=now)
    with pytest.raises(GrantVerificationError):
        verifier.verify(sign(key, grant))


def test_bounds_are_inclusive_start_exclusive_end():
    key, verifier, grant = fixture(now=900)
    assert verifier.verify(sign(key, grant)).grant_id == "grant-1"


def test_duplicate_json_keys_rejected():
    key, verifier, grant = fixture()
    token = sign(key, grant)
    duplicate = token.replace(b'"host_id":"host-1",', b'"host_id":"host-1","host_id":"host-2",')
    assert duplicate != token
    with pytest.raises(GrantVerificationError):
        verifier.verify(duplicate)


def test_noncanonical_encoding_rejected():
    key, verifier, grant = fixture()
    token = sign(key, grant)
    noncanonical = token.replace(b'"grant":', b'"grant": ')
    with pytest.raises(GrantVerificationError):
        verifier.verify(noncanonical)


@pytest.mark.parametrize("change", [
    lambda o: o.update({"x": 1}),
    lambda o: o["grant"].update({"extra": 1}),
    lambda o: o.update({"schema": "UNKNOWN"}),
    lambda o: o.update({"signature": o["signature"] + "="}),
])
def test_unknown_fields_schema_or_noncanonical_signature_rejected(change):
    key, verifier, grant = fixture()
    obj = json.loads(sign(key, grant))
    change(obj)
    with pytest.raises(GrantVerificationError):
        verifier.verify(canonical(obj))


@pytest.mark.parametrize("field,value", [
    ("grant_id", ""), ("model_id", 123), ("request_digest", "ABC"),
    ("not_before", True), ("expires_at", 900),
    ("epoch", True), ("purpose", ""),
])
def test_invalid_but_signed_grant_schema_rejected(field, value):
    key, verifier, grant = fixture()
    grant[field] = value
    with pytest.raises(GrantVerificationError):
        verifier.verify(sign(key, grant))


def test_mutation_of_returned_body_does_not_mutate_grant():
    key, verifier, grant = fixture()
    actual = verifier.verify(sign(key, grant))
    body = actual.canonical_body()
    body["peer_key"] = "uid:6666"
    assert actual.peer_key == "uid:1001"


def test_reject_bare_grant_unsigned_and_wrong_input_type():
    key, verifier, grant = fixture()
    for token in (canonical(grant), {"grant": grant}, b"not-json", None):
        with pytest.raises(GrantVerificationError):
            verifier.verify(token)
