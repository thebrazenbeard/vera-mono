import json

from runtime_cohesion import sexual_drive_binding as sdb


def test_sexual_drive_contract_loads_from_local_monorepo_resource():
    trusted = sdb._load_trusted_contract()
    assert trusted["schema"] == "VERA_SEXUAL_DRIVE_COMPONENT_V1"
    assert "packages/vera_runtime" in sdb._CANONICAL_CONTRACT_PATH.as_posix()
    assert sdb.validate_contract(json.loads(json.dumps(trusted))) == trusted


def test_sexual_drive_component_points_to_local_monorepo_source():
    trusted = sdb._load_trusted_contract()
    component = sdb.build_component_ref(trusted, observed_at="2026-09-23T00:00:00Z")
    assert component.source_locator.startswith("monorepo:thebrazenbeard/vera-mono:")
    assert component.source_revision == sdb._PINNED_CONTRACT_GIT_BLOB
    assert component.payload_ref.startswith("monorepo://thebrazenbeard/vera-mono/")
    assert component.currentness_basis == "MONOREPO_LOCAL_PINNED_SOURCE"
