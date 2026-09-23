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
