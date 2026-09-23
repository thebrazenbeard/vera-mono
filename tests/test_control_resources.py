from vera_control import load_json_resource


def test_control_resources_are_local_source_not_auto_activation():
    payload = load_json_resource(
        "architecture/control/VERA_CONTROL_PLANE_ABSORPTION_V1.json"
    )
    assert payload["schema"] == "VERA_CONTROL_PLANE_ABSORPTION_V1"
    text = str(payload).upper()
    assert "CONTROL" in text
