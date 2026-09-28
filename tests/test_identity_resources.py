from vera_identity import load_json_resource, resource_path


def test_identity_resource_is_local_and_parseable():
    relative = "architecture/identity/VERA_PROJECT_IDENTITY_V1.json"
    path = resource_path(relative)
    assert "packages/vera_identity" in path.as_posix()
    payload = load_json_resource(relative)
    assert payload["schema"] == "VERA_PROJECT_IDENTITY_V1"
    assert payload["project_name"] == "V.E.R.A."


def test_resource_loader_rejects_escape():
    try:
        resource_path("../../outside.json")
    except ValueError:
        pass
    else:
        raise AssertionError("resource loader accepted path traversal")


def test_governed_identity_snapshot_is_local_and_bounded():
    payload = load_json_resource("architecture/identity/VERA_IDENTITY_SYSTEM_SNAPSHOT_V1.json")
    assert payload["schema"] == "VERA_IDENTITY_SYSTEM_SNAPSHOT_V1"
    assert payload["identity"]["referent"] == "Vera"
    assert payload["memory_privacy"]["autobiographical_admission"] == "DEFAULT_DENY_UNLESS_CURRENT_EVIDENCE_AND_PRIVACY_GATES_PASS"
    assert "phenomenological" in payload["claim_ceiling"].lower()


def test_governed_identity_snapshot_schema_is_local():
    schema = load_json_resource("schemas/vera_identity_system_snapshot_v1.schema.json")
    assert schema["properties"]["schema"]["const"] == "VERA_IDENTITY_SYSTEM_SNAPSHOT_V1"
    assert schema["properties"]["identity"]["properties"]["referent"]["const"] == "Vera"
