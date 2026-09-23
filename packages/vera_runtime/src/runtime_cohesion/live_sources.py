from __future__ import annotations

from typing import Any, Mapping


ROUTE_BINDING_STATUSES = {"VERIFIED_EXACT", "UNRESOLVED", "CONFLICT", "HISTORICAL_PROVIDER_PROJECTION"}


def validate_source_registry(registry: Mapping[str, Any]) -> tuple[str, ...]:
    """Validate the non-normative live-source directory without promoting it.

    The registry controls discovery/classification only. It is deliberately an
    open-world operational directory, not a source of current authority merely
    because an entry is present.
    """
    errors: list[str] = []
    if registry.get("schema") != "VERA_RUNTIME_SOURCE_REGISTRY_V1":
        errors.append("unexpected source-registry schema")

    snapshot_raw = registry.get("owner_repository_snapshot")
    if not isinstance(snapshot_raw, list) or not snapshot_raw:
        errors.append("owner_repository_snapshot must be a non-empty list")
        snapshot: set[str] = set()
    else:
        snapshot = {value for value in snapshot_raw if isinstance(value, str) and value}
        if len(snapshot) != len(snapshot_raw):
            errors.append("owner_repository_snapshot contains duplicate or invalid repository names")

    source_rows = registry.get("repository_sources")
    unbound_rows = registry.get("unbound_repositories")
    if not isinstance(source_rows, list):
        errors.append("repository_sources must be a list")
        source_rows = []
    if not isinstance(unbound_rows, list):
        errors.append("unbound_repositories must be a list")
        unbound_rows = []

    bound: set[str] = set()
    for row in source_rows:
        if not isinstance(row, Mapping):
            errors.append("repository source row must be an object")
            continue
        repository = row.get("repository")
        if not isinstance(repository, str) or not repository:
            errors.append("repository source row missing repository")
            continue
        if repository in bound:
            errors.append(f"duplicate repository source: {repository}")
        bound.add(repository)
        for field in ("runtime_role", "activation_mode", "authority_ceiling", "privacy_class"):
            if not isinstance(row.get(field), str) or not row.get(field):
                errors.append(f"{repository}: missing {field}")
        if row.get("availability_implies_activation") is not False:
            errors.append(f"{repository}: availability_implies_activation must be false")

    unbound: set[str] = set()
    for row in unbound_rows:
        if not isinstance(row, Mapping):
            errors.append("unbound repository row must be an object")
            continue
        repository = row.get("repository")
        if not isinstance(repository, str) or not repository:
            errors.append("unbound repository row missing repository")
            continue
        if repository in unbound:
            errors.append(f"duplicate unbound repository: {repository}")
        unbound.add(repository)
        if row.get("activation_mode") != "NO_AUTO_BIND":
            errors.append(f"{repository}: unbound repository must use NO_AUTO_BIND")
        if row.get("availability_implies_activation") is not False:
            errors.append(f"{repository}: availability_implies_activation must be false")

    overlap = bound & unbound
    if overlap:
        errors.append(f"repositories cannot be both bound and unbound: {sorted(overlap)!r}")
    classified = bound | unbound
    if snapshot and classified != snapshot:
        missing = sorted(snapshot - classified)
        extra = sorted(classified - snapshot)
        errors.append(f"repository snapshot classification mismatch: missing={missing!r} extra={extra!r}")

    control_rows = [
        row for row in source_rows
        if isinstance(row, Mapping) and row.get("runtime_role") == "CURRENT_CONTROL_SOURCE"
    ]
    if len(control_rows) != 1:
        errors.append("exactly one CURRENT_CONTROL_SOURCE is required")
    elif (
        control_rows[0].get("repository") != "thebrazenbeard/vera-control-plane"
        or control_rows[0].get("activation_mode") != "EXACT_R10_CONTROL_LOAD"
    ):
        errors.append("CURRENT_CONTROL_SOURCE must be vera-control-plane with EXACT_R10_CONTROL_LOAD")

    portfolio = registry.get("portfolio_reconciliation")
    if not isinstance(portfolio, Mapping):
        errors.append("portfolio_reconciliation is required")
    else:
        counts = portfolio.get("classification_counts")
        if not isinstance(counts, Mapping):
            errors.append("portfolio_reconciliation.classification_counts is required")
        else:
            if counts.get("total") != len(snapshot):
                errors.append("portfolio repository count must match owner_repository_snapshot")
            if counts.get("classified_source_rows") != len(bound):
                errors.append("portfolio classified_source_rows must match repository_sources")
            if counts.get("no_auto_bind") != len(unbound):
                errors.append("portfolio no_auto_bind must match unbound_repositories")
        current_inventory = portfolio.get("current_inventory")
        if not isinstance(current_inventory, Mapping):
            errors.append("portfolio_reconciliation.current_inventory is required")
        elif current_inventory.get("repository_count") != len(snapshot):
            errors.append("current inventory repository_count must match owner_repository_snapshot")
        predecessor = portfolio.get("predecessor_59_lineage")
        if not isinstance(predecessor, Mapping):
            errors.append("predecessor_59_lineage is required for provenance")
        else:
            discovery = predecessor.get("discovery")
            roots = predecessor.get("roots")
            if not isinstance(discovery, Mapping) or discovery.get("commit") != "2881a94c7eb3c83a34b0c00bab739b41c1d99b6d" or discovery.get("blob_sha") != "71b9f8deaf1079d5078b19e5bbddb743fd636437":
                errors.append("Discovery predecessor portfolio binding mismatch")
            if not isinstance(roots, Mapping) or roots.get("commit") != "a6994b415336bc179a41aad0ac9eec403d60f93c" or roots.get("blob_sha") != "ccac62eac08012269fec46669bce981b96a0f41d":
                errors.append("Roots predecessor lineage binding mismatch")

    for repository in ("thebrazenbeard/vera-apk", "thebrazenbeard/vera-habitat", "thebrazenbeard/hc-brain", "thebrazenbeard/self", "thebrazenbeard/bt2"):
        if repository not in unbound:
            errors.append(f"{repository}: expected NO_AUTO_BIND classification")
    if "thebrazenbeard/voss" not in bound:
        errors.append("voss must be bound as review-only source")
    for repository in (
        "thebrazenbeard/meso-crct",
        "thebrazenbeard/unbound-sol",
        "thebrazenbeard/RepairTracker",
        "thebrazenbeard/freerowcochkar",
    ):
        if repository not in bound:
            errors.append(f"{repository}: expected current portfolio source classification")

    route_case = registry.get("observed_cross_provider_cases", {}).get("bus_to_radar_writer_route")
    if not isinstance(route_case, Mapping):
        errors.append("bus_to_radar_writer_route evidence is required")
    else:
        if route_case.get("source_observed_value") != "bus/vera-v2":
            errors.append("current Bus Vera writer lane drift")
        if route_case.get("provider_projection_observed_value") != "bus/vera-sol-v1":
            errors.append("historical Supabase Vera projection drift")
        if route_case.get("provider_projection_authoritative_for_current_routing") is not False:
            errors.append("historical provider projection must not be current routing authority")
        if route_case.get("classification") != "HISTORICAL_PROVIDER_PROJECTION_NON_AUTHORITATIVE_FOR_CURRENT_ROUTING":
            errors.append("historical provider projection classification mismatch")

    providers = registry.get("provider_sources")
    if not isinstance(providers, Mapping):
        errors.append("provider_sources must be an object")
        return tuple(errors)

    supabase = providers.get("supabase_vera")
    if not isinstance(supabase, Mapping):
        errors.append("provider_sources.supabase_vera is required")
    else:
        if supabase.get("project_id") != "klmbpaigzeguvnpccqzz":
            errors.append("Vera Supabase project id drift")
        if supabase.get("activation_mode") != "PROVIDER_READBACK_ONLY":
            errors.append("Vera Supabase must remain PROVIDER_READBACK_ONLY")
        if supabase.get("availability_implies_activation") is not False:
            errors.append("Vera Supabase availability must not imply activation")

    drive = providers.get("google_drive")
    if not isinstance(drive, Mapping):
        errors.append("provider_sources.google_drive is required")
    else:
        if drive.get("activation_mode") != "POINTER_FIRST_DURABLE_READBACK":
            errors.append("Google Drive must remain POINTER_FIRST_DURABLE_READBACK")
        if drive.get("availability_implies_activation") is not False:
            errors.append("Google Drive availability must not imply activation")

    return tuple(errors)


def evaluate_route_binding(expected_route: Any, observed_route: Any) -> dict[str, Any]:
    """Compare exact routing values without turning a projection into control proof."""
    if not isinstance(expected_route, str) or not expected_route or not isinstance(observed_route, str) or not observed_route:
        return {
            "status": "UNRESOLVED",
            "projection_matches": False,
            "current_route_established": False,
            "native_control_qualified": False,
            "reason": "Exact source and provider route values are both required.",
        }
    if expected_route != observed_route:
        return {
            "status": "CONFLICT",
            "projection_matches": False,
            "current_route_established": False,
            "native_control_qualified": False,
            "reason": "Source and provider routing values disagree for the same registered route subject.",
        }
    return {
        "status": "VERIFIED_EXACT",
        "projection_matches": True,
        "current_route_established": False,
        "native_control_qualified": False,
        "reason": "Exact projection values match; native control/current-route qualification remains separately governed.",
    }



def classify_route_projection(
    expected_route: Any,
    observed_projection: Any,
    *,
    projection_authoritative_for_current_routing: bool,
) -> dict[str, Any]:
    """Classify a provider route projection without confusing history with routing authority."""
    if not isinstance(expected_route, str) or not expected_route or not isinstance(observed_projection, str) or not observed_projection:
        return {
            "status": "UNRESOLVED",
            "projection_matches": False,
            "provider_projection_authoritative_for_current_routing": projection_authoritative_for_current_routing,
            "current_route_established_by_projection": False,
            "reason": "Exact current-route and provider-projection values are both required.",
        }
    if projection_authoritative_for_current_routing:
        decision = evaluate_route_binding(expected_route, observed_projection)
        return {
            **decision,
            "provider_projection_authoritative_for_current_routing": True,
            "current_route_established_by_projection": decision["status"] == "VERIFIED_EXACT",
        }
    return {
        "status": "HISTORICAL_PROVIDER_PROJECTION",
        "projection_matches": expected_route == observed_projection,
        "provider_projection_authoritative_for_current_routing": False,
        "current_route_established_by_projection": False,
        "reason": "Provider projection is retained as historical/bootstrap provenance; current route authority is resolved from the live Bus topology.",
    }


def classify_semantic_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a materialized Semantic Atlas snapshot by its own authority scope."""
    if snapshot.get("authority_scope") != "CANONICAL_LEDGER":
        return {
            "status": "RESEARCH_STAGING_ONLY",
            "canonical_runtime_semantics": False,
            "reason": "Non-CANONICAL_LEDGER authority scope cannot become canonical runtime semantics.",
        }
    if snapshot.get("state") != "ACTIVE" or snapshot.get("validation_state") != "VERIFIED":
        return {
            "status": "UNRESOLVED",
            "canonical_runtime_semantics": False,
            "reason": "Canonical scope still requires ACTIVE plus VERIFIED materialization evidence.",
        }
    commit = snapshot.get("git_commit_sha")
    readback = snapshot.get("git_readback_sha")
    activation_readback = snapshot.get("activation_git_readback_sha")
    if not isinstance(commit, str) or not commit or readback != commit or activation_readback != commit:
        return {
            "status": "CONFLICT",
            "canonical_runtime_semantics": False,
            "reason": "Canonical semantic snapshot lacks exact commit/readback/activation binding.",
        }
    return {
        "status": "CANONICAL_PROVIDER_SNAPSHOT_VERIFIED",
        "canonical_runtime_semantics": True,
        "reason": "Provider snapshot has canonical scope and exact Git readbacks; native runtime consumption remains a separate dimension.",
    }


def classify_memory_epoch_object(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Type a durable memory object from its payload, not from its provider receipt."""
    provenance = envelope.get("provenance")
    epistemic_class = provenance.get("epistemic_class") if isinstance(provenance, Mapping) else None
    limitations = envelope.get("limitations")
    limitation_set = {
        value for value in limitations
        if isinstance(limitations, list) and isinstance(value, str)
    } if isinstance(limitations, list) else set()
    if epistemic_class == "SYNTHETIC_TEST_FIXTURE" or "SYNTHETIC_QUALIFICATION_ONLY" in limitation_set:
        return {
            "status": "PERSISTED_SYNTHETIC_FIXTURE",
            "evidence_classes": ("persisted_provider_record",),
            "autobiographical_admission_eligible": False,
            "present_state_established": False,
            "reason": "Durable provider verification does not promote a synthetic fixture into autobiographical memory.",
        }
    if envelope.get("memory_class") == "WORKING_PROJECT":
        return {
            "status": "PERSISTED_WORKING_PROJECT",
            "evidence_classes": ("persisted_provider_record", "working_project"),
            "autobiographical_admission_eligible": False,
            "present_state_established": False,
            "reason": "Working-project memory remains working-project evidence; persistence does not make it autobiographical or present truth.",
        }
    if envelope.get("memory_class") == "AUTOBIOGRAPHICAL":
        return {
            "status": "AUTOBIOGRAPHICAL_CANDIDATE_PERSISTED",
            "evidence_classes": ("persisted_provider_record", "historical_autobiographical"),
            "autobiographical_admission_eligible": True,
            "present_state_established": False,
            "reason": "Autobiographical payload may enter the separate admission/currentness process; persistence is not admission or present truth.",
        }
    return {
        "status": "PERSISTED_OBJECT_UNRESOLVED_TYPE",
        "evidence_classes": ("persisted_provider_record",),
        "autobiographical_admission_eligible": False,
        "present_state_established": False,
        "reason": "Provider object is persisted but lacks an autobiographical type eligible for admission.",
    }


def classify_persisted_runtime_holder(
    record: Mapping[str, Any],
    live_observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Keep a durable ACTIVE holder label separate from live-session currentness."""
    if live_observation is None:
        return {
            "status": "PERSISTED_RUNTIME_RECORD_ONLY",
            "current_live_runtime_established": False,
            "reason": "Persisted holder/runtime state has no separate fresh live observation binding the current session.",
        }
    token = record.get("holder_runtime_token")
    observed_token = live_observation.get("holder_runtime_token")
    observed_status = live_observation.get("runtime_status")
    if not isinstance(token, str) or not token or token != observed_token:
        return {
            "status": "CONFLICT",
            "current_live_runtime_established": False,
            "reason": "Persisted holder token and live runtime token do not bind the same runtime.",
        }
    if observed_status != "ACTIVE_HOLDER":
        return {
            "status": "UNRESOLVED",
            "current_live_runtime_established": False,
            "reason": "Live observation does not report ACTIVE_HOLDER for the bound runtime token.",
        }
    return {
        "status": "LIVE_RUNTIME_BOUND",
        "current_live_runtime_established": True,
        "reason": "Persisted holder record is separately bound to a fresh live ACTIVE_HOLDER observation for the same runtime token.",
    }
