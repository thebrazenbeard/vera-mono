from vera_core.registry import CAPABILITIES, capability, validate_registry


def test_registry_is_local_and_valid():
    assert validate_registry() == ()
    assert {item.capability_id for item in CAPABILITIES} == {
        "reasoning",
        "identity_resources",
        "runtime_cohesion",
        "protocol",
        "tul_fixture",
        "portfolio_runtime",
        "coordination",
        "memory",
        "assurance",
        "pc_connection",
        "control",
        "recovery",
    }
    assert all("github.com/" not in item.import_root for item in CAPABILITIES)
    assert all(not item.import_root.startswith("thebrazenbeard/") for item in CAPABILITIES)


def test_reasoning_resolves_to_local_rezon_package():
    item = capability("reasoning")
    assert item.package == "rezon"
    assert item.import_root == "rezon"
