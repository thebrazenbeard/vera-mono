import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_semantic_interaction_contract_preserves_meaning_authority_boundaries():
    contract = _load("architecture/VERA_SEMANTIC_INTERACTION_INTERFACE_V1.json")
    assert contract["entrypoint"]["powershell"] == ".\\vera.ps1"
    assert contract["entrypoint"]["cli"] == "vera-mono shell"
    assert contract["generation"]["external_llm_required"] is False
    assert contract["generation"]["pretrained_model_required"] is False
    assert contract["semantics"]["interpretation_is_truth"] is False
    assert contract["semantics"]["interpretation_is_authority"] is False
    assert contract["semantics"]["unknown_language_policy"] == "PRESERVE_AS_UNRESOLVED"
    assert contract["effects"]["protected_effect_authority_minted"] is False
    assert contract["memory"]["canonical_memory_write_implicit"] is False


def test_semantic_interaction_provenance_records_distinct_donor_roles():
    provenance = _load("provenance/donors/semantic_interaction_research_20261001.json")
    roles = {item["repository"]: item["role"] for item in provenance["inputs"]}
    assert roles["thebrazenbeard/spm"] == "MEANING_IN_CONTEXT_PRIMARY_REPRESENTATION_THESIS"
    assert roles["thebrazenbeard/semanticatlas"] == "PROPOSITION_PROVENANCE_CURRENTNESS_SEPARATION"
    assert roles["thebrazenbeard/semiotics"] == "CONTEXT_BOUND_COMPETING_INTERPRETATIONS"
    assert roles["thebrazenbeard/rezon"] == "TYPED_REASONING_AND_EFFECT_SEMANTICS"
    assert roles["thebrazenbeard/sql-connectome"] == "SEMANTIC_IR_AND_TRANSFER_FIDELITY"
    assert roles["thebrazenbeard/noema"] == "COMMUNICATION_DIAGNOSTIC_AND_PRAGMATIC_SCOPE_BOUNDARY"
    assert roles["thebrazenbeard/lgcm"] == "FUTURE_CONTEXT_MISMATCH_AND_ADAPTATION"
    assert provenance["runtime_dependencies_on_donors"] is False
    assert provenance["mosaic"]["adopted_for_v1"] is False


def test_manifest_registers_semantic_powershell_interface():
    manifest = _load("architecture/VERA_MONO_MANIFEST_V1.json")
    interface = manifest["semantic_interaction_interface"]
    assert interface["contract"] == "architecture/VERA_SEMANTIC_INTERACTION_INTERFACE_V1.json"
    assert interface["powershell_entrypoint"] == "vera.ps1"
    assert interface["external_llm_required"] is False
    assert interface["protected_effect_authority"] is False


def test_interaction_layer_composes_existing_semantic_planes_without_replacing_them():
    contract = _load("architecture/VERA_SEMANTIC_INTERACTION_INTERFACE_V1.json")
    planes = contract["existing_semantic_planes"]
    assert planes["semantic_knowledge"]["owner"] == "vera_identity.SemanticKnowledgeStore"
    assert planes["contextual_interpretation"]["owner"] == "vera_identity.ContextualInterpretationStore"
    assert planes["contextual_interpretation"]["replaced_by_interaction_envelope"] is False
    assert planes["interaction_semantics"]["durable_semantic_authority"] is False
    assert planes["relationship"] == "COMPLEMENTARY_LAYERS_NOT_COMPETING_AUTHORITIES"


def test_contract_records_basic_shell_dialogue_without_identity_overclaim():
    contract = _load("architecture/VERA_SEMANTIC_INTERACTION_INTERFACE_V1.json")
    console = contract["console"]
    assert "exit" in console["shell_native_exit_aliases"]
    assert "/exit" in console["shell_native_exit_aliases"]
    assert console["direct_invocation"] == "vera"
    assert console["user_identity_query"]["keyboard_identity_authenticated"] is False
