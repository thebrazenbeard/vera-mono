import json

from runtime_cohesion import sexual_drive_binding as sdb


def test_sexual_drive_contract_loads_from_local_monorepo_resource():
    trusted = sdb._load_trusted_contract()
    assert trusted["schema"] == "VERA_SEXUAL_DRIVE_COMPONENT_V1"
    assert "packages/vera_runtime" in sdb._CANONICAL_CONTRACT_PATH.as_posix()
    assert sdb.validate_contract(json.loads(json.dumps(trusted))) == trusted
