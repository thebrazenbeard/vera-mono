import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "architecture" / "VERA_EXPOSED_PLUGIN_CONNECTOR_SURFACE_V1.json"


def test_exposed_connector_surface_is_complete_unique_and_bounded():
    payload = json.loads(SURFACE.read_text(encoding="utf-8"))
    connectors = payload["connectors"]
    names = [item["name"] for item in connectors]
    assert payload["count"] == 32 == len(names)
    assert len(names) == len(set(names))
    assert payload["observation_basis"] == "PATRICK_DIRECT_ENUMERATION_IN_CURRENT_CHAT"
    assert "Remote Desktop Commander" in names
    remote = next(item for item in connectors if item["name"] == "Remote Desktop Commander")
    assert remote["use_policy"] == "DO_NOT_USE_RATE_LIMITED_BY_PATRICK"
    assert "NOT PROOF OF AUTHORIZATION" in payload["claim_ceiling"]
