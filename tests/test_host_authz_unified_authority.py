"""Synthetic single-leader source tests, NOT physically independent custody."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from hashlib import sha256
import json
import shutil
import threading

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from portfolio_runtime.lantern.canonical import canonical_json_bytes
from vera_core.host_authz.bindings import (
    HostBindingSnapshot, PrincipalBinding, ProviderBinding,
)
from vera_core.host_authz.grants import (
    ApprovedGrant, SignedGrantVerifier, SIGNATURE_CONTEXT as GRANT_CONTEXT,
    SIGNED_GRANT_SCHEMA,
)
from vera_core.host_authz.service import ProviderAcknowledgement
from vera_core.host_authz.unified_authority import (
    RECEIPT_SCHEMA, SIGNATURE_CONTEXT, UnifiedAuthorityDenied,
    UnifiedAuthorityUnavailable, UnifiedHostAuthority,
    verify_provider_start_lease,
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def raw_pub(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw,
                                        serialization.PublicFormat.Raw)


class SyntheticLeader:
    """One in-process simulated witness; NOT antirollback or host authority."""

    def __init__(self, key):
        self.key = key
        self.sequence = 0
        self.seen = set()
        self.events = []
        self.full_events = []
        self.lock = threading.Lock()
        self.fail_after_commit = False
        self.tamper_response = False

    def allocate_event(self, encoded_request):
        request = json.loads(encoded_request)
        assert request["schema"] == "HOST_AUTHZ_UNIFIED_EVENT_REQUEST_V1"
        with self.lock:
            event_key = (request["kind"], request["event_digest"])
            if event_key in self.seen:
                raise OSError("exact event already allocated")
            self.seen.add(event_key)
            self.sequence += 1
            body = {
                "host_id": request["host_id"], "issuer_id": request["issuer_id"],
                "epoch": request["epoch"], "leader_epoch": request["leader_epoch"],
                "challenge": request["challenge"],
                "kind": request["kind"], "event_digest": request["event_digest"],
                "sequence": self.sequence, "approved": True,
            }
            self.events.append(body)
            self.full_events.append(request["event"])
            signature = self.key.sign(SIGNATURE_CONTEXT + canonical(body))
            if self.tamper_response:
                signature = b"x" * 64
            result = canonical({
                "schema": RECEIPT_SCHEMA,
                "body": body,
                "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode(),
            })
            if self.fail_after_commit:
                raise OSError("witness committed but ACK was lost")
            return result


def setup(tmp_path, *, witness=None, consent=True, issuer=None, provider=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    tmp_path.chmod(0o700)
    issuer = issuer if issuer is not None else Ed25519PrivateKey.generate()
    provider = provider if provider is not None else Ed25519PrivateKey.generate()
    witness_key = Ed25519PrivateKey.generate()
    model = PrincipalBinding("uid:1001", "model-A", "adapter-A", "runtime-A",
                             "subject-A", frozenset({"provider-A"}))
    provider_binding = ProviderBinding("provider-A", "instance-A",
                                       frozenset({"observe"}))
    bindings = HostBindingSnapshot("host-A", "issuer-A", 7,
                                    {model.peer_key: model},
                                    {provider_binding.provider_id: provider_binding})
    now = {"value": 2000}
    clock = lambda: now["value"]
    verifier = SignedGrantVerifier(raw_pub(issuer), issuer_id="issuer-A",
                                   host_id="host-A", epoch=7, trusted_clock=clock)
    leader = witness if witness is not None else SyntheticLeader(witness_key)
    # If reusing a leader, tests also reuse its actual signing key.
    if witness is not None:
        witness_key = witness.key
    def open_authority(path=None):
        return UnifiedHostAuthority(
            path or tmp_path / "unified.sqlite", bindings=bindings,
            grant_verifier=verifier, witness=leader,
            witness_public_key=raw_pub(witness_key),
            leader_epoch=11,
            provider_public_keys={"provider-A": raw_pub(provider)},
            trusted_clock=clock,
            consent_status=(lambda _grant, _now: consent) if consent is not None else None,
        )
    return {
        "authority": open_authority(), "open": open_authority,
        "issuer": issuer, "provider": provider, "witness": leader,
        "clock": now, "directory": tmp_path,
    }


def signed_grant(ctx, **overrides):
    body = {
        "grant_id": "grant-A", "issuer_id": "issuer-A", "host_id": "host-A",
        "epoch": 7, "peer_key": "uid:1001", "model_id": "model-A",
        "adapter_id": "adapter-A", "runtime_id": "runtime-A",
        "subject_id": "subject-A", "participant_id": "participant-A",
        "purpose": "approved observation", "provider_id": "provider-A",
        "provider_instance_id": "instance-A", "operation": "observe",
        "request_digest": sha256(canonical({"item": "synthetic"})).hexdigest(),
        "not_before": 1900, "expires_at": 2100,
    }
    body.update(overrides)
    grant = ApprovedGrant(**body)
    sig = ctx["issuer"].sign(GRANT_CONTEXT + canonical(grant.canonical_body()))
    return canonical({"schema": SIGNED_GRANT_SCHEMA,
                      "grant": grant.canonical_body(),
                      "signature": base64.urlsafe_b64encode(sig).rstrip(b"=").decode()}), grant


def claim(ctx, signed=None):
    if signed is None:
        signed, _ = signed_grant(ctx)
    return ctx["authority"].claim(signed, "uid:1001", {"item": "synthetic"})


def acknowledged(ctx, row):
    unsigned = ProviderAcknowledgement(
        row.effect_id, row.provider_id, row.provider_instance_id,
        row.claim_sequence, row.request_digest, "a" * 64, b"",
    )
    return replace(unsigned, receipt_signature=ctx["provider"].sign(
        b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\0" +
        canonical_json_bytes(unsigned.signed_body())))


def test_coherent_global_claim_start_complete_events_and_provider_lease(tmp_path):
    ctx = setup(tmp_path)
    row = claim(ctx)
    assert row.state == "CLAIMED" and row.claim_sequence == 1
    start_lease = ctx["authority"].start(row.grant_id)
    assert start_lease.sequence == 2
    assert ctx["authority"].read(row.grant_id).state == "STARTED"
    lease = verify_provider_start_lease(
        start_lease.raw, event=start_lease.event,
        witness_public_key=raw_pub(ctx["witness"].key),
        expected_host_id="host-A", expected_epoch=7,
        expected_leader_epoch=11,
        expected_effect_id=row.effect_id,
        expected_provider_id=row.provider_id,
        expected_provider_instance_id=row.provider_instance_id,
        expected_request_digest=row.request_digest, provider_now=2000,
    )
    assert lease.sequence == 2
    assert json.loads(lease.event)["participant_id"] == "participant-A"
    assert json.loads(lease.event)["purpose"] == "approved observation"
    assert json.loads(lease.event)["issued_at"] == 2000
    assert json.loads(lease.event)["start_deadline"] == 2030
    completed = ctx["authority"].complete(row.grant_id, acknowledged(ctx, row))
    assert completed.state == "COMPLETED"
    assert completed.provider_receipt_digest == "a" * 64
    assert [e["kind"] for e in ctx["witness"].events] == ["CLAIM", "START", "COMPLETE"]
    complete_event = ctx["witness"].full_events[-1]
    assert set(complete_event) == {
        "kind", "grant_id", "effect_id", "start_sequence", "receipt_digest",
        "provider_ack_body", "provider_ack_signature",
    }
    assert complete_event["provider_ack_body"]["effect_id"] == row.effect_id
    assert complete_event["provider_ack_body"]["provider_instance_id"] == row.provider_instance_id
    encoded_signature = complete_event["provider_ack_signature"]
    signature = base64.urlsafe_b64decode(encoded_signature + "=" * ((-len(encoded_signature)) % 4))
    ctx["provider"].public_key().verify(
        signature, b"VERA_HOST_AUTHZ_PROVIDER_ACK_V1\0" +
        canonical_json_bytes(complete_event["provider_ack_body"]))
    assert sha256(canonical(complete_event)).hexdigest() == ctx["witness"].events[-1]["event_digest"]
    with pytest.raises(UnifiedAuthorityDenied):
        ctx["authority"].start(row.grant_id)
    with pytest.raises(UnifiedAuthorityDenied):
        claim(ctx)


def test_revoke_before_start_denies_physical_lease(tmp_path):
    ctx = setup(tmp_path)
    signed, grant = signed_grant(ctx)
    row = claim(ctx, signed)
    revocation = ctx["authority"].revoke_scope(grant)
    assert revocation.sequence == 2
    with pytest.raises(UnifiedAuthorityDenied, match="revoked"):
        ctx["authority"].start(row.grant_id)
    assert ctx["authority"].read(row.grant_id).state == "CLAIMED"
    assert [e["kind"] for e in ctx["witness"].events] == ["CLAIM", "REVOKE_SCOPE"]


def test_revoke_after_start_cannot_retroactively_erase_physical_effect(tmp_path):
    ctx = setup(tmp_path)
    signed, grant = signed_grant(ctx)
    row = claim(ctx, signed)
    start = ctx["authority"].start(row.grant_id)
    assert start.sequence == 2
    revoked = ctx["authority"].revoke_scope(grant)
    assert revoked.sequence == 3
    assert ctx["authority"].complete(row.grant_id, acknowledged(ctx, row)).state == "COMPLETED"
    assert [e["kind"] for e in ctx["witness"].events] == [
        "CLAIM", "START", "REVOKE_SCOPE", "COMPLETE"]


def test_crash_after_start_reopens_without_retry_and_unknown_reconciles(tmp_path):
    ctx = setup(tmp_path)
    row = claim(ctx)
    ctx["authority"].start(row.grant_id)
    reopened = ctx["open"]()
    assert reopened.read(row.grant_id).state == "STARTED"
    with pytest.raises(UnifiedAuthorityDenied):
        reopened.start(row.grant_id)
    assert reopened.mark_unknown(row.grant_id).state == "UNKNOWN"
    with pytest.raises(UnifiedAuthorityDenied):
        reopened.complete(row.grant_id, acknowledged(ctx, row))


def test_no_witness_fails_closed_without_claim(tmp_path):
    ctx = setup(tmp_path)
    ctx["authority"]._witness = None  # source-host failure injection only
    with pytest.raises(UnifiedAuthorityUnavailable):
        claim(ctx)
    assert ctx["authority"].read("grant-A") is None


def test_wrong_signed_witness_key_denies_state_transition(tmp_path):
    ctx = setup(tmp_path)
    ctx["witness"].tamper_response = True
    with pytest.raises(UnifiedAuthorityUnavailable):
        claim(ctx)
    assert ctx["authority"].read("grant-A") is None


def test_lost_remote_receipt_fails_closed_without_local_commit(tmp_path):
    ctx = setup(tmp_path)
    ctx["witness"].fail_after_commit = True
    with pytest.raises(UnifiedAuthorityUnavailable):
        claim(ctx)
    assert ctx["authority"].read("grant-A") is None
    ctx["witness"].fail_after_commit = False
    with pytest.raises(UnifiedAuthorityUnavailable):
        claim(ctx)


def test_cloned_local_db_cannot_double_claim_under_one_external_leader(tmp_path):
    ctx = setup(tmp_path / "a")
    clone_path = tmp_path / "b" / "unified.sqlite"
    clone_path.parent.mkdir(mode=0o700)
    shutil.copyfile(ctx["authority"].path, clone_path)
    clone_path.chmod(0o600)
    clone = ctx["open"](clone_path)
    assert claim(ctx).state == "CLAIMED"
    with pytest.raises(UnifiedAuthorityUnavailable):
        clone.claim(signed_grant(ctx)[0], "uid:1001", {"item": "synthetic"})
    assert clone.read("grant-A") is None


def test_cloned_witness_and_db_still_split_brain_explicit_expected_red(tmp_path):
    """A signer+database cloned together defeats this source-only mechanism."""
    a = setup(tmp_path / "a")
    cloned_leader = SyntheticLeader(a["witness"].key)
    clone_dir = tmp_path / "clone"
    clone_dir.mkdir(mode=0o700)
    shutil.copyfile(a["authority"].path, clone_dir / "unified.sqlite")
    (clone_dir / "unified.sqlite").chmod(0o600)
    b = setup(clone_dir, witness=cloned_leader,
              issuer=a["issuer"], provider=a["provider"])
    assert claim(a).state == "CLAIMED"
    assert claim(b).state == "CLAIMED"
    assert a["witness"].sequence == cloned_leader.sequence == 1


def test_model_or_provider_rebinding_denied_before_event(tmp_path):
    ctx = setup(tmp_path)
    for changed in ({"peer_key": "uid:1002"},
                    {"provider_instance_id": "replacement"},
                    {"model_id": "model-B"}):
        signed, _ = signed_grant(ctx, **changed)
        with pytest.raises(UnifiedAuthorityDenied):
            claim(ctx, signed)
    assert ctx["witness"].sequence == 0


def test_forged_provider_ack_keeps_effect_started(tmp_path):
    ctx = setup(tmp_path)
    row = claim(ctx)
    ctx["authority"].start(row.grant_id)
    valid = acknowledged(ctx, row)
    forged = replace(valid, receipt_signature=b"X" * 64)
    with pytest.raises(UnifiedAuthorityDenied):
        ctx["authority"].complete(row.grant_id, forged)
    assert ctx["authority"].read(row.grant_id).state == "STARTED"


def test_provider_rejects_start_lease_tampering_retarget_and_expiry(tmp_path):
    ctx = setup(tmp_path)
    row = claim(ctx)
    lease = ctx["authority"].start(row.grant_id)
    expected = {
        "event": lease.event,
        "witness_public_key": raw_pub(ctx["witness"].key),
        "expected_host_id": "host-A", "expected_epoch": 7,
        "expected_leader_epoch": 11,
        "expected_effect_id": row.effect_id,
        "expected_provider_id": row.provider_id,
        "expected_provider_instance_id": row.provider_instance_id,
        "expected_request_digest": row.request_digest,
        "provider_now": 2000,
    }
    forged = json.loads(lease.event)
    forged["participant_id"] = "another-participant"
    with pytest.raises(UnifiedAuthorityDenied):
        verify_provider_start_lease(lease.raw, **{**expected, "event": canonical(forged)})
    with pytest.raises(UnifiedAuthorityDenied):
        verify_provider_start_lease(lease.raw, **{**expected,
                                                 "expected_provider_instance_id": "clone-instance"})
    with pytest.raises(UnifiedAuthorityDenied):
        verify_provider_start_lease(lease.raw, **{**expected, "provider_now": 2100})
    assert verify_provider_start_lease(
        lease.raw, **{**expected, "provider_now": 2030}).sequence == lease.sequence
    with pytest.raises(UnifiedAuthorityDenied):
        verify_provider_start_lease(lease.raw, **{**expected, "provider_now": 2031})
    with pytest.raises(UnifiedAuthorityDenied):
        verify_provider_start_lease(lease.raw, **{**expected, "expected_epoch": 8})
    with pytest.raises(UnifiedAuthorityDenied):
        verify_provider_start_lease(lease.raw, **{**expected, "expected_leader_epoch": 12})
    with pytest.raises(UnifiedAuthorityDenied):
        verify_provider_start_lease(lease.raw, **{**expected,
                                  "witness_public_key": raw_pub(Ed25519PrivateKey.generate())})


def test_start_deadline_cannot_outlive_grant_and_denies_delayed_dispatch(tmp_path):
    ctx = setup(tmp_path)
    signed, _ = signed_grant(ctx, expires_at=2005)
    row = claim(ctx, signed)
    lease = ctx["authority"].start(row.grant_id)
    event = json.loads(lease.event)
    assert event["issued_at"] == 2000
    assert event["start_deadline"] == 2004
    expected = dict(
        event=lease.event, witness_public_key=raw_pub(ctx["witness"].key),
        expected_host_id="host-A", expected_epoch=7, expected_leader_epoch=11,
        expected_effect_id=row.effect_id, expected_provider_id=row.provider_id,
        expected_provider_instance_id=row.provider_instance_id,
        expected_request_digest=row.request_digest,
    )
    assert verify_provider_start_lease(lease.raw, **expected, provider_now=2004).sequence == 2
    with pytest.raises(UnifiedAuthorityDenied):
        verify_provider_start_lease(lease.raw, **expected, provider_now=2005)


def test_concurrent_revocation_and_start_share_same_ordered_transaction(tmp_path):
    ctx = setup(tmp_path)
    signed, grant = signed_grant(ctx)
    row = claim(ctx, signed)
    gate = threading.Barrier(2)
    def do_start():
        gate.wait()
        try:
            return "start", ctx["authority"].start(row.grant_id).sequence
        except UnifiedAuthorityDenied:
            return "denied", None
    def do_revoke():
        gate.wait()
        return "revoke", ctx["authority"].revoke_scope(grant).sequence
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(do_start)
        b = pool.submit(do_revoke)
        x, y = a.result(timeout=5), b.result(timeout=5)
    assert y[0] == "revoke" and y[1] in (2, 3)
    if x[0] == "start":
        assert x[1] == 2 and y[1] == 3
        assert ctx["authority"].read(row.grant_id).state == "STARTED"
    else:
        assert x == ("denied", None) and y[1] == 2
        assert ctx["authority"].read(row.grant_id).state == "CLAIMED"


def test_changed_authority_epoch_or_issuer_rejected(tmp_path):
    ctx = setup(tmp_path)
    bad = signed_grant(ctx, epoch=8)[0]
    with pytest.raises(UnifiedAuthorityDenied):
        claim(ctx, bad)


def test_existing_store_pins_issuer_witness_provider_keys_and_leader_epoch(tmp_path):
    ctx = setup(tmp_path)
    assert ctx["open"]().read("grant-A") is None
    for replacements in (
        {"witness": ctx["witness"], "issuer": ctx["issuer"]},
        {"issuer": ctx["issuer"], "provider": ctx["provider"]},
        {"witness": ctx["witness"], "provider": ctx["provider"]},
    ):
        with pytest.raises(UnifiedAuthorityDenied, match="persisted host authority mismatch"):
            setup(tmp_path, **replacements)
    current = ctx["authority"]
    with pytest.raises(UnifiedAuthorityDenied, match="persisted host authority mismatch"):
        UnifiedHostAuthority(
            current.path, bindings=current.bindings,
            grant_verifier=current.grant_verifier,
            witness=ctx["witness"],
            witness_public_key=raw_pub(ctx["witness"].key),
            leader_epoch=12,
            provider_public_keys={"provider-A": raw_pub(ctx["provider"])},
            trusted_clock=current._clock,
            consent_status=current._consent_status,
        )
