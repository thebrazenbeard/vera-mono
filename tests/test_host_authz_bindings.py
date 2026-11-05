import pytest

from vera_core.host_authz.bindings import (
    HostBindingError,
    HostBindingSnapshot,
    PrincipalBinding,
    ProviderBinding,
)


def _principal(peer="uid:1001", *, model="model-a"):
    return PrincipalBinding(
        peer_key=peer,
        model_id=model,
        adapter_id="adapter-a",
        runtime_id="runtime-a",
        subject_id="subject-a",
        allowed_provider_ids={"provider-a"},
    )


def _provider():
    return ProviderBinding(
        provider_id="provider-a",
        provider_instance_id="device-a/instance-1",
        allowed_operations={"measure"},
    )


def _snapshot():
    return HostBindingSnapshot(
        host_id="host-a",
        issuer_id="issuer-a",
        epoch=5,
        principals={"uid:1001": _principal()},
        providers={"provider-a": _provider()},
    )


def test_exact_kernel_peer_maps_to_immutable_authority_and_provider():
    snap = _snapshot()
    principal = snap.principal_for_peer("uid:1001")
    assert principal.model_id == "model-a"
    assert principal.allowed_provider_ids == frozenset({"provider-a"})
    assert snap.provider_for(principal, "provider-a", "measure").provider_instance_id == "device-a/instance-1"


def test_unknown_peer_provider_or_operation_fail_closed():
    snap = _snapshot()
    with pytest.raises(HostBindingError):
        snap.principal_for_peer("uid:1002")
    with pytest.raises(HostBindingError):
        snap.principal_for_peer(None)
    principal = snap.principal_for_peer("uid:1001")
    with pytest.raises(HostBindingError):
        snap.provider_for(principal, "provider-b", "measure")
    with pytest.raises(HostBindingError):
        snap.provider_for(principal, "provider-a", "write")


def test_request_supplied_principal_cannot_skip_snapshot_peer_resolution():
    snap = _snapshot()
    forged = _principal()
    assert forged == snap.principal_for_peer("uid:1001")
    with pytest.raises(HostBindingError):
        snap.provider_for(forged, "provider-a", "measure")


def test_distinct_authenticated_peers_do_not_transfer_model_permissions():
    model_b = PrincipalBinding("uid:1002", "model-b", "adapter-b", "runtime-b",
                               "subject-b", {"provider-b"})
    snap = HostBindingSnapshot(
        "host-a", "issuer-a", 5,
        {"uid:1001": _principal(), "uid:1002": model_b},
        {"provider-a": _provider(),
         "provider-b": ProviderBinding("provider-b", "device-b/instance-2", {"observe"})},
    )
    a = snap.principal_for_peer("uid:1001")
    b = snap.principal_for_peer("uid:1002")
    assert a.model_id != b.model_id
    assert snap.provider_for(b, "provider-b", "observe").provider_id == "provider-b"
    with pytest.raises(HostBindingError):
        snap.provider_for(a, "provider-b", "observe")
    with pytest.raises(HostBindingError):
        snap.provider_for(b, "provider-a", "measure")
    # Structurally equal principals from another host are never accepted.
    another_host = HostBindingSnapshot("host-other", "issuer-a", 5,
                                     {"uid:1001": _principal()},
                                     {"provider-a": _provider()})
    with pytest.raises(HostBindingError):
        snap.provider_for(another_host.principal_for_peer("uid:1001"),
                          "provider-a", "measure")


def test_snapshot_copies_nested_mutable_sources_and_rebuilds_principals():
    principal = _principal()
    principals = {"uid:1001": principal}
    operations = {"measure"}
    provider = ProviderBinding("provider-a", "device-a/instance-1", operations)
    providers = {"provider-a": provider}
    snap = HostBindingSnapshot("host-a", "issuer-a", 5, principals, providers)
    operations.clear()
    principals.clear()
    providers.clear()
    with pytest.raises(AttributeError):
        object.__setattr__(principal, "model_id", "tampered-after-build")
    with pytest.raises(AttributeError):
        object.__setattr__(provider, "provider_instance_id", "tampered-after-build")
    assert snap.principal_for_peer("uid:1001").model_id == "model-a"
    assert snap.provider_for(snap.principal_for_peer("uid:1001"), "provider-a", "measure").provider_instance_id == "device-a/instance-1"
    with pytest.raises(TypeError):
        snap.principals["uid:1002"] = _principal("uid:1002")
    with pytest.raises(AttributeError):
        object.__setattr__(snap, "host_id", "host-b")
    with pytest.raises(AttributeError):
        object.__setattr__(snap.principal_for_peer("uid:1001"), "model_id", "hostile")


def test_mapping_key_identity_mismatch_and_duplicate_model_binding_rejected():
    with pytest.raises(ValueError):
        HostBindingSnapshot("host-a", "issuer-a", 5,
                            {"uid:another": _principal()}, {"provider-a": _provider()})
    with pytest.raises(ValueError):
        HostBindingSnapshot("host-a", "issuer-a", 5,
                            {"uid:1001": _principal(), "uid:1002": _principal("uid:1002")},
                            {"provider-a": _provider()})
    with pytest.raises(ValueError):
        HostBindingSnapshot("host-a", "issuer-a", 5,
                            {"uid:1001": _principal()}, {"provider-b": _provider()})


@pytest.mark.parametrize("field,bad", [("host_id", ""), ("issuer_id", None), ("epoch", 0), ("epoch", True)])
def test_host_identity_and_epoch_must_be_exact(field, bad):
    kwargs = dict(host_id="host-a", issuer_id="issuer-a", epoch=5,
                  principals={"uid:1001": _principal()}, providers={"provider-a": _provider()})
    kwargs[field] = bad
    with pytest.raises((TypeError, ValueError)):
        HostBindingSnapshot(**kwargs)


def test_reject_subclasses_and_mutable_collaborator_injection():
    class SubPrincipal(PrincipalBinding):
        pass

    class EvilMap(dict):
        pass

    with pytest.raises(TypeError):
        HostBindingSnapshot("host-a", "issuer-a", 5,
                            {"uid:1001": SubPrincipal(**vars_for_principal())},
                            {"provider-a": _provider()})
    with pytest.raises(TypeError):
        HostBindingSnapshot("host-a", "issuer-a", 5,
                            EvilMap({"uid:1001": _principal()}),
                            {"provider-a": _provider()})


def vars_for_principal():
    return dict(peer_key="uid:1001", model_id="model-a", adapter_id="adapter-a",
                runtime_id="runtime-a", subject_id="subject-a",
                allowed_provider_ids={"provider-a"})
