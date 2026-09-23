from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, Mapping

from .adapters import AdapterProbeResult, AdapterRegistry, AdapterRequest
from .audit import AUDIT_STATUSES, ProjectionAuditResult, _audit_registered_projections_qualifying
from .evidence import ProviderEvidenceEnvelope, validate_envelope
from .item_typing import validated_item_type
from .runtime import build_operational_checkpoint, build_retrieval_plan, evaluate_proposition_admission


EVIDENCE_PREFIX = "VERA_RUNTIME_CONTRACT_V1#evidence_classes."
RETRIEVABLE_PROBE_STATES = {"CURRENTLY_OBSERVED_REACHABLE", "RESULT"}
_EVENT_SELECTOR_TOKENS = {"$source_ref", "$source_path", "$source_revision"}
_GOVERNING_RESOLUTION_STATES = {"SATISFIED", "UNRESOLVED", "CONFLICT"}
_AUTHORITY_RESOLVER_PREFIX = "VERA_RUNTIME_CONTRACT_V1#authority_resolvers."


@dataclass(frozen=True)
class GoverningResolutionRecord:
    prerequisite_domain: str
    proposition_or_effect_class: str | None
    referent_scope: str | None
    status: str
    admission_status: str
    dispatch_id: str | None
    resolver_ref: str | None
    observed_evidence_classes: tuple[str, ...]
    current_observation_count: int
    reason: str

    def __post_init__(self) -> None:
        if self.status not in _GOVERNING_RESOLUTION_STATES:
            raise ValueError(f"unsupported governing resolution status: {self.status}")
        if self.admission_status not in {"ADMITTED", "UNRESOLVED", "CONFLICT"}:
            raise ValueError(f"unsupported governing admission status: {self.admission_status}")
        if self.status == "SATISFIED" and self.admission_status != "ADMITTED":
            raise ValueError("SATISFIED governing resolution requires ADMITTED proposition evidence")


@dataclass(frozen=True)
class DomainExecutionResult:
    status: str
    domain_id: str
    probes: tuple[AdapterProbeResult, ...]
    observations: tuple[ProviderEvidenceEnvelope, ...]
    unresolved: tuple[str, ...]
    checkpoint: dict[str, Any]
    governing_resolutions: tuple[GoverningResolutionRecord, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"EXECUTED", "EXECUTED_WITH_UNRESOLVED", "UNRESOLVED"}:
            raise ValueError(f"unsupported execution status: {self.status}")


@dataclass(frozen=True)
class ProjectionExecutionResult:
    status: str
    projection_id: str
    probes: tuple[AdapterProbeResult, ...]
    source_observation: ProviderEvidenceEnvelope | None
    target_observation: ProviderEvidenceEnvelope | None
    audit: ProjectionAuditResult | None
    unresolved: tuple[str, ...]
    checkpoint: dict[str, Any]

    def __post_init__(self) -> None:
        if self.status not in AUDIT_STATUSES:
            raise ValueError(f"unsupported projection execution status: {self.status}")
        if not self.projection_id:
            raise ValueError("projection_id must be non-empty")


def _provider_for_route(fabric: Mapping[str, Any], route_ref: str) -> str:
    matches = [
        provider_id
        for provider_id, provider in fabric.get("providers", {}).items()
        if route_ref in provider.get("route_refs", [])
    ]
    if len(matches) != 1:
        raise ValueError(f"route {route_ref!r} must resolve to exactly one provider; got {matches!r}")
    return matches[0]


def _request_for_candidate(
    candidate: Mapping[str, Any],
    provider: str,
    *,
    governing_dispatch: Mapping[str, Any] | None = None,
) -> AdapterRequest:
    governing_proposition = None
    governing_referent_scope = None
    if governing_dispatch is not None:
        governing_proposition = str(governing_dispatch["proposition_or_effect_class"])
        governing_referent_scope = str(governing_dispatch["referent_scope"])
    return AdapterRequest(
        domain_id=str(candidate["domain_id"]),
        provider=provider,
        source_ref=str(candidate["source_ref"]),
        route_ref=str(candidate["route_ref"]),
        selector_ref=candidate.get("selector_ref"),
        privacy_class=str(candidate["privacy_class"]),
        evidence_capability_refs=tuple(candidate.get("evidence_capability_refs", ())),
        governing_proposition_or_effect_class=governing_proposition,
        governing_referent_scope=governing_referent_scope,
    )


def _candidate_key(candidate: Mapping[str, Any]) -> tuple[str, str, str, str | None]:
    return (
        str(candidate["domain_id"]),
        str(candidate["source_ref"]),
        str(candidate["route_ref"]),
        candidate.get("selector_ref"),
    )


def _allowed_evidence_classes(request: AdapterRequest) -> set[str]:
    result: set[str] = set()
    for ref in request.evidence_capability_refs:
        if not ref.startswith(EVIDENCE_PREFIX):
            raise ValueError(f"unsupported evidence capability ref: {ref}")
        result.add(ref[len(EVIDENCE_PREFIX):])
    return result


def _validate_probe(request: AdapterRequest, probe: AdapterProbeResult) -> None:
    if probe.provider != request.provider:
        raise ValueError(
            f"adapter probe provider mismatch for {request.route_ref}: expected {request.provider!r}, got {probe.provider!r}"
        )
    if probe.route_ref != request.route_ref:
        raise ValueError(
            f"adapter probe route mismatch: expected {request.route_ref!r}, got {probe.route_ref!r}"
        )


def _validate_read(request: AdapterRequest, envelope: ProviderEvidenceEnvelope) -> None:
    validate_envelope(envelope)
    if envelope.provider != request.provider:
        raise ValueError(
            f"adapter read provider mismatch for {request.route_ref}: expected {request.provider!r}, got {envelope.provider!r}"
        )

    derived = validated_item_type(request, envelope)
    if derived is None:
        raise ValueError(
            f"returned item lacks independently validated type/currentness provenance for {request.route_ref}"
        )
    if derived.derived_evidence_class != envelope.evidence_class:
        raise ValueError(
            "returned item evidence class does not match independently derived item type: "
            f"claimed={envelope.evidence_class!r} derived={derived.derived_evidence_class!r}"
        )
    if derived.derived_evidence_class not in _allowed_evidence_classes(request):
        raise ValueError(
            f"independently derived item evidence class {derived.derived_evidence_class!r} is not in target capability set for {request.route_ref}"
        )
    if envelope.privacy_class != request.privacy_class:
        raise ValueError(
            f"returned item privacy class {envelope.privacy_class!r} does not match planned class {request.privacy_class!r}"
        )
    route_ref = envelope.metadata.get("route_ref")
    source_ref = envelope.metadata.get("source_ref")
    if route_ref != request.route_ref:
        raise ValueError(
            f"returned item route metadata mismatch: expected {request.route_ref!r}, got {route_ref!r}"
        )
    if source_ref != request.source_ref:
        raise ValueError(
            f"returned item source metadata mismatch: expected {request.source_ref!r}, got {source_ref!r}"
        )


def _validate_domain_read(request: AdapterRequest, envelope: ProviderEvidenceEnvelope) -> None:
    _validate_read(request, envelope)
    if envelope.referent != request.domain_id:
        raise ValueError(
            f"returned item referent mismatch: expected governing/task domain {request.domain_id!r}, got {envelope.referent!r}"
        )


def _checkpoint_with_unresolved(checkpoint: Mapping[str, Any], unresolved: list[str]) -> dict[str, Any]:
    result = dict(checkpoint)
    pointer = dict(result.get("minimum_necessary_payload_or_pointer", {}))
    pointer["unresolved"] = list(dict.fromkeys(unresolved))
    result["minimum_necessary_payload_or_pointer"] = pointer
    return result


def _expected_governing_dispatch(
    prerequisite_domain: str,
    index: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str]:
    domain_rows = [row for row in index.get("domains", []) if row.get("id") == prerequisite_domain]
    if len(domain_rows) != 1:
        return None, "Governing prerequisite domain does not resolve exactly once in the cohesion index."

    authority_ref = domain_rows[0].get("authority_resolver_ref")
    if not isinstance(authority_ref, str) or not authority_ref.startswith(_AUTHORITY_RESOLVER_PREFIX):
        return None, "Governing prerequisite lacks an exact runtime-contract authority resolver reference."
    resolver_ref = authority_ref[len(_AUTHORITY_RESOLVER_PREFIX):]

    candidates = [
        row
        for row in contract.get("resolver_dispatch", [])
        if isinstance(row, Mapping)
        and row.get("resolver_ref") == resolver_ref
        and row.get("domain_scope") in {"*", prerequisite_domain}
    ]
    if not candidates:
        return None, "No resolver dispatch binds the prerequisite domain's declared authority resolver to an exact proposition/referent."

    def rank(row: Mapping[str, Any]) -> tuple[int, int]:
        precedence = row.get("precedence")
        if not isinstance(precedence, int):
            precedence = -1
        specificity = 1 if row.get("domain_scope") == prerequisite_domain else 0
        return precedence, specificity

    best_rank = max(rank(row) for row in candidates)
    best = [row for row in candidates if rank(row) == best_rank]
    if len(best) != 1:
        return None, "Governing prerequisite authority resolver has an ambiguous highest-rank proposition/referent dispatch."

    selected = best[0]
    for field in ("id", "proposition_or_effect_class", "referent_scope", "resolver_ref"):
        if not isinstance(selected.get(field), str) or not selected.get(field):
            return None, f"Selected governing dispatch is missing {field}."
    return selected, "Exact governing proposition/referent dispatch derived from A+B."


def _derive_governing_resolution(
    prerequisite_domain: str,
    index: Mapping[str, Any],
    contract: Mapping[str, Any],
    observations: list[ProviderEvidenceEnvelope],
) -> GoverningResolutionRecord:
    expected, expected_reason = _expected_governing_dispatch(prerequisite_domain, index, contract)
    relevant = [item for item in observations if item.referent == prerequisite_domain]
    observed_classes = tuple(sorted({item.evidence_class for item in relevant}))

    if expected is None:
        return GoverningResolutionRecord(
            prerequisite_domain=prerequisite_domain,
            proposition_or_effect_class=None,
            referent_scope=None,
            status="UNRESOLVED",
            admission_status="UNRESOLVED",
            dispatch_id=None,
            resolver_ref=None,
            observed_evidence_classes=observed_classes,
            current_observation_count=0,
            reason=expected_reason,
        )

    proposition = str(expected["proposition_or_effect_class"])
    referent_scope = str(expected["referent_scope"])
    expected_dispatch_id = str(expected["id"])
    expected_resolver_ref = str(expected["resolver_ref"])
    bound = [
        item
        for item in relevant
        if item.metadata.get("proposition_or_effect_class") == proposition
        and item.metadata.get("referent_scope") == referent_scope
    ]
    if not bound:
        return GoverningResolutionRecord(
            prerequisite_domain=prerequisite_domain,
            proposition_or_effect_class=proposition,
            referent_scope=referent_scope,
            status="UNRESOLVED",
            admission_status="UNRESOLVED",
            dispatch_id=expected_dispatch_id,
            resolver_ref=expected_resolver_ref,
            observed_evidence_classes=observed_classes,
            current_observation_count=0,
            reason="No prerequisite evidence is explicitly bound to the exact A+B governing proposition/referent scope.",
        )

    if any(item.conflict_state in {"CONFLICT", "MISMATCH"} for item in bound):
        return GoverningResolutionRecord(
            prerequisite_domain=prerequisite_domain,
            proposition_or_effect_class=proposition,
            referent_scope=referent_scope,
            status="CONFLICT",
            admission_status="CONFLICT",
            dispatch_id=expected_dispatch_id,
            resolver_ref=expected_resolver_ref,
            observed_evidence_classes=tuple(sorted({item.evidence_class for item in bound})),
            current_observation_count=0,
            reason="Exact proposition-bound prerequisite evidence contains an explicit conflict/mismatch and cannot release dependent I/O.",
        )

    current = [
        item
        for item in bound
        if item.supersession_state == "CURRENT_OBSERVATION" and item.conflict_state == "NONE"
    ]
    if not current:
        return GoverningResolutionRecord(
            prerequisite_domain=prerequisite_domain,
            proposition_or_effect_class=proposition,
            referent_scope=referent_scope,
            status="UNRESOLVED",
            admission_status="UNRESOLVED",
            dispatch_id=expected_dispatch_id,
            resolver_ref=expected_resolver_ref,
            observed_evidence_classes=tuple(sorted({item.evidence_class for item in bound})),
            current_observation_count=0,
            reason="No conflict-free CURRENT_OBSERVATION evidence exists for the exact governing proposition/referent.",
        )

    decision = evaluate_proposition_admission(
        prerequisite_domain,
        proposition,
        referent_scope,
        current,
        contract,
    )
    if decision.dispatch_id != expected_dispatch_id or decision.resolver_ref != expected_resolver_ref:
        return GoverningResolutionRecord(
            prerequisite_domain=prerequisite_domain,
            proposition_or_effect_class=proposition,
            referent_scope=referent_scope,
            status="CONFLICT",
            admission_status="CONFLICT",
            dispatch_id=decision.dispatch_id,
            resolver_ref=decision.resolver_ref,
            observed_evidence_classes=decision.observed_evidence_classes,
            current_observation_count=len(current),
            reason="Admission dispatch/resolver does not match the prerequisite's independently derived A+B binding.",
        )

    status = {
        "ADMITTED": "SATISFIED",
        "CONFLICT": "CONFLICT",
        "UNRESOLVED": "UNRESOLVED",
    }[decision.status]
    return GoverningResolutionRecord(
        prerequisite_domain=prerequisite_domain,
        proposition_or_effect_class=proposition,
        referent_scope=referent_scope,
        status=status,
        admission_status=decision.status,
        dispatch_id=decision.dispatch_id,
        resolver_ref=decision.resolver_ref,
        observed_evidence_classes=decision.observed_evidence_classes,
        current_observation_count=len(current),
        reason=decision.reason,
    )


def _derive_governing_resolutions(
    index: Mapping[str, Any],
    contract: Mapping[str, Any],
    observations: list[ProviderEvidenceEnvelope],
) -> tuple[GoverningResolutionRecord, ...]:
    raw = index.get("dependency_semantics", {}).get("hard_prerequisite_domains", [])
    if not isinstance(raw, list):
        raise ValueError("dependency_semantics.hard_prerequisite_domains must be a list")
    return tuple(
        _derive_governing_resolution(domain_id, index, contract, observations)
        for domain_id in raw
        if isinstance(domain_id, str) and domain_id
    )


def execute_domain_cycle(
    domain_id: str,
    index: Mapping[str, Any],
    contract: Mapping[str, Any],
    fabric: Mapping[str, Any],
    adapters: AdapterRegistry,
    *,
    privacy_allowlist: set[str] | frozenset[str],
) -> DomainExecutionResult:
    """Execute a bounded provider-backed cohesion retrieval/resolution cycle.

    The executor never accepts a caller-supplied SATISFIED status. It first
    retrieves safe hard-prerequisite evidence, independently derives the exact
    governing proposition/referent dispatch from A+B, carries that exact request
    binding across the adapter boundary, then re-runs proposition admission and
    currentness on only the fresh envelopes that echo the same binding. Dependent
    provider I/O is released only from that internally derived resolution.
    """

    probes: list[AdapterProbeResult] = []
    observations: list[ProviderEvidenceEnvelope] = []
    route_states: dict[str, str] = {}
    execution_unresolved: list[str] = []
    candidate_requests: dict[tuple[str, str, str, str | None], AdapterRequest] = {}
    probed_keys: set[tuple[str, str, str, str | None]] = set()
    read_keys: set[tuple[str, str, str, str | None]] = set()
    governing_records = _derive_governing_resolutions(index, contract, observations)
    governing_states = {record.prerequisite_domain: record.status for record in governing_records}

    domains = index.get("domains", [])
    max_rounds = max(2, (len(domains) if isinstance(domains, list) else 1) * 2 + 2)
    plan = build_retrieval_plan(
        domain_id,
        index,
        contract,
        observed_route_states=route_states,
        privacy_allowlist=privacy_allowlist,
        governing_dependency_states=governing_states,
    )

    for _round in range(max_rounds):
        changed = False
        plan = build_retrieval_plan(
            domain_id,
            index,
            contract,
            observed_route_states=route_states,
            privacy_allowlist=privacy_allowlist,
            governing_dependency_states=governing_states,
        )

        for candidate in plan.candidate_targets:
            key = _candidate_key(candidate)
            provider = _provider_for_route(fabric, str(candidate["route_ref"]))
            governing_dispatch, _ = _expected_governing_dispatch(str(candidate["domain_id"]), index, contract)
            request = _request_for_candidate(candidate, provider, governing_dispatch=governing_dispatch)
            candidate_requests[key] = request
            if key in probed_keys:
                continue
            probed_keys.add(key)
            changed = True

            adapter = adapters.get(provider)
            if adapter is None:
                execution_unresolved.append(f"MISSING_ADAPTER:{provider}:{request.route_ref}")
                continue
            if getattr(adapter, "provider", None) != provider:
                raise ValueError(
                    f"adapter registry/provider mismatch for {provider!r}: adapter reports {getattr(adapter, 'provider', None)!r}"
                )
            probe = adapter.probe(request)
            _validate_probe(request, probe)
            probes.append(probe)
            route_states[request.route_ref] = probe.state

        plan = build_retrieval_plan(
            domain_id,
            index,
            contract,
            observed_route_states=route_states,
            privacy_allowlist=privacy_allowlist,
            governing_dependency_states=governing_states,
        )

        for target in plan.targets:
            key = _candidate_key(target)
            if key in read_keys:
                continue
            read_keys.add(key)
            changed = True

            provider = _provider_for_route(fabric, str(target["route_ref"]))
            request = candidate_requests.get(key)
            if request is None:
                governing_dispatch, _ = _expected_governing_dispatch(str(target["domain_id"]), index, contract)
                request = _request_for_candidate(target, provider, governing_dispatch=governing_dispatch)
                candidate_requests[key] = request
            adapter = adapters.get(provider)
            if adapter is None:
                execution_unresolved.append(f"MISSING_ADAPTER:{provider}:{request.route_ref}")
                continue
            envelope = adapter.read(request)
            if envelope is None:
                execution_unresolved.append(f"ABSENT_ITEM:{provider}:{request.route_ref}:{request.source_ref}")
                continue
            _validate_domain_read(request, envelope)
            observations.append(envelope)

        new_records = _derive_governing_resolutions(index, contract, observations)
        new_states = {record.prerequisite_domain: record.status for record in new_records}
        if new_states != governing_states:
            changed = True
        governing_records = new_records
        governing_states = new_states

        if not changed:
            break
    else:
        execution_unresolved.append("GOVERNING_RESOLUTION_FIXED_POINT_EXHAUSTED")

    plan = build_retrieval_plan(
        domain_id,
        index,
        contract,
        observed_route_states=route_states,
        privacy_allowlist=privacy_allowlist,
        governing_dependency_states=governing_states,
    )
    unresolved = list(dict.fromkeys([*execution_unresolved, *plan.unresolved]))
    checkpoint = _checkpoint_with_unresolved(build_operational_checkpoint(plan, []), unresolved)

    material_unresolved = [
        item
        for item in unresolved
        if not (
            item.startswith("ROUTE_NOT_CURRENTLY_OBSERVED_REACHABLE:")
            and item.rsplit(":", 1)[-1] in RETRIEVABLE_PROBE_STATES
        )
    ]
    if observations and not material_unresolved and plan.budget_state == "WITHIN_BUDGET":
        status = "EXECUTED"
    elif observations:
        status = "EXECUTED_WITH_UNRESOLVED"
    else:
        status = "UNRESOLVED"

    return DomainExecutionResult(
        status=status,
        domain_id=domain_id,
        probes=tuple(probes),
        observations=tuple(observations),
        unresolved=tuple(material_unresolved),
        checkpoint=checkpoint,
        governing_resolutions=governing_records,
    )


def _matches_pattern(value: str, pattern_expression: str) -> bool:
    patterns = [part.strip() for part in pattern_expression.split("|") if part.strip()]
    return any(fnmatchcase(value, pattern) for pattern in patterns)


def _projection_by_id(fabric: Mapping[str, Any], projection_id: str) -> Mapping[str, Any]:
    rows = [row for row in fabric.get("projections", []) if row.get("id") == projection_id]
    if len(rows) != 1:
        raise ValueError(f"projection {projection_id!r} must resolve exactly once; got {len(rows)}")
    return rows[0]


def _resolve_event_selector(
    projection: Mapping[str, Any],
    *,
    role: str,
    event_ref: str,
    event_path: str,
    source_revision: str | None,
) -> tuple[tuple[str, str], ...]:
    raw = projection.get(f"{role}_event_selector")
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise ValueError(f"projection {projection.get('id')!r} {role}_event_selector must be a mapping")
    values = {
        "$source_ref": event_ref,
        "$source_path": event_path,
        "$source_revision": source_revision,
    }
    resolved: list[tuple[str, str]] = []
    for field_name, template in raw.items():
        if not isinstance(field_name, str) or not field_name:
            raise ValueError("event selector field names must be non-empty strings")
        if not isinstance(template, str) or not template:
            raise ValueError(f"event selector value for {field_name!r} must be a non-empty string")
        if template.startswith("$") and template not in _EVENT_SELECTOR_TOKENS:
            raise ValueError(f"unsupported event selector token: {template}")
        value = values.get(template, template)
        if value is None:
            raise ValueError(f"event selector token {template!r} is unavailable before source readback")
        resolved.append((field_name, value))
    return tuple(sorted(resolved))


def _projection_request(
    projection: Mapping[str, Any],
    fabric: Mapping[str, Any],
    *,
    role: str,
    event_ref: str,
    event_path: str,
    source_revision: str | None = None,
) -> AdapterRequest:
    if role not in {"source", "target"}:
        raise ValueError(f"unsupported projection role: {role}")
    provider = str(projection[f"{role}_provider"])
    route_ref = str(projection[f"{role}_route_ref"])
    evidence_class = str(projection[f"{role}_evidence_class"])
    resolved_provider = _provider_for_route(fabric, route_ref)
    if resolved_provider != provider:
        raise ValueError(
            f"projection {projection.get('id')!r} {role} route/provider mismatch: {route_ref!r} resolves to {resolved_provider!r}, not {provider!r}"
        )
    provider_row = fabric.get("providers", {}).get(provider, {})
    if evidence_class not in provider_row.get("evidence_capability_refs", []):
        raise ValueError(
            f"projection {projection.get('id')!r} {role} evidence class {evidence_class!r} is not supported by provider {provider!r}"
        )
    return AdapterRequest(
        domain_id=f"PROJECTION_AUDIT:{projection['id']}",
        provider=provider,
        source_ref=str(projection[f"{role}_subject"]),
        route_ref=route_ref,
        selector_ref=None,
        privacy_class=str(projection["privacy_class"]),
        evidence_capability_refs=(f"{EVIDENCE_PREFIX}{evidence_class}",),
        event_ref=event_ref,
        event_path=event_path,
        event_selector=_resolve_event_selector(
            projection,
            role=role,
            event_ref=event_ref,
            event_path=event_path,
            source_revision=source_revision,
        ),
    )


def _event_binding_issue(
    request: AdapterRequest,
    envelope: ProviderEvidenceEnvelope,
) -> tuple[str, str] | None:
    if request.event_ref is None:
        return None
    observed_ref = envelope.metadata.get("projection_event_ref")
    observed_path = envelope.metadata.get("projection_event_path")
    if not isinstance(observed_ref, str) or not observed_ref or not isinstance(observed_path, str) or not observed_path:
        return (
            "UNRESOLVED",
            f"EVENT_BINDING_MISSING:{request.provider}:{request.route_ref}:{request.event_ref}:{request.event_path}",
        )
    if observed_ref != request.event_ref or observed_path != request.event_path:
        return (
            "CONFLICT",
            f"EVENT_BINDING_MISMATCH:{request.provider}:{request.route_ref}:requested={request.event_ref}@{request.event_path}:observed={observed_ref}@{observed_path}",
        )
    return None


def _projection_checkpoint(
    projection_id: str,
    status: str,
    source_ref: str,
    source_path: str,
    source: ProviderEvidenceEnvelope | None,
    target: ProviderEvidenceEnvelope | None,
    unresolved: tuple[str, ...],
    audit: ProjectionAuditResult | None,
) -> dict[str, Any]:
    return {
        "referent": projection_id,
        "scope": "DURABLE_OPERATIONAL_STATE",
        "provenance": "VERA_RUNTIME_COHESION_V1",
        "purpose": "CROSS_PROVIDER_PROJECTION_RECONCILIATION",
        "sensitivity_or_privacy_class": "POINTER_ONLY",
        "minimum_necessary_payload_or_pointer": {
            "projection_id": projection_id,
            "source_ref": source_ref,
            "source_path": source_path,
            "status": status,
            "source_revision": source.revision if source is not None else None,
            "target_revision": target.revision if target is not None else None,
            "escalation_frontier": audit.escalation_frontier if audit is not None else None,
            "unresolved": list(unresolved),
        },
        "destination_eligibility": "REQUIRES_ELIGIBLE_DURABLE_PROVIDER",
        "retention_or_expiry": "UNTIL_RECONCILED_RECOVERED_EXPIRED_OR_SUPERSEDED",
        "supersession_semantics": "EXPLICIT_SUCCESSOR_OR_RECOVERY_REQUIRED; NEWEST_TIMESTAMP_DOES_NOT_SUPERSEDE",
        "non_promotion_flag": True,
    }


def _projection_result(
    projection_id: str,
    status: str,
    probes: list[AdapterProbeResult],
    source_ref: str,
    source_path: str,
    source: ProviderEvidenceEnvelope | None = None,
    target: ProviderEvidenceEnvelope | None = None,
    audit: ProjectionAuditResult | None = None,
    unresolved: tuple[str, ...] = (),
) -> ProjectionExecutionResult:
    return ProjectionExecutionResult(
        status=status,
        projection_id=projection_id,
        probes=tuple(probes),
        source_observation=source,
        target_observation=target,
        audit=audit,
        unresolved=unresolved,
        checkpoint=_projection_checkpoint(
            projection_id,
            status,
            source_ref,
            source_path,
            source,
            target,
            unresolved,
            audit,
        ),
    )


def execute_projection_cycle(
    projection_id: str,
    fabric: Mapping[str, Any],
    adapters: AdapterRegistry,
    *,
    source_ref: str,
    source_path: str,
    privacy_allowlist: set[str] | frozenset[str],
) -> ProjectionExecutionResult:
    """Probe, read, event-bind, and reconcile one registered projection.

    Scope and privacy gates run before provider I/O. The exact caller event ref
    and path cross the adapter boundary. A provider observation must independently
    bind that same event before revision/digest reconciliation may run. Collection
    targets receive their registered provider-native event selector. Matching
    revisions for a different event never qualify as VERIFIED_EXACT.
    """

    projection = _projection_by_id(fabric, projection_id)
    privacy_class = str(projection.get("privacy_class", ""))
    probes: list[AdapterProbeResult] = []

    if not _matches_pattern(source_ref, str(projection.get("source_ref_pattern", ""))) or not _matches_pattern(
        source_path, str(projection.get("source_path_pattern", ""))
    ):
        return _projection_result(
            projection_id,
            "NOT_APPLICABLE",
            probes,
            source_ref,
            source_path,
        )

    if privacy_class not in privacy_allowlist and "*" not in privacy_allowlist:
        return _projection_result(
            projection_id,
            "UNRESOLVED",
            probes,
            source_ref,
            source_path,
            unresolved=(f"PRIVACY_NOT_ELIGIBLE:{projection_id}:{privacy_class}",),
        )

    source_request = _projection_request(
        projection,
        fabric,
        role="source",
        event_ref=source_ref,
        event_path=source_path,
    )

    source_adapter = adapters.get(source_request.provider)
    if source_adapter is None:
        return _projection_result(
            projection_id,
            "UNRESOLVED",
            probes,
            source_ref,
            source_path,
            unresolved=(f"MISSING_ADAPTER:{source_request.provider}:{source_request.route_ref}",),
        )
    if getattr(source_adapter, "provider", None) != source_request.provider:
        raise ValueError("source adapter registry/provider mismatch")
    source_probe = source_adapter.probe(source_request)
    _validate_probe(source_request, source_probe)
    probes.append(source_probe)
    if source_probe.state == "UNAVAILABLE":
        return _projection_result(
            projection_id,
            "UNAVAILABLE",
            probes,
            source_ref,
            source_path,
            unresolved=(f"SOURCE_ROUTE_UNAVAILABLE:{source_request.route_ref}",),
        )
    if source_probe.state not in RETRIEVABLE_PROBE_STATES:
        return _projection_result(
            projection_id,
            "UNRESOLVED",
            probes,
            source_ref,
            source_path,
            unresolved=(f"SOURCE_ROUTE_NOT_CURRENTLY_REACHABLE:{source_request.route_ref}:{source_probe.state}",),
        )

    source_observation = source_adapter.read(source_request)
    if source_observation is None:
        return _projection_result(
            projection_id,
            "ABSENT",
            probes,
            source_ref,
            source_path,
            unresolved=(f"SOURCE_OBJECT_ABSENT:{source_request.source_ref}",),
        )
    _validate_read(source_request, source_observation)
    binding_issue = _event_binding_issue(source_request, source_observation)
    if binding_issue is not None:
        status, reason = binding_issue
        return _projection_result(
            projection_id,
            status,
            probes,
            source_ref,
            source_path,
            source=source_observation,
            unresolved=(reason,),
        )

    target_request = _projection_request(
        projection,
        fabric,
        role="target",
        event_ref=source_ref,
        event_path=source_path,
        source_revision=source_observation.revision,
    )
    target_adapter = adapters.get(target_request.provider)
    if target_adapter is None:
        return _projection_result(
            projection_id,
            "UNRESOLVED",
            probes,
            source_ref,
            source_path,
            source=source_observation,
            unresolved=(f"MISSING_ADAPTER:{target_request.provider}:{target_request.route_ref}",),
        )
    if getattr(target_adapter, "provider", None) != target_request.provider:
        raise ValueError("target adapter registry/provider mismatch")
    target_probe = target_adapter.probe(target_request)
    _validate_probe(target_request, target_probe)
    probes.append(target_probe)
    if target_probe.state == "UNAVAILABLE":
        return _projection_result(
            projection_id,
            "UNAVAILABLE",
            probes,
            source_ref,
            source_path,
            source=source_observation,
            unresolved=(f"TARGET_ROUTE_UNAVAILABLE:{target_request.route_ref}",),
        )
    if target_probe.state not in RETRIEVABLE_PROBE_STATES:
        return _projection_result(
            projection_id,
            "UNRESOLVED",
            probes,
            source_ref,
            source_path,
            source=source_observation,
            unresolved=(f"TARGET_ROUTE_NOT_CURRENTLY_REACHABLE:{target_request.route_ref}:{target_probe.state}",),
        )

    target_observation = target_adapter.read(target_request)
    if target_observation is not None:
        _validate_read(target_request, target_observation)
        binding_issue = _event_binding_issue(target_request, target_observation)
        if binding_issue is not None:
            status, reason = binding_issue
            return _projection_result(
                projection_id,
                status,
                probes,
                source_ref,
                source_path,
                source=source_observation,
                target=target_observation,
                unresolved=(reason,),
            )

    audit = _audit_registered_projections_qualifying(
        fabric,
        {
            projection_id: {
                "source": source_observation,
                "target": target_observation,
                "source_ref": source_ref,
                "source_path": source_path,
            }
        },
    )[0]
    unresolved = (audit.reason,) if audit.status == "UNRESOLVED" else ()
    return _projection_result(
        projection_id,
        audit.status,
        probes,
        source_ref,
        source_path,
        source=source_observation,
        target=target_observation,
        audit=audit,
        unresolved=unresolved,
    )