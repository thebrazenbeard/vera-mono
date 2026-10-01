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


def test_capability_mesh_covers_required_semantic_domains_without_duplicate_owners():
    mesh_path = (
        Path(__file__).resolve().parents[1]
        / "architecture"
        / "VERA_CAPABILITY_MESH_V1.json"
    )
    payload = json.loads(mesh_path.read_text(encoding="utf-8"))
    ids = [item["id"] for item in payload["domains"]]

    assert len(ids) == len(set(ids))
    assert {
        "identity_self_model",
        "current_memory",
        "deep_historical_memory",
        "provenance",
        "semantics",
        "pragmatics",
        "reasoning",
        "metacognition",
        "planning",
        "salience_attention",
        "affect",
        "conation_motivation",
        "homeostasis_interoception_analogues",
        "temporal_state",
        "learning_adaptation",
        "continual_learning",
        "behavior_generation",
        "io",
        "ingestion",
        "coordination",
        "recovery",
        "runtime",
        "authorization_effect_control",
        "security",
        "external_tools",
        "workstation_interaction",
        "multi_device_transport",
        "databases_state_stores",
        "model_provider_abstraction",
        "qualification",
        "regression_protection",
        "error_correction",
        "adversarial_review",
        "evidence_custody",
        "project_orchestration",
    }.issubset(ids)

    for domain in payload["domains"]:
        assert domain["semantic_owner"]
        assert domain["implementation"]
        assert domain["authority_owner"]
        assert domain["status"]


def test_provider_admission_contract_and_manifest_are_bound():
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (root / "architecture" / "VERA_EXTERNAL_PROVIDER_ADMISSION_V1.json").read_text(
            encoding="utf-8"
        )
    )
    manifest = json.loads(
        (root / "architecture" / "VERA_MONO_MANIFEST_V1.json").read_text(
            encoding="utf-8"
        )
    )

    assert contract["implementation"] == (
        "packages/vera_core/src/vera_core/external_provider_admission.py"
    )
    assert contract["composition"]["provider_specific_names_in_core_contract"] is False
    assert contract["invariants"]["provider_admission_may_create_core_runtime_dependency"] is False
    assert contract["invariants"]["availability_may_imply_effect_authority"] is False

    provider = manifest["external_provider_admission"]
    assert provider["contract"] == "architecture/VERA_EXTERNAL_PROVIDER_ADMISSION_V1.json"
    assert provider["implementation"] == "vera_core.external_provider_admission"
    assert provider["core_runtime_dependency_created_by_admission"] is False
    assert provider["effect_authority_created_by_admission"] is False

    mesh = manifest["capability_mesh"]
    assert mesh["contract"] == "architecture/VERA_CAPABILITY_MESH_V1.json"
    assert mesh["semantic_owner_map_is_runtime_registry"] is False
