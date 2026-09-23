from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any, Mapping

from .evidence import ProviderEvidenceEnvelope, validate_envelope
from .item_typing import validated_item_event_binding
from .reconcile import reconcile_exact, reconcile_exact_receipt


AUDIT_STATUSES = {
    "VERIFIED_EXACT",
    "STALE_PROJECTION",
    "CONFLICT",
    "ABSENT",
    "UNAVAILABLE",
    "UNRESOLVED",
    "NOT_APPLICABLE",
}


@dataclass(frozen=True)
class ProjectionAuditResult:
    projection_id: str
    status: str
    source_revision: str | None
    target_revision: str | None
    observed_at: str | None
    reason: str
    escalation_frontier: str
    claim_ceiling: str

    def __post_init__(self) -> None:
        if self.status not in AUDIT_STATUSES:
            raise ValueError(f"unsupported audit status: {self.status}")


def _matches_pattern(value: str, pattern_expression: str) -> bool:
    patterns = [part.strip() for part in pattern_expression.split("|") if part.strip()]
    return any(fnmatchcase(value, pattern) for pattern in patterns)


def _audit_result(
    projection: Mapping[str, Any],
    status: str,
    source: ProviderEvidenceEnvelope | None,
    target: ProviderEvidenceEnvelope | None,
    reason: str,
    escalation_frontier: str,
) -> ProjectionAuditResult:
    observed_at = source.observed_at if source is not None else (target.observed_at if target is not None else None)
    return ProjectionAuditResult(
        projection_id=str(projection["id"]),
        status=status,
        source_revision=source.revision if source is not None else None,
        target_revision=target.revision if target is not None else None,
        observed_at=observed_at,
        reason=reason,
        escalation_frontier=escalation_frontier,
        claim_ceiling=str(projection.get("claim_ceiling", "PROJECTION_EVIDENCE_ONLY")),
    )


def _qualification_gate(
    projection: Mapping[str, Any],
    result: ProjectionAuditResult,
    source: ProviderEvidenceEnvelope,
    target: ProviderEvidenceEnvelope,
    *,
    event_ref: str,
    event_path: str,
) -> ProjectionAuditResult:
    if result.status != "VERIFIED_EXACT":
        return result

    source_binding = validated_item_event_binding(
        source,
        provider=str(projection["source_provider"]),
        route_ref=str(projection["source_route_ref"]),
        source_ref=str(projection["source_subject"]),
        event_ref=event_ref,
        event_path=event_path,
    )
    target_binding = validated_item_event_binding(
        target,
        provider=str(projection["target_provider"]),
        route_ref=str(projection["target_route_ref"]),
        source_ref=str(projection["target_subject"]),
        event_ref=event_ref,
        event_path=event_path,
    )
    if source_binding is not None and target_binding is not None:
        return result

    return ProjectionAuditResult(
        projection_id=result.projection_id,
        status="UNRESOLVED",
        source_revision=result.source_revision,
        target_revision=result.target_revision,
        observed_at=result.observed_at,
        reason=(
            "Projection reconciliation reached an exact candidate, but the exact source and target envelope objects "
            "do not both carry runtime-owned provider/object/event provenance for this projection event. "
            "Supplied-observation audit cannot mint VERIFIED_EXACT from caller-shaped event metadata."
        ),
        escalation_frontier="EXECUTE_OR_VALIDATE_EXACT_PROVIDER_EVENT_READS",
        claim_ceiling=result.claim_ceiling,
    )


def audit_registered_projections(
    fabric: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
) -> list[ProjectionAuditResult]:
    """Audit registered projections without a weaker caller-supplied exact path.

    The public surface accepts no event-validation boolean or caller proof token.
    VERIFIED_EXACT can survive only when the exact live source and target envelope
    objects already carry independently derived runtime-owned provider/object/event
    provenance from the read boundary. Fresh caller-shaped envelopes therefore
    remain advisory even when their metadata looks identical.
    """

    registered = {row["id"]: row for row in fabric.get("projections", [])}
    results: list[ProjectionAuditResult] = []

    for projection_id, bundle in observations.items():
        projection = registered.get(projection_id)
        if projection is None:
            raise ValueError(f"unregistered projection: {projection_id}")

        source = bundle.get("source")
        target = bundle.get("target")
        if source is not None:
            validate_envelope(source)
        if target is not None:
            validate_envelope(target)

        if source is None:
            results.append(
                _audit_result(
                    projection,
                    "ABSENT",
                    None,
                    target,
                    "No source observation was supplied for the registered projection.",
                    "OBSERVE_REGISTERED_SOURCE",
                )
            )
            continue

        if source.provider != projection.get("source_provider"):
            results.append(
                _audit_result(
                    projection,
                    "CONFLICT",
                    source,
                    target,
                    f"Observed source provider {source.provider!r} does not match registered provider {projection.get('source_provider')!r}.",
                    "RECONCILE_PROVIDER_IDENTITY",
                )
            )
            continue

        source_ref = bundle.get("source_ref")
        source_path = bundle.get("source_path")
        if not isinstance(source_ref, str) or not isinstance(source_path, str):
            results.append(
                _audit_result(
                    projection,
                    "UNRESOLVED",
                    source,
                    target,
                    "Projection-scope audit requires exact source_ref and source_path observations.",
                    "OBSERVE_EXACT_SOURCE_SCOPE",
                )
            )
            continue

        if not _matches_pattern(source_ref, str(projection.get("source_ref_pattern", ""))) or not _matches_pattern(
            source_path, str(projection.get("source_path_pattern", ""))
        ):
            results.append(
                _audit_result(
                    projection,
                    "NOT_APPLICABLE",
                    source,
                    target,
                    "Observed source movement is outside the registered projection ref/path scope.",
                    "NONE_OUTSIDE_REGISTERED_PROJECTION_SCOPE",
                )
            )
            continue

        if target is None:
            results.append(
                _audit_result(
                    projection,
                    "ABSENT",
                    source,
                    None,
                    "Registered in-scope source observation has no target projection observation.",
                    "CHECK_TARGET_ROUTE_OR_PROJECTION_EXECUTION",
                )
            )
            continue

        if target.provider != projection.get("target_provider"):
            results.append(
                _audit_result(
                    projection,
                    "CONFLICT",
                    source,
                    target,
                    f"Observed target provider {target.provider!r} does not match registered provider {projection.get('target_provider')!r}.",
                    "RECONCILE_PROVIDER_IDENTITY",
                )
            )
            continue

        mode = projection.get("comparison_mode")
        if mode == "EXACT_REVISION":
            reconciliation = reconcile_exact(
                projection_id,
                [source, target],
                expected_revision=source.revision,
                expected_digest=source.content_digest if source.content_digest is not None else None,
            )
            frontier = {
                "VERIFIED_EXACT": "NONE",
                "STALE_PROJECTION": "REFRESH_OR_REPROJECT_TARGET_WITH_EXACT_SOURCE_BINDING",
                "CONFLICT": "RECONCILE_EXACT_PROVIDER_IDENTITIES",
                "ABSENT": "CHECK_TARGET_ROUTE_OR_PROJECTION_EXECUTION",
                "UNAVAILABLE": "RETRY_OR_USE_INDEPENDENT_SAME_TARGET_ROUTE",
                "UNRESOLVED": "OBTAIN_MISSING_EXACT_RECONCILIATION_EVIDENCE",
            }.get(reconciliation.status, "RECONCILE_PROJECTION")
            candidate = _audit_result(
                projection,
                reconciliation.status,
                source,
                target,
                reconciliation.reason,
                frontier,
            )
            results.append(
                _qualification_gate(
                    projection,
                    candidate,
                    source,
                    target,
                    event_ref=source_ref,
                    event_path=source_path,
                )
            )
            continue

        if mode == "EXACT_RECEIPT":
            reconciliation = reconcile_exact_receipt(
                projection_id,
                source,
                target,
                source_subject=str(projection.get("source_subject", "")),
                target_subject=str(projection.get("target_subject", "")),
                event_ref=source_ref,
                event_path=source_path,
                receipt_policy=projection.get("receipt_binding", {}),
            )
            frontier = {
                "VERIFIED_EXACT": "NONE",
                "STALE_PROJECTION": "REFRESH_RECEIPT_FOR_CURRENT_SOURCE_OBJECT",
                "CONFLICT": "RECONCILE_RECEIPT_EVENT_OBJECT_BINDING",
                "ABSENT": "CHECK_RECEIPT_OBJECT_OR_PROVIDER_EFFECT",
                "UNAVAILABLE": "RETRY_OR_USE_INDEPENDENT_SAME_TARGET_ROUTE",
                "UNRESOLVED": "OBTAIN_EXACT_RECEIPT_OBJECT_BINDING",
            }.get(reconciliation.status, "RECONCILE_RECEIPT_PROJECTION")
            candidate = _audit_result(
                projection,
                reconciliation.status,
                source,
                target,
                reconciliation.reason,
                frontier,
            )
            results.append(
                _qualification_gate(
                    projection,
                    candidate,
                    source,
                    target,
                    event_ref=source_ref,
                    event_path=source_path,
                )
            )
            continue

        if mode == "SEMANTIC_COMPANION":
            bound_source_revision = target.metadata.get("bound_source_revision")
            if not isinstance(bound_source_revision, str) or not bound_source_revision:
                results.append(
                    _audit_result(
                        projection,
                        "UNRESOLVED",
                        source,
                        target,
                        "Semantic companion does not expose an exact bound source revision, so automated exact freshness cannot be established.",
                        "ADD_OR_OBSERVE_EXACT_COMPANION_SOURCE_REVISION_BINDING",
                    )
                )
            elif bound_source_revision == source.revision:
                candidate = _audit_result(
                    projection,
                    "VERIFIED_EXACT",
                    source,
                    target,
                    "Semantic companion binds the currently observed exact source revision within the registered projection scope.",
                    "NONE",
                )
                results.append(
                    _qualification_gate(
                        projection,
                        candidate,
                        source,
                        target,
                        event_ref=source_ref,
                        event_path=source_path,
                    )
                )
            else:
                results.append(
                    _audit_result(
                        projection,
                        "STALE_PROJECTION",
                        source,
                        target,
                        f"Semantic companion is bound to source revision {bound_source_revision!r}, not current observed revision {source.revision!r}.",
                        "REFRESH_COMPANION_WITH_EXACT_SOURCE_REVISION_BINDING",
                    )
                )
            continue

        results.append(
            _audit_result(
                projection,
                "UNRESOLVED",
                source,
                target,
                f"Unsupported comparison mode {mode!r}.",
                "RECONCILE_PROVIDER_FABRIC_CONFIGURATION",
            )
        )

    return results


def _audit_registered_projections_qualifying(
    fabric: Mapping[str, Any],
    observations: Mapping[str, Mapping[str, Any]],
) -> list[ProjectionAuditResult]:
    """Compatibility alias with no privilege beyond the public audit surface.

    The name remains internal for the existing executor import, but qualification
    is determined only by runtime-owned item/event provenance already bound to the
    exact envelope objects. Calling this helper directly cannot self-assert that
    event validation occurred.
    """

    return audit_registered_projections(fabric, observations)
