from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


RETRIEVABLE_ROUTE_STATES = {"CURRENTLY_OBSERVED_REACHABLE", "RESULT"}
BUDGET_OK = "WITHIN_BUDGET"
BUDGET_EXHAUSTED = "UNRESOLVED_RETRIEVAL_BUDGET_EXHAUSTED"
ADMISSION_STATUSES = {"ADMITTED", "UNRESOLVED", "CONFLICT"}
GOVERNING_DEPENDENCY_STATES = {"SATISFIED", "UNRESOLVED", "CONFLICT"}
SEMANTIC_CURRENTNESS_DISPATCH_ID = "dispatch:semantic-currentness"


@dataclass(frozen=True)
class RetrievalPlan:
    domain_id: str
    candidate_targets: tuple[dict[str, Any], ...]
    targets: tuple[dict[str, Any], ...]
    visited_domains: tuple[str, ...]
    unresolved: tuple[str, ...]
    budget_state: str
    reason: str
    privacy_classes: tuple[str, ...]


@dataclass(frozen=True)
class AdmissionDecision:
    status: str
    dispatch_id: str | None
    resolver_ref: str | None
    required_evidence_classes: tuple[str, ...]
    observed_evidence_classes: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if self.status not in ADMISSION_STATUSES:
            raise ValueError(f"unsupported admission status: {self.status}")


def _rows_by_id(rows: Iterable[Mapping[str, Any]], kind: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            raise ValueError(f"{kind} row missing id")
        if row_id in result:
            raise ValueError(f"duplicate {kind} id: {row_id}")
        result[row_id] = row
    return result


def _validate_selector_narrowing(
    target: Mapping[str, Any],
    selectors: Mapping[str, Mapping[str, Any]],
) -> None:
    selector_ref = target.get("selector_ref")
    if selector_ref is None:
        return
    selector = selectors.get(selector_ref)
    if selector is None:
        raise ValueError(f"unknown selector: {selector_ref}")
    if selector.get("source_ref") != target.get("source_ref"):
        raise ValueError(f"selector/source mismatch: {selector_ref}")
    narrowed = selector.get("evidence_capability_refs")
    if narrowed is None:
        return
    parent = set(target.get("evidence_capability_refs", []))
    narrowed_set = set(narrowed)
    if not narrowed_set.issubset(parent):
        raise ValueError(f"selector broadens parent evidence capabilities: {selector_ref}")


def _decisive_evidence_requirements(
    dispatch_id: str,
    contract: Mapping[str, Any],
) -> tuple[set[str], set[str]] | None:
    registry = contract.get("resolver_dispatch_decisive_evidence")
    if not isinstance(registry, Mapping):
        return None
    decisive = registry.get(dispatch_id)
    if not isinstance(decisive, Mapping):
        return None
    allowed_keys = {"all_of", "any_of", "relational_binding"}
    if not {"all_of", "any_of"}.issubset(decisive) or not set(decisive).issubset(allowed_keys):
        return None
    all_raw = decisive.get("all_of")
    any_raw = decisive.get("any_of")
    if not isinstance(all_raw, list) or not isinstance(any_raw, list):
        return None
    if not all(isinstance(value, str) and value for value in all_raw + any_raw):
        return None
    all_of = set(all_raw)
    any_of = set(any_raw)
    if not all_of and not any_of:
        return None
    return all_of, any_of


def _admissible_evidence_class(
    item: Any,
    *,
    domain_id: str,
    proposition_or_effect_class: str,
    referent_scope: str,
) -> str | None:
    evidence_class = getattr(item, "evidence_class", None)
    if not isinstance(evidence_class, str) or not evidence_class:
        return None

    # Lightweight abstract evidence objects remain supported for isolated policy
    # tests. Rich provider envelopes, however, cannot discard their own binding,
    # conflict, or currentness state merely by crossing the admission boundary.
    rich_fields = ("referent", "supersession_state", "conflict_state", "metadata")
    if not any(hasattr(item, field) for field in rich_fields):
        return evidence_class
    if not all(hasattr(item, field) for field in rich_fields):
        return None
    if getattr(item, "referent") != domain_id:
        return None
    if getattr(item, "supersession_state") != "CURRENT_OBSERVATION":
        return None
    if getattr(item, "conflict_state") != "NONE":
        return None
    metadata = getattr(item, "metadata")
    if not isinstance(metadata, Mapping):
        return None
    if metadata.get("proposition_or_effect_class") != proposition_or_effect_class:
        return None
    if metadata.get("referent_scope") != referent_scope:
        return None
    return evidence_class


def _semantic_currentness_relational_decision(
    *,
    dispatch_id: str,
    resolver_ref: str,
    domain_id: str,
    proposition_or_effect_class: str,
    referent_scope: str,
    observations: tuple[Any, ...],
    contract: Mapping[str, Any],
    required_evidence_classes: tuple[str, ...],
    observed_evidence_classes: tuple[str, ...],
) -> AdmissionDecision | None:
    if dispatch_id != SEMANTIC_CURRENTNESS_DISPATCH_ID:
        return None

    registry = contract.get("resolver_dispatch_decisive_evidence")
    decisive = registry.get(dispatch_id) if isinstance(registry, Mapping) else None
    relational = decisive.get("relational_binding") if isinstance(decisive, Mapping) else None
    if not isinstance(relational, Mapping):
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Semantic currentness has no explicit relational binding rule; evidence-class co-occurrence is not sufficient currentness authority.",
        )

    required_keys = {
        "mode",
        "control_root_ref",
        "required_source_identity",
        "required_currentness_state",
        "required_supersession_state",
        "shared_metadata_fields",
    }
    if set(relational) != required_keys:
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Semantic currentness relational binding rule is malformed or incomplete.",
        )
    if relational.get("mode") != "EXACT_SHARED_R10_CONTROL_BINDING":
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Semantic currentness relational binding mode is unsupported.",
        )
    if relational.get("control_root_ref") != "VERA_RUNTIME_CONTRACT_V1#control_root":
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Semantic currentness relational rule does not bind the runtime contract control root.",
        )

    control_root = contract.get("control_root")
    if not isinstance(control_root, Mapping):
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Runtime contract control root is unavailable for semantic currentness reconciliation.",
        )
    expected_release = control_root.get("release")
    expected_round = control_root.get("round")
    expected_manifest = control_root.get("manifest_sha256")
    expected_source_commit = control_root.get("source_commit")
    required_source_identity = relational.get("required_source_identity")
    required_currentness_state = relational.get("required_currentness_state")
    required_supersession_state = relational.get("required_supersession_state")
    shared_fields = relational.get("shared_metadata_fields")
    if not all(
        isinstance(value, str) and value
        for value in (
            expected_release,
            expected_round,
            expected_manifest,
            expected_source_commit,
            required_source_identity,
            required_currentness_state,
            required_supersession_state,
        )
    ):
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Semantic currentness exact R10 binding requirements are incomplete.",
        )
    expected_fields = [
        "control_release",
        "control_round",
        "control_manifest_sha256",
        "binding_source_identity",
        "binding_source_revision",
        "binding_currentness_state",
        "binding_supersession_state",
    ]
    if shared_fields != expected_fields:
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Semantic currentness shared binding field registry is incomplete or reordered.",
        )

    decisive_items: dict[str, list[Any]] = {"control_source": [], "live_observation": []}
    for item in observations:
        evidence_class = _admissible_evidence_class(
            item,
            domain_id=domain_id,
            proposition_or_effect_class=proposition_or_effect_class,
            referent_scope=referent_scope,
        )
        if evidence_class in decisive_items:
            decisive_items[evidence_class].append(item)

    if not decisive_items["control_source"] or not decisive_items["live_observation"]:
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Semantic currentness requires both control_source and live_observation evidence bound to the same exact R10 source state.",
        )

    expected_binding = {
        "control_release": expected_release,
        "control_round": expected_round,
        "control_manifest_sha256": expected_manifest,
        "binding_source_identity": required_source_identity,
        "binding_source_revision": expected_source_commit,
        "binding_currentness_state": required_currentness_state,
        "binding_supersession_state": required_supersession_state,
    }

    normalized_bindings: dict[str, list[tuple[str, ...]]] = {"control_source": [], "live_observation": []}
    for evidence_class, items in decisive_items.items():
        for item in items:
            metadata = getattr(item, "metadata", None)
            if not isinstance(metadata, Mapping) or any(field not in metadata for field in expected_fields):
                return AdmissionDecision(
                    status="UNRESOLVED",
                    dispatch_id=dispatch_id,
                    resolver_ref=resolver_ref,
                    required_evidence_classes=required_evidence_classes,
                    observed_evidence_classes=observed_evidence_classes,
                    reason=f"{evidence_class} lacks exact semantic-currentness binding metadata; class identity alone cannot establish currentness.",
                )

            observed_binding = {field: metadata.get(field) for field in expected_fields}
            if evidence_class == "control_source" and any(
                observed_binding[field] != expected_binding[field]
                for field in ("control_release", "control_round", "control_manifest_sha256")
            ):
                return AdmissionDecision(
                    status="CONFLICT",
                    dispatch_id=dispatch_id,
                    resolver_ref=resolver_ref,
                    required_evidence_classes=required_evidence_classes,
                    observed_evidence_classes=observed_evidence_classes,
                    reason="control_source explicitly conflicts with the exact runtime contract R10 control root.",
                )
            if observed_binding["binding_source_identity"] != required_source_identity:
                return AdmissionDecision(
                    status="CONFLICT",
                    dispatch_id=dispatch_id,
                    resolver_ref=resolver_ref,
                    required_evidence_classes=required_evidence_classes,
                    observed_evidence_classes=observed_evidence_classes,
                    reason="Semantic currentness decisive evidence is not bound to the required exact R10 source identity.",
                )
            if observed_binding["binding_currentness_state"] != required_currentness_state:
                return AdmissionDecision(
                    status="CONFLICT",
                    dispatch_id=dispatch_id,
                    resolver_ref=resolver_ref,
                    required_evidence_classes=required_evidence_classes,
                    observed_evidence_classes=observed_evidence_classes,
                    reason="Semantic currentness decisive evidence carries a conflicting currentness state.",
                )
            if (
                observed_binding["binding_supersession_state"] != required_supersession_state
                or getattr(item, "supersession_state", None) != required_supersession_state
            ):
                return AdmissionDecision(
                    status="UNRESOLVED",
                    dispatch_id=dispatch_id,
                    resolver_ref=resolver_ref,
                    required_evidence_classes=required_evidence_classes,
                    observed_evidence_classes=observed_evidence_classes,
                    reason="Semantic currentness decisive evidence is not current under the required supersession state.",
                )
            normalized_bindings[evidence_class].append(
                tuple(str(observed_binding[field]) for field in expected_fields)
            )

    all_bindings = normalized_bindings["control_source"] + normalized_bindings["live_observation"]
    first_binding = all_bindings[0]
    if any(binding != first_binding for binding in all_bindings[1:]):
        return AdmissionDecision(
            status="CONFLICT",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="control_source and live_observation do not attest the same exact source/revision/control/currentness/supersession binding.",
        )
    if any(first_binding[index] != str(expected_binding[field]) for index, field in enumerate(expected_fields)):
        return AdmissionDecision(
            status="CONFLICT",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=required_evidence_classes,
            observed_evidence_classes=observed_evidence_classes,
            reason="Semantic currentness shared binding does not resolve to the exact R10 proposition/referent/source/currentness state.",
        )

    return AdmissionDecision(
        status="ADMITTED",
        dispatch_id=dispatch_id,
        resolver_ref=resolver_ref,
        required_evidence_classes=required_evidence_classes,
        observed_evidence_classes=observed_evidence_classes,
        reason="Observed decisive evidence satisfies the class rule and one exact shared R10 proposition/referent/source/currentness/supersession binding.",
    )


def evaluate_abstract_proposition_admission(
    domain_id: str,
    proposition_or_effect_class: str,
    referent_scope: str,
    observations: Iterable[Any],
    contract: Mapping[str, Any],
) -> AdmissionDecision:
    """Evaluate proposition admission for abstract policy evidence.

    Transport, readability, persistence, and exact cross-provider reconciliation
    are not proposition authority. Dispatch selection occurs before terminal
    resolver acceptance. Every dispatch must have an entry in the separate
    `resolver_dispatch_decisive_evidence` registry with explicit `all_of` and
    `any_of` semantics; the resolver's broader accepted set is only a capability
    ceiling and never silently becomes the deciding rule.

    This deliberately retains lightweight evidence support for isolated policy
    tests. Provider-backed callers must use `evaluate_proposition_admission`,
    which first requires full `ProviderEvidenceEnvelope` objects.
    """

    materialized = tuple(observations)
    dispatch_rows = contract.get("resolver_dispatch", [])
    candidates: list[Mapping[str, Any]] = []
    for row in dispatch_rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("domain_scope") not in {"*", domain_id}:
            continue
        if row.get("proposition_or_effect_class") != proposition_or_effect_class:
            continue
        if row.get("referent_scope") != referent_scope:
            continue
        candidates.append(row)

    observed = tuple(sorted({
        evidence_class
        for item in materialized
        if (evidence_class := _admissible_evidence_class(
            item,
            domain_id=domain_id,
            proposition_or_effect_class=proposition_or_effect_class,
            referent_scope=referent_scope,
        )) is not None
    }))

    if not candidates:
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=None,
            resolver_ref=None,
            required_evidence_classes=(),
            observed_evidence_classes=observed,
            reason="No resolver_dispatch row matches the exact domain/proposition/referent tuple.",
        )

    def rank(row: Mapping[str, Any]) -> tuple[int, int]:
        precedence = row.get("precedence")
        if not isinstance(precedence, int):
            precedence = -1
        specificity = 1 if row.get("domain_scope") == domain_id else 0
        return precedence, specificity

    best_rank = max(rank(row) for row in candidates)
    best = [row for row in candidates if rank(row) == best_rank]
    best_resolvers = {row.get("resolver_ref") for row in best}
    if len(best_resolvers) != 1:
        return AdmissionDecision(
            status="CONFLICT",
            dispatch_id=None,
            resolver_ref=None,
            required_evidence_classes=(),
            observed_evidence_classes=observed,
            reason="Equal-precedence/equal-specificity dispatch rows select different terminal resolvers.",
        )

    selected = sorted(best, key=lambda row: str(row.get("id", "")))[0]
    dispatch_id = selected.get("id")
    resolver_ref = selected.get("resolver_ref")
    resolvers = contract.get("authority_resolvers", {})
    resolver = resolvers.get(resolver_ref) if isinstance(resolvers, Mapping) else None
    if not isinstance(dispatch_id, str) or not dispatch_id or not isinstance(resolver_ref, str) or not isinstance(resolver, Mapping):
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id if isinstance(dispatch_id, str) else None,
            resolver_ref=resolver_ref if isinstance(resolver_ref, str) else None,
            required_evidence_classes=(),
            observed_evidence_classes=observed,
            reason="Selected dispatch does not resolve to a valid terminal authority resolver.",
        )

    accepted = {
        value for value in resolver.get("accepted_evidence_classes", [])
        if isinstance(value, str) and value
    }
    decisive = _decisive_evidence_requirements(dispatch_id, contract)
    if decisive is None:
        return AdmissionDecision(
            status="UNRESOLVED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=(),
            observed_evidence_classes=observed,
            reason="Selected dispatch has no explicit valid decisive-evidence registry entry; implicit resolver fallback is forbidden.",
        )

    all_of, any_of = decisive
    required = all_of | any_of
    if not required.issubset(accepted):
        return AdmissionDecision(
            status="CONFLICT",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=tuple(sorted(required)),
            observed_evidence_classes=observed,
            reason="Dispatch decisive-evidence requirement exceeds its terminal resolver acceptance set.",
        )

    observed_set = set(observed)
    all_satisfied = all_of.issubset(observed_set)
    any_satisfied = not any_of or bool(observed_set.intersection(any_of))
    if all_satisfied and any_satisfied:
        relational = _semantic_currentness_relational_decision(
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            domain_id=domain_id,
            proposition_or_effect_class=proposition_or_effect_class,
            referent_scope=referent_scope,
            observations=materialized,
            contract=contract,
            required_evidence_classes=tuple(sorted(required)),
            observed_evidence_classes=observed,
        )
        if relational is not None:
            return relational
        return AdmissionDecision(
            status="ADMITTED",
            dispatch_id=dispatch_id,
            resolver_ref=resolver_ref,
            required_evidence_classes=tuple(sorted(required)),
            observed_evidence_classes=observed,
            reason="Observed evidence satisfies the selected dispatch's explicit decisive all-of/any-of rule.",
        )

    return AdmissionDecision(
        status="UNRESOLVED",
        dispatch_id=dispatch_id,
        resolver_ref=resolver_ref,
        required_evidence_classes=tuple(sorted(required)),
        observed_evidence_classes=observed,
        reason="Readable/reconciled evidence is insufficient to satisfy the selected dispatch's decisive evidence rule.",
    )


def evaluate_proposition_admission(
    domain_id: str,
    proposition_or_effect_class: str,
    referent_scope: str,
    observations: Iterable[Any],
    contract: Mapping[str, Any],
) -> AdmissionDecision:
    """Provider-strict public admission boundary.

    Provider envelopes preserve binding/currentness/conflict fields, but
    semantic-currentness admission additionally requires executor-registered
    provider-origin validation for each decisive observation. Claimant-authored
    metadata, even if byte-for-byte correct, is not provider-origin proof.
    """
    from .evidence import ProviderEvidenceEnvelope
    from .origin import (
        SEMANTIC_CURRENTNESS_DOMAIN,
        SEMANTIC_CURRENTNESS_PROPOSITION,
        SEMANTIC_CURRENTNESS_REFERENT_SCOPE,
        SEMANTIC_DECISIVE_CLASSES,
        validated_semantic_origin,
    )

    materialized = tuple(observations)
    if not all(isinstance(item, ProviderEvidenceEnvelope) for item in materialized):
        raise TypeError(
            "provider-backed proposition admission requires ProviderEvidenceEnvelope observations"
        )

    if (
        domain_id == SEMANTIC_CURRENTNESS_DOMAIN
        and proposition_or_effect_class == SEMANTIC_CURRENTNESS_PROPOSITION
        and referent_scope == SEMANTIC_CURRENTNESS_REFERENT_SCOPE
    ):
        decisive_items = [
            item for item in materialized
            if item.evidence_class in SEMANTIC_DECISIVE_CLASSES
        ]
        if any(validated_semantic_origin(item, contract) is None for item in decisive_items):
            observed = tuple(sorted({item.evidence_class for item in materialized}))
            return AdmissionDecision(
                status="UNRESOLVED",
                dispatch_id=SEMANTIC_CURRENTNESS_DISPATCH_ID,
                resolver_ref="semantic_currentness",
                required_evidence_classes=tuple(sorted(SEMANTIC_DECISIVE_CLASSES)),
                observed_evidence_classes=observed,
                reason=(
                    "Semantic currentness provider admission requires independently validated "
                    "provider-origin proof for the exact R10 repository+commit+path+blob+SHA object; "
                    "claimant-authored envelope metadata cannot satisfy this boundary."
                ),
            )

    return evaluate_abstract_proposition_admission(
        domain_id,
        proposition_or_effect_class,
        referent_scope,
        materialized,
        contract,
    )


def build_retrieval_plan(
    domain_id: str,
    index: Mapping[str, Any],
    contract: Mapping[str, Any],
    observed_route_states: Mapping[str, str],
    privacy_allowlist: set[str] | frozenset[str],
    governing_dependency_states: Mapping[str, str] | None = None,
) -> RetrievalPlan:
    """Build the smallest bounded retrieval plan from supplied current evidence.

    The function performs no provider I/O. Governing hard prerequisites are
    traversed before a dependent domain. Route reachability is sufficient only to
    probe/read the prerequisite itself; it never releases dependent-domain I/O.
    A dependent domain becomes eligible only when every hard prerequisite has an
    explicit `SATISFIED` governing state produced by the caller's resolver/
    admission phase. Contextual dependencies are visited afterward and remain
    non-blocking under the visited-set and finite-budget rules.

    `candidate_targets` are safe probe targets. When a hard prerequisite is not
    satisfied, only prerequisite candidates are exposed; dependent candidates are
    withheld. `targets` additionally require a fresh reachable/result route.
    """

    domains = _rows_by_id(index.get("domains", []), "domain")
    selectors = _rows_by_id(index.get("selector_declarations", []), "selector")
    if domain_id not in domains:
        raise ValueError(f"unknown domain: {domain_id}")

    dependency_semantics = index.get("dependency_semantics", {})
    hard_domains_raw = dependency_semantics.get("hard_prerequisite_domains", [])
    if not isinstance(hard_domains_raw, list) or not all(isinstance(value, str) and value for value in hard_domains_raw):
        raise ValueError("dependency_semantics.hard_prerequisite_domains must be a list of domain ids")
    hard_domains = set(hard_domains_raw)
    unknown_hard_domains = hard_domains.difference(domains)
    if unknown_hard_domains:
        raise ValueError(f"unknown hard prerequisite domains: {sorted(unknown_hard_domains)!r}")

    governing_states = dict(governing_dependency_states or {})
    unknown_governing_domains = set(governing_states).difference(domains)
    if unknown_governing_domains:
        raise ValueError(f"unknown governing dependency states: {sorted(unknown_governing_domains)!r}")
    invalid_governing_states = {
        domain: state
        for domain, state in governing_states.items()
        if state not in GOVERNING_DEPENDENCY_STATES
    }
    if invalid_governing_states:
        raise ValueError(f"invalid governing dependency states: {invalid_governing_states!r}")

    policy = contract.get("active_context_policy", {})
    budget = policy.get("uncertainty_probe_budget", {})
    max_depth = int(budget.get("max_dependency_depth", 0))
    max_domains = int(budget.get("max_total_new_domains", 0))
    if max_depth < 0 or max_domains < 1:
        raise ValueError("invalid active-context retrieval budget")

    visited: list[str] = []
    visited_set: set[str] = set()
    visiting: set[str] = set()
    candidate_targets: list[dict[str, Any]] = []
    candidate_keys: set[tuple[Any, ...]] = set()
    targets: list[dict[str, Any]] = []
    target_keys: set[tuple[Any, ...]] = set()
    unresolved: list[str] = []
    privacy_seen: set[str] = set()
    budget_state = BUDGET_OK

    def classify_dependencies(current: Mapping[str, Any]) -> tuple[list[str], list[str]]:
        declared = current.get("dependencies", [])
        if not isinstance(declared, list):
            raise ValueError(f"{current.get('id')}: dependencies must be a list")
        hard: list[str] = []
        contextual: list[str] = []
        for dependency in declared:
            if not isinstance(dependency, str) or not dependency:
                raise ValueError(f"{current.get('id')}: dependency ids must be non-empty strings")
            if dependency in hard_domains:
                hard.append(dependency)
            else:
                contextual.append(dependency)
        return hard, contextual

    def visit(current_id: str, depth: int) -> None:
        nonlocal budget_state

        if current_id in visited_set or current_id in visiting:
            return
        if depth > max_depth or len(visited_set) >= max_domains:
            budget_state = BUDGET_EXHAUSTED
            unresolved.append(f"BUDGET_EXHAUSTED:{current_id}")
            return

        current = domains.get(current_id)
        if current is None:
            unresolved.append(f"UNKNOWN_DEPENDENCY:{current_id}")
            return

        visiting.add(current_id)
        hard_dependencies, contextual_dependencies = classify_dependencies(current)

        for dependency in hard_dependencies:
            if dependency in visited_set:
                continue
            if depth + 1 > max_depth or len(visited_set) >= max_domains:
                budget_state = BUDGET_EXHAUSTED
                unresolved.append(f"BUDGET_EXHAUSTED:{dependency}")
                continue
            visit(dependency, depth + 1)

        if current_id in visited_set:
            visiting.discard(current_id)
            return
        if len(visited_set) >= max_domains:
            budget_state = BUDGET_EXHAUSTED
            unresolved.append(f"BUDGET_EXHAUSTED:{current_id}")
            visiting.discard(current_id)
            return

        visited_set.add(current_id)
        visited.append(current_id)
        privacy_class = current.get("privacy_class")
        if not isinstance(privacy_class, str) or not privacy_class:
            unresolved.append(f"MISSING_PRIVACY_CLASS:{current_id}")
            visiting.discard(current_id)
            return
        privacy_seen.add(privacy_class)

        if privacy_class not in privacy_allowlist and "*" not in privacy_allowlist:
            unresolved.append(f"PRIVACY_NOT_ELIGIBLE:{current_id}:{privacy_class}")
        else:
            hard_unresolved = [
                dependency
                for dependency in hard_dependencies
                if governing_states.get(dependency) != "SATISFIED"
            ]
            for dependency in hard_unresolved:
                state = governing_states.get(dependency, "UNRESOLVED")
                unresolved.append(
                    f"HARD_PREREQUISITE_UNRESOLVED:{current_id}:{dependency}:GOVERNING_STATE={state}"
                )

            if not hard_unresolved:
                for target in current.get("retrieval_targets", []):
                    _validate_selector_narrowing(target, selectors)
                    route_ref = target.get("route_ref")
                    if not isinstance(route_ref, str) or not route_ref:
                        unresolved.append(f"MISSING_ROUTE_REF:{current_id}")
                        continue
                    key = (target.get("source_ref"), route_ref, target.get("selector_ref"))
                    candidate = {
                        "domain_id": current_id,
                        "source_ref": target.get("source_ref"),
                        "route_ref": route_ref,
                        "selector_ref": target.get("selector_ref"),
                        "evidence_capability_refs": tuple(target.get("evidence_capability_refs", [])),
                        "privacy_class": privacy_class,
                    }
                    if key not in candidate_keys:
                        candidate_keys.add(key)
                        candidate_targets.append(candidate)

                    route_state = observed_route_states.get(route_ref)
                    if route_state not in RETRIEVABLE_ROUTE_STATES:
                        unresolved.append(
                            f"ROUTE_NOT_CURRENTLY_OBSERVED_REACHABLE:{current_id}:{route_ref}:{route_state or 'UNOBSERVED'}"
                        )
                        continue
                    if key in target_keys:
                        continue
                    target_keys.add(key)
                    targets.append({**candidate, "observed_route_state": route_state})

        for dependency in contextual_dependencies:
            if dependency in visited_set or dependency in visiting:
                continue
            if depth + 1 > max_depth or len(visited_set) >= max_domains:
                budget_state = BUDGET_EXHAUSTED
                unresolved.append(f"BUDGET_EXHAUSTED:{dependency}")
                continue
            visit(dependency, depth + 1)

        visiting.discard(current_id)

    visit(domain_id, 0)

    if budget_state == BUDGET_EXHAUSTED:
        reason = "Retrieval expansion exhausted the configured ACTIVE_CONTEXT_SET budget and remains unresolved."
    elif unresolved:
        reason = "Retrieval plan is bounded with explicit unresolved route/privacy/governing-dependency state."
    else:
        reason = "Retrieval plan is within budget; governing prerequisites are satisfied and selected routes have fresh reachability/result evidence."

    return RetrievalPlan(
        domain_id=domain_id,
        candidate_targets=tuple(candidate_targets),
        targets=tuple(targets),
        visited_domains=tuple(visited),
        unresolved=tuple(dict.fromkeys(unresolved)),
        budget_state=budget_state,
        reason=reason,
        privacy_classes=tuple(sorted(privacy_seen)),
    )


def build_operational_checkpoint(
    plan: RetrievalPlan,
    reconciliation_results: Iterable[Any],
) -> dict[str, Any]:
    """Create a pointer-first resumable operational checkpoint.

    Reconciliation payloads are deliberately not copied. Only compact subject,
    status, and reason pointers are retained.
    """

    target_refs = [
        {
            "domain_id": target["domain_id"],
            "source_ref": target["source_ref"],
            "route_ref": target["route_ref"],
            "selector_ref": target["selector_ref"],
            "observed_route_state": target["observed_route_state"],
        }
        for target in plan.targets
    ]
    reconciliation_refs = [
        {
            "subject_key": getattr(result, "subject_key", None),
            "status": getattr(result, "status", None),
            "reason": getattr(result, "reason", None),
        }
        for result in reconciliation_results
    ]
    return {
        "referent": plan.domain_id,
        "scope": "DURABLE_OPERATIONAL_STATE",
        "provenance": "VERA_RUNTIME_COHESION_V1",
        "purpose": "RUNTIME_COHESION_RESUMABLE_OPERATION",
        "sensitivity_or_privacy_class": list(plan.privacy_classes),
        "minimum_necessary_payload_or_pointer": {
            "domain_id": plan.domain_id,
            "target_refs": target_refs,
            "reconciliation_refs": reconciliation_refs,
            "unresolved": list(plan.unresolved),
            "budget_state": plan.budget_state,
        },
        "destination_eligibility": "REQUIRES_ELIGIBLE_DURABLE_PROVIDER",
        "retention_or_expiry": "UNTIL_TASK_RESOLVED_EXPIRED_OR_SUPERSEDED",
        "supersession_semantics": "EXPLICIT_SUCCESSOR_OR_EXPIRY_REQUIRED; NEWEST_TIMESTAMP_DOES_NOT_SUPERSEDE",
        "non_promotion_flag": True,
    }
