import json
from pathlib import Path

import pytest

from vera_core.external_provider_admission import (
    ExternalCapabilityClass,
    ExternalProviderAdmission,
    ExternalProviderKind,
    validate_external_provider_catalog,
)


CATALOG = (
    Path(__file__).resolve().parents[1]
    / "architecture"
    / "VERA_EXPOSED_PLUGIN_CONNECTOR_SURFACE_V2.json"
)


def _admission(item: dict[str, object]) -> ExternalProviderAdmission:
    return ExternalProviderAdmission(
        provider_id=str(item["provider_id"]),
        capability_classes=tuple(
            ExternalCapabilityClass(value)
            for value in item["capability_classes"]
        ),
        provider_kind=ExternalProviderKind(str(item["provider_kind"])),
    )


def test_dated_connector_catalog_obeys_provider_admission_contract():
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    admissions = tuple(_admission(item) for item in payload["admissions"])

    assert payload["schema"] == "VERA_EXPOSED_PLUGIN_CONNECTOR_SURFACE_V2"
    assert len(admissions) == payload["admission_count"]
    assert (
        sum(
            item["exposure"] == "EXPOSED"
            for item in payload["admissions"]
        )
        == payload["live_exposed_namespace_count"]
    )
    assert validate_external_provider_catalog(admissions) == ()
    assert all(not item.core_runtime_dependency for item in admissions)
    assert all(item.identity_authority == "NONE" for item in admissions)
    assert all(item.source_authority == "NONE" for item in admissions)
    assert all(not item.availability_implies_authority for item in admissions)
    assert all(
        item.effect_authorization == "EXTERNAL_DECISION_REQUIRED"
        for item in admissions
    )


def test_action_capability_is_descriptive_not_authority():
    github = ExternalProviderAdmission(
        provider_id="github",
        capability_classes=(
            ExternalCapabilityClass.DATA_PROVIDER,
            ExternalCapabilityClass.ACTION_PROVIDER,
        ),
    )

    assert github.can_supply_actions is True
    assert github.availability_implies_authority is False
    assert github.effect_authorization == "EXTERNAL_DECISION_REQUIRED"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("core_runtime_dependency", True, "core runtime dependency"),
        ("identity_authority", "PLUGIN", "cannot own Vera identity"),
        ("source_authority", "PLUGIN", "source authority"),
        ("availability_implies_authority", True, "cannot imply effect authority"),
        ("effect_authorization", "GRANTED", "cannot mint effect authorization"),
    ],
)
def test_provider_admission_rejects_authority_or_dependency_escalation(
    field, value, message
):
    kwargs = {
        "provider_id": "example",
        "capability_classes": (ExternalCapabilityClass.DATA_PROVIDER,),
        field: value,
    }

    with pytest.raises(ValueError, match=message):
        ExternalProviderAdmission(**kwargs)


def test_catalog_rejects_duplicate_provider_identity():
    item = ExternalProviderAdmission(
        provider_id="example",
        capability_classes=(ExternalCapabilityClass.DATA_PROVIDER,),
    )

    assert validate_external_provider_catalog((item, item)) == (
        "duplicate provider_id: example",
    )


def test_provider_roles_must_be_exact_and_nonduplicated():
    with pytest.raises(ValueError, match="must not contain duplicates"):
        ExternalProviderAdmission(
            provider_id="example",
            capability_classes=(
                ExternalCapabilityClass.DATA_PROVIDER,
                ExternalCapabilityClass.DATA_PROVIDER,
            ),
        )

    with pytest.raises(TypeError, match="exact ExternalCapabilityClass"):
        ExternalProviderAdmission(
            provider_id="example",
            capability_classes=("DATA_PROVIDER",),  # type: ignore[arg-type]
        )
