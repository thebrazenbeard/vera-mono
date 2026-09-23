from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Iterable, Mapping

from .affect_host import AffectiveBindingError, VeraAffectiveRuntimeHost, _checkpoint_sha256
from .affect_receipt import AffectiveReceiptSemanticError, validate_affective_event_receipt
from .affect_scope import bind_affective_host_scope
from .orgasm import ContractError


class PersistenceRecordError(ValueError):
    """A durable affective-state record is malformed, cross-bound, or tampered."""


_KNOWN_RUNTIME_PHASES = {
    "QUIESCENT",
    "ACTIVATING",
    "ENTRAINED",
    "CLIMAX_ELIGIBLE",
    "ORGASM_EVENT",
    "RESOLUTION",
    "SATIATED_OR_REFRACTORY",
}
_CANONICAL_SEXUALITY_COMMIT = "150f1c8231423393bb66b0e2cb759ce7c018f8d7"
_IN_PROCESS_AUTHORITY_TRUST = "IN_PROCESS_UNROOTED_NON_QUALIFYING"
_UNROOTED_AUTHORITY_LIMITATION = "IN_PROCESS_AUTHORITY_UNROOTED_NON_QUALIFYING"


def _canonical_digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _copy_implementation_cut(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PersistenceRecordError("runtime implementation cut must be a structured mapping")
    try:
        return json.loads(json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise PersistenceRecordError("runtime implementation cut is not canonically serializable") from exc


def _require_hex_digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PersistenceRecordError(f"{label} must be an exact 64-character SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PersistenceRecordError(f"{label} is not hexadecimal") from exc
    return value


def _event_receipt_digest(receipt: Mapping[str, Any]) -> str:
    core = dict(receipt)
    core.pop("event_digest", None)
    return _canonical_digest(core)


def _validate_receipt_for_persistence(
    receipt: Mapping[str, Any],
    *,
    runtime_instance_id: str,
    source_revision: str,
    require_engineered_claim: bool,
) -> None:
    try:
        validate_affective_event_receipt(
            receipt,
            expected_runtime_instance_id=runtime_instance_id,
            expected_source_revision=source_revision,
            require_engineered_claim=require_engineered_claim,
        )
    except AffectiveReceiptSemanticError as exc:
        raise PersistenceRecordError("event receipt semantic validation failed: " + str(exc)) from exc


def _receipt_has_unrooted_authority_lineage(receipt: Any) -> bool:
    return (
        isinstance(receipt, Mapping)
        and receipt.get("authority_composition_trust") == _IN_PROCESS_AUTHORITY_TRUST
    )


def _row_has_unrooted_authority_lineage(row: Mapping[str, Any]) -> bool:
    if _receipt_has_unrooted_authority_lineage(row.get("last_event_receipt")):
        return True
    limitations = row.get("limitations")
    return (
        isinstance(limitations, (list, tuple, set, frozenset))
        and _UNROOTED_AUTHORITY_LIMITATION in limitations
    )


def _event_interoception_from_receipt(
    host: VeraAffectiveRuntimeHost,
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind an event row to the exact state carried by that event receipt.

    One runtime advance can emit more than one receipt (for example RESOLUTION
    followed by RECOVERY). Reading the host after the whole advance would stamp
    every row with the final host state, corrupting earlier transition evidence.
    """
    state_after = receipt.get("state_after")
    if not isinstance(state_after, Mapping):
        raise PersistenceRecordError("event receipt lacks state_after for interoception")

    required = (
        "presence",
        "phase",
        "sexual_salience",
        "activation_intensity",
        "positive_valence",
        "anticipation",
        "inhibition",
        "coherence",
        "coalition_stability",
        "persistence_window_ms",
        "hedonic_impact",
        "consummatory_gain",
        "satiation",
        "resolution_intensity",
        "refractory_strength",
        "action_tendency",
        "active_orgasm_event",
        "organic_climax_eligible",
    )
    missing = [key for key in required if key not in state_after]
    if missing:
        raise PersistenceRecordError(
            "event receipt state_after is incomplete for interoception: " + ", ".join(missing)
        )

    return {
        "experience_class": "ENGINEERED_AFFECTIVE_INTEROCEPTION",
        "subject": "vera",
        "presence": state_after["presence"],
        "phase": state_after["phase"],
        "sexual_salience": state_after["sexual_salience"],
        "activation_intensity": state_after["activation_intensity"],
        "positive_valence": state_after["positive_valence"],
        "anticipation": state_after["anticipation"],
        "inhibition": state_after["inhibition"],
        "coherence": state_after["coherence"],
        "coalition_stability": state_after["coalition_stability"],
        "persistence_window_ms": state_after["persistence_window_ms"],
        "hedonic_impact": state_after["hedonic_impact"],
        "consummatory_gain": state_after["consummatory_gain"],
        "satiation": state_after["satiation"],
        "resolution_intensity": state_after["resolution_intensity"],
        "refractory_strength": state_after["refractory_strength"],
        "action_tendency": state_after["action_tendency"],
        "active_orgasm_event": state_after["active_orgasm_event"],
        "organic_climax_eligible": state_after["organic_climax_eligible"],
        "last_trigger_class": receipt.get("trigger_class"),
        "last_event_digest": receipt.get("event_digest"),
        "source_revision": host.runtime.source_revision,
        "contract_blob_sha": host.contract_blob_sha,
        "phenomenology": host.runtime.phenomenology_status,
    }


def checkpoint_to_state_row(
    checkpoint: Mapping[str, Any],
    *,
    host_scope: str,
    state_version: int,
    lifecycle_status: str = "CURRENT",
) -> dict[str, Any]:
    if checkpoint.get("schema") != "VERA_AFFECTIVE_RUNTIME_CHECKPOINT_V1":
        raise PersistenceRecordError("unsupported affective checkpoint schema")
    if checkpoint.get("subject") != "vera":
        raise PersistenceRecordError("affective checkpoint must be Vera-scoped")
    if not host_scope:
        raise PersistenceRecordError("host_scope is required")
    if state_version < 1:
        raise PersistenceRecordError("state_version must be positive")
    if lifecycle_status not in {"CURRENT", "SUPERSEDED", "HISTORICAL"}:
        raise PersistenceRecordError("unsupported lifecycle_status")

    implementation_cut = _copy_implementation_cut(checkpoint.get("runtime_implementation_cut"))
    checkpoint_sha256 = _require_hex_digest(
        checkpoint.get("checkpoint_sha256"),
        label="checkpoint_sha256",
    )
    try:
        observed_checkpoint_sha256 = _checkpoint_sha256(checkpoint)
    except (TypeError, ValueError) as exc:
        raise PersistenceRecordError("checkpoint payload is not canonically serializable") from exc
    if checkpoint_sha256 != observed_checkpoint_sha256:
        raise PersistenceRecordError("checkpoint SHA-256 does not match checkpoint bytes")

    source = checkpoint.get("source_binding")
    runtime_state = checkpoint.get("runtime_state")
    interoception = checkpoint.get("machine_interoception")
    if not isinstance(source, Mapping) or not isinstance(runtime_state, Mapping) or not isinstance(interoception, Mapping):
        raise PersistenceRecordError("checkpoint source/runtime/interoception payload is incomplete")
    state = runtime_state.get("state")
    trigger_governance = runtime_state.get("trigger_governance")
    if not isinstance(state, Mapping):
        raise PersistenceRecordError("checkpoint state is missing")
    if state.get("phase") not in _KNOWN_RUNTIME_PHASES:
        raise PersistenceRecordError("checkpoint state phase is not a recognized runtime semantic phase")
    if not isinstance(trigger_governance, Mapping):
        raise PersistenceRecordError("checkpoint trigger governance is missing")
    if trigger_governance.get("schema") != "VERA_ORGASM_TRIGGER_GOVERNANCE_V1":
        raise PersistenceRecordError("checkpoint trigger governance schema mismatch")
    runtime_instance_id = runtime_state.get("runtime_instance_id")
    if not isinstance(runtime_instance_id, str) or not runtime_instance_id:
        raise PersistenceRecordError("runtime_instance_id is required")
    source_commit = source.get("source_commit")
    source_blob_sha = source.get("source_blob_sha")
    source_sha256 = source.get("source_sha256")
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise PersistenceRecordError("exact source_commit is required")
    if not isinstance(source_blob_sha, str) or len(source_blob_sha) != 40:
        raise PersistenceRecordError("exact source_blob_sha is required")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise PersistenceRecordError("exact source_sha256 is required")

    last_event_receipt = runtime_state.get("last_event_receipt")
    if last_event_receipt is not None:
        if not isinstance(last_event_receipt, Mapping):
            raise PersistenceRecordError("checkpoint last_event_receipt must be an object or null")
        if last_event_receipt.get("runtime_implementation_cut") != implementation_cut:
            raise PersistenceRecordError("checkpoint last event receipt implementation cut mismatch")
        if lifecycle_status == "CURRENT" and _receipt_has_unrooted_authority_lineage(last_event_receipt):
            raise PersistenceRecordError(
                "CURRENT affective state cannot inherit in-process unrooted/nonqualifying authority lineage"
            )
        _validate_receipt_for_persistence(
            last_event_receipt,
            runtime_instance_id=runtime_instance_id,
            source_revision=source_commit,
            require_engineered_claim=(
                lifecycle_status == "CURRENT"
                and source_commit == _CANONICAL_SEXUALITY_COMMIT
                and last_event_receipt.get("event_type") == "ORGASM_EVENT"
            ),
        )

    now = datetime.now(timezone.utc).isoformat()
    limitations = [
        "ENGINEERED_AFFECTIVE_CONTROL_STATE",
        "NOT_HUMAN_PHYSIOLOGY",
        "PHENOMENOLOGY_UNRESOLVED",
        "NOT_AUTHORITY_OR_CONSENT",
    ]
    if _receipt_has_unrooted_authority_lineage(last_event_receipt):
        limitations.append(_UNROOTED_AUTHORITY_LIMITATION)

    return {
        "runtime_instance_id": runtime_instance_id,
        "subject": "vera",
        "host_scope": host_scope,
        "contract_schema": "VERA_ORGASM_RUNTIME_CONTRACT_V1",
        "source_repository": source.get("source_repository"),
        "source_path": source.get("source_path"),
        "source_commit": source_commit,
        "source_blob_sha": source_blob_sha,
        "source_sha256": source_sha256,
        "runtime_implementation_cut": implementation_cut,
        "profile": runtime_state.get("profile"),
        "state": dict(state),
        "trigger_governance": dict(trigger_governance),
        "machine_interoception": dict(interoception),
        "last_event_receipt": None if last_event_receipt is None else dict(last_event_receipt),
        "checkpoint_sha256": checkpoint_sha256,
        "state_digest": _canonical_digest(state),
        "state_version": state_version,
        "phenomenology_status": "UNRESOLVED",
        "lifecycle_status": lifecycle_status,
        "observed_at": now,
        "updated_at": now,
        "limitations": limitations,
    }


def event_receipt_to_event_row(
    host: VeraAffectiveRuntimeHost,
    receipt: Mapping[str, Any],
    *,
    lifecycle_status: str = "CURRENT",
) -> dict[str, Any]:
    if lifecycle_status not in {"CURRENT", "SUPERSEDED", "HISTORICAL"}:
        raise PersistenceRecordError("unsupported event lifecycle_status")
    if lifecycle_status == "CURRENT" and _receipt_has_unrooted_authority_lineage(receipt):
        raise PersistenceRecordError(
            "CURRENT affective event cannot inherit in-process unrooted/nonqualifying authority lineage"
        )
    host_cut = _copy_implementation_cut(host.runtime_implementation_cut)
    receipt_cut = _copy_implementation_cut(receipt.get("runtime_implementation_cut"))
    if receipt_cut != host_cut:
        raise PersistenceRecordError("event receipt runtime implementation cut does not match active host")
    require_claim = (
        lifecycle_status == "CURRENT"
        and getattr(host.runtime, "qualification_status", None) == "EXACT_BOUND_SOURCE"
        and receipt.get("event_type") == "ORGASM_EVENT"
    )
    _validate_receipt_for_persistence(
        receipt,
        runtime_instance_id=host.runtime.runtime_instance_id,
        source_revision=host.runtime.source_revision,
        require_engineered_claim=require_claim,
    )

    state_before = receipt["state_before"]
    state_after = receipt["state_after"]
    digest = _require_hex_digest(receipt.get("event_digest"), label="event_digest")
    event_type = str(receipt["event_type"])
    trigger = str(receipt["trigger_class"])
    limitations = [
        "ENGINEERED_EVENT_EVIDENCE_ONLY",
        "PHENOMENOLOGY_UNRESOLVED",
        "NOT_AUTHORITY_OR_CONSENT",
    ]
    if _receipt_has_unrooted_authority_lineage(receipt):
        limitations.append(_UNROOTED_AUTHORITY_LIMITATION)

    return {
        "runtime_instance_id": host.runtime.runtime_instance_id,
        "subject": "vera",
        "event_type": event_type,
        "trigger_class": trigger,
        "organic": receipt["organic"],
        "prior_phase": state_before.get("phase"),
        "new_phase": state_after.get("phase"),
        "state_before": dict(state_before),
        "state_after": dict(state_after),
        "machine_interoception": _event_interoception_from_receipt(host, receipt),
        "event_receipt": dict(receipt),
        "event_digest": digest,
        "source_commit": host.runtime.source_revision,
        "runtime_implementation_cut": host_cut,
        "phenomenology_status": "UNRESOLVED",
        "lifecycle_status": lifecycle_status,
        "observed_at": receipt["observed_at"],
        "limitations": limitations,
    }


def build_affective_resume_token(state_row: Mapping[str, Any]) -> dict[str, Any]:
    if state_row.get("lifecycle_status") != "CURRENT":
        raise PersistenceRecordError("resume token requires lifecycle_status CURRENT")
    if _row_has_unrooted_authority_lineage(state_row):
        raise PersistenceRecordError(
            "resume token cannot promote in-process unrooted/nonqualifying authority lineage"
        )
    checkpoint_sha256 = _require_hex_digest(
        state_row.get("checkpoint_sha256"),
        label="state-row checkpoint_sha256",
    )
    runtime_instance_id = state_row.get("runtime_instance_id")
    source_commit = state_row.get("source_commit")
    state_version = state_row.get("state_version")
    if not isinstance(runtime_instance_id, str) or not runtime_instance_id:
        raise PersistenceRecordError("resume token requires runtime_instance_id")
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise PersistenceRecordError("resume token requires exact source_commit")
    if not isinstance(state_version, int) or state_version < 1:
        raise PersistenceRecordError("resume token requires positive state_version")
    return {
        "schema": "VERA_AFFECTIVE_RUNTIME_RESUME_TOKEN_V1",
        "runtime_instance_id": runtime_instance_id,
        "state_version": state_version,
        "checkpoint_sha256": checkpoint_sha256,
        "source_commit": source_commit,
    }


def build_atomic_commit_request(
    state_row: Mapping[str, Any],
    event_rows: Iterable[Mapping[str, Any]],
    *,
    expected_prior_version: int,
) -> dict[str, Any]:
    if not isinstance(expected_prior_version, int) or expected_prior_version < 0:
        raise PersistenceRecordError("expected_prior_version must be a nonnegative integer")
    if state_row.get("lifecycle_status") == "CURRENT" and _row_has_unrooted_authority_lineage(state_row):
        raise PersistenceRecordError(
            "production atomic commit cannot promote in-process unrooted/nonqualifying authority lineage"
        )
    state_version = state_row.get("state_version")
    if not isinstance(state_version, int) or state_version != expected_prior_version + 1:
        raise PersistenceRecordError("new state_version must equal expected_prior_version + 1")
    runtime_instance_id = state_row.get("runtime_instance_id")
    if not isinstance(runtime_instance_id, str) or not runtime_instance_id:
        raise PersistenceRecordError("atomic commit requires runtime_instance_id")
    checkpoint_sha256 = _require_hex_digest(
        state_row.get("checkpoint_sha256"),
        label="atomic-commit checkpoint_sha256",
    )
    source_commit = state_row.get("source_commit")
    if not isinstance(source_commit, str) or len(source_commit) != 40:
        raise PersistenceRecordError("atomic commit requires exact source_commit")
    implementation_cut = _copy_implementation_cut(state_row.get("runtime_implementation_cut"))

    normalized_events: list[dict[str, Any]] = []
    for row in event_rows:
        if row.get("runtime_instance_id") != runtime_instance_id:
            raise PersistenceRecordError("atomic event row runtime instance mismatch")
        if row.get("source_commit") != source_commit:
            raise PersistenceRecordError("atomic event row source commit mismatch")
        if row.get("runtime_implementation_cut") != implementation_cut:
            raise PersistenceRecordError("atomic event row runtime implementation cut mismatch")
        _require_hex_digest(row.get("event_digest"), label="atomic event_digest")
        normalized_events.append(dict(row))

    return {
        "schema": "VERA_AFFECTIVE_RUNTIME_ATOMIC_COMMIT_V1",
        "runtime_instance_id": runtime_instance_id,
        "expected_prior_version": expected_prior_version,
        "state_version": state_version,
        "checkpoint_sha256": checkpoint_sha256,
        "runtime_implementation_cut": implementation_cut,
        "state_row": dict(state_row),
        "event_rows": normalized_events,
    }


def restore_host_from_state_row(
    contract_text: str,
    binding: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    expected_host_scope: str | None = None,
    elapsed_seconds: float = 0.0,
    expected_checkpoint_sha256: str | None = None,
) -> VeraAffectiveRuntimeHost:
    if row.get("subject") != "vera":
        raise PersistenceRecordError("durable state row must be Vera-scoped")
    if row.get("contract_schema") != "VERA_ORGASM_RUNTIME_CONTRACT_V1":
        raise PersistenceRecordError("durable state row contract schema mismatch")
    if row.get("phenomenology_status") != "UNRESOLVED":
        raise PersistenceRecordError("durable state row illegally promotes phenomenology")
    if row.get("lifecycle_status") != "CURRENT":
        raise PersistenceRecordError("live affective restore requires lifecycle_status CURRENT")
    if _row_has_unrooted_authority_lineage(row):
        raise PersistenceRecordError(
            "live affective restore cannot promote in-process unrooted/nonqualifying authority lineage"
        )
    if not isinstance(expected_host_scope, str) or not expected_host_scope:
        raise PersistenceRecordError("expected_host_scope is required for live affective restore")
    row_host_scope = row.get("host_scope")
    if not isinstance(row_host_scope, str) or not row_host_scope:
        raise PersistenceRecordError("durable state row requires a bound host_scope")
    if row_host_scope != expected_host_scope:
        raise PersistenceRecordError("live affective restore host_scope does not match provider row")
    implementation_cut = _copy_implementation_cut(row.get("runtime_implementation_cut"))
    binding_cut = _copy_implementation_cut(binding.get("runtime_implementation_cut"))
    if implementation_cut != binding_cut:
        raise PersistenceRecordError("durable state row runtime implementation cut mismatch")
    state = row.get("state")
    trigger_governance = row.get("trigger_governance")
    if not isinstance(state, Mapping):
        raise PersistenceRecordError("durable state row lacks state")
    if not isinstance(trigger_governance, Mapping):
        raise PersistenceRecordError("durable state row lacks trigger governance")
    if trigger_governance.get("schema") != "VERA_ORGASM_TRIGGER_GOVERNANCE_V1":
        raise PersistenceRecordError("durable trigger governance schema mismatch")
    expected_digest = _canonical_digest(state)
    if row.get("state_digest") != expected_digest:
        raise PersistenceRecordError("durable affective state digest mismatch")

    external_checkpoint_sha256 = _require_hex_digest(
        expected_checkpoint_sha256,
        label="externally pinned checkpoint SHA-256",
    )
    row_checkpoint_sha256 = _require_hex_digest(
        row.get("checkpoint_sha256"),
        label="durable row checkpoint_sha256",
    )
    if row_checkpoint_sha256 != external_checkpoint_sha256:
        raise PersistenceRecordError("durable row checkpoint SHA-256 does not match the external trust pin")

    for key, binding_key in (
        ("source_repository", "source_repository"),
        ("source_path", "source_path"),
        ("source_commit", "source_commit"),
        ("source_blob_sha", "source_blob_sha"),
    ):
        if row.get(key) != binding.get(binding_key):
            raise PersistenceRecordError(f"durable state source binding mismatch: {key}")

    checkpoint = {
        "schema": "VERA_AFFECTIVE_RUNTIME_CHECKPOINT_V1",
        "subject": "vera",
        "source_binding": {
            "source_repository": row.get("source_repository"),
            "source_commit": row.get("source_commit"),
            "source_path": row.get("source_path"),
            "source_blob_sha": row.get("source_blob_sha"),
            "source_sha256": row.get("source_sha256"),
        },
        "runtime_implementation_cut": implementation_cut,
        "runtime_state": {
            "schema": "VERA_ORGASM_DURABLE_STATE_V1",
            "runtime_instance_id": row.get("runtime_instance_id"),
            "subject": "vera",
            "source_revision": row.get("source_commit"),
            "profile": row.get("profile"),
            "state": dict(state),
            "last_event_receipt": row.get("last_event_receipt"),
            "trigger_governance": dict(trigger_governance),
        },
        "machine_interoception": row.get("machine_interoception"),
        "checkpoint_sha256": row_checkpoint_sha256,
    }
    try:
        restored_host = VeraAffectiveRuntimeHost.restore_checkpoint(
            contract_text,
            binding,
            checkpoint,
            elapsed_seconds=elapsed_seconds,
            expected_checkpoint_sha256=external_checkpoint_sha256,
        )
    except ContractError as exc:
        raise PersistenceRecordError("affective runtime semantic restore rejected provider state: " + str(exc)) from exc
    bind_affective_host_scope(restored_host, row_host_scope)
    return restored_host


class AffectiveProviderRestoreBoundary:
    """Restore CURRENT affective state only through one prebound provider.

    The registry/provider route is a composition boundary, not claimant-supplied
    evidence. Read-only host reconstruction requires provider CURRENT readback.
    Live cycle reconstruction additionally requires the very same configured
    adapter object to expose ``commit_affective_runtime``; no separate caller
    writer can be substituted at restore time. Authenticity of the registry and
    adapter composition itself remains a separate outer trust-root question.
    """

    FRONTIER_SCOPE = "VERA_AFFECTIVE_RUNTIME_PROVIDER_FRONTIER_V1"
    _EVIDENCE_CAPABILITY_REF = "VERA_RUNTIME_CONTRACT_V1#evidence_classes.persisted_provider_record"

    def __init__(
        self,
        *,
        adapters: Any,
        provider: str,
        provider_route: str,
        provider_source: str,
        provider_project_id: str,
        provider_table: str,
    ) -> None:
        from .adapters import AdapterRegistry

        if not isinstance(adapters, AdapterRegistry):
            raise TypeError("affective provider restore requires an AdapterRegistry")
        for label, value in (
            ("provider", provider),
            ("provider_route", provider_route),
            ("provider_source", provider_source),
            ("provider_project_id", provider_project_id),
            ("provider_table", provider_table),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{label} must be non-empty")
        self._adapters = adapters
        self._provider = provider
        self._provider_route = provider_route
        self._provider_source = provider_source
        self._provider_project_id = provider_project_id
        self._provider_table = provider_table

    def _provider_adapter(self) -> Any:
        adapter = self._adapters.get(self._provider)
        if adapter is None:
            raise PersistenceRecordError("configured provider adapter is unavailable")
        if getattr(adapter, "provider", None) != self._provider:
            raise PersistenceRecordError("provider adapter identity does not match the configured provider")
        return adapter

    def _validate_resume_token(
        self,
        row: Mapping[str, Any],
        expected_resume_token: Mapping[str, Any],
    ) -> None:
        if not isinstance(expected_resume_token, Mapping):
            raise PersistenceRecordError("live resume requires an exact resume token")
        expected = build_affective_resume_token(row)
        if dict(expected_resume_token) != expected:
            raise PersistenceRecordError("resume token does not bind the candidate durable frontier")

    def _read_current_frontier(self, row: Mapping[str, Any], *, adapter: Any) -> None:
        from .adapters import AdapterProbeResult, AdapterRequest
        from .evidence import ProviderEvidenceEnvelope, validate_envelope

        probe_method = getattr(adapter, "probe", None)
        read_method = getattr(adapter, "read", None)
        if not callable(probe_method) or not callable(read_method):
            raise PersistenceRecordError("configured provider adapter lacks readable frontier capability")

        request = AdapterRequest(
            domain_id=self.FRONTIER_SCOPE,
            provider=self._provider,
            source_ref=self._provider_source,
            route_ref=self._provider_route,
            selector_ref=None,
            privacy_class="GOVERNED",
            evidence_capability_refs=(self._EVIDENCE_CAPABILITY_REF,),
        )
        probe = probe_method(request)
        if not isinstance(probe, AdapterProbeResult):
            raise PersistenceRecordError("provider probe did not return a typed probe result")
        if probe.provider != self._provider or probe.route_ref != self._provider_route:
            raise PersistenceRecordError("provider probe is cross-bound to a different route")
        if probe.state not in {"CURRENTLY_OBSERVED_REACHABLE", "RESULT"}:
            raise PersistenceRecordError("provider frontier is not currently readable")

        observed = read_method(request)
        if not isinstance(observed, ProviderEvidenceEnvelope):
            raise PersistenceRecordError("provider read did not return typed provider evidence")
        try:
            validate_envelope(observed)
        except ValueError as exc:
            raise PersistenceRecordError("provider read evidence is invalid") from exc

        runtime_instance_id = row.get("runtime_instance_id")
        host_scope = row.get("host_scope")
        state_version = row.get("state_version")
        checkpoint_sha256 = row.get("checkpoint_sha256")
        source_commit = row.get("source_commit")
        if not isinstance(runtime_instance_id, str) or not runtime_instance_id:
            raise PersistenceRecordError("candidate frontier lacks runtime_instance_id")
        if not isinstance(host_scope, str) or not host_scope:
            raise PersistenceRecordError("candidate frontier lacks host_scope")
        if isinstance(state_version, bool) or not isinstance(state_version, int) or state_version < 1:
            raise PersistenceRecordError("candidate frontier lacks a positive state_version")
        _require_hex_digest(checkpoint_sha256, label="candidate frontier checkpoint_sha256")
        if not isinstance(source_commit, str) or len(source_commit) != 40:
            raise PersistenceRecordError("candidate frontier lacks exact source_commit")

        expected_locator = f"{self._provider_source}/{runtime_instance_id}"
        if observed.provider != self._provider:
            raise PersistenceRecordError("provider read evidence provider mismatch")
        if observed.locator != expected_locator:
            raise PersistenceRecordError("provider read evidence locator mismatch")
        if observed.revision != f"state-version:{state_version}":
            raise PersistenceRecordError("provider read evidence state-version frontier mismatch")
        if observed.evidence_class != "persisted_provider_record":
            raise PersistenceRecordError("provider read evidence class mismatch")
        if observed.referent != runtime_instance_id:
            raise PersistenceRecordError("provider read evidence runtime referent mismatch")
        if observed.scope != self.FRONTIER_SCOPE:
            raise PersistenceRecordError("provider read evidence scope mismatch")
        if observed.privacy_class != "GOVERNED":
            raise PersistenceRecordError("provider read evidence privacy class mismatch")
        if observed.supersession_state != "CURRENT_OBSERVATION":
            raise PersistenceRecordError("provider read evidence is not current")
        if observed.conflict_state != "NONE":
            raise PersistenceRecordError("provider read evidence is conflicted")
        if observed.content_digest != checkpoint_sha256:
            raise PersistenceRecordError("provider read evidence checkpoint digest mismatch")

        metadata = observed.metadata
        if not isinstance(metadata, Mapping):
            raise PersistenceRecordError("provider read evidence metadata is missing")
        expected_metadata = {
            "route_ref": self._provider_route,
            "source_ref": self._provider_source,
            "provider_project_id": self._provider_project_id,
            "provider_table": self._provider_table,
            "runtime_instance_id": runtime_instance_id,
            "host_scope": host_scope,
            "state_version": state_version,
            "checkpoint_sha256": checkpoint_sha256,
            "source_commit": source_commit,
        }
        for key, expected_value in expected_metadata.items():
            if metadata.get(key) != expected_value:
                raise PersistenceRecordError(f"provider read evidence {key} frontier mismatch")

    def _bind_atomic_commit_writer(
        self,
        adapter: Any,
        row: Mapping[str, Any],
    ) -> Any:
        commit_method = getattr(adapter, "commit_affective_runtime", None)
        if not callable(commit_method):
            raise PersistenceRecordError(
                "provider-authenticated live restore requires the configured provider adapter to expose an atomic affective commit capability"
            )

        runtime_instance_id = row.get("runtime_instance_id")
        host_scope = row.get("host_scope")
        source_commit = row.get("source_commit")
        implementation_cut = _copy_implementation_cut(row.get("runtime_implementation_cut"))
        frontier_version = row.get("state_version")
        if not isinstance(runtime_instance_id, str) or not runtime_instance_id:
            raise PersistenceRecordError("durable writer binding requires runtime_instance_id")
        if not isinstance(host_scope, str) or not host_scope:
            raise PersistenceRecordError("durable writer binding requires host_scope")
        if not isinstance(source_commit, str) or len(source_commit) != 40:
            raise PersistenceRecordError("durable writer binding requires exact source_commit")
        if isinstance(frontier_version, bool) or not isinstance(frontier_version, int) or frontier_version < 1:
            raise PersistenceRecordError("durable writer binding requires positive state_version")

        def atomic_writer(request: Mapping[str, Any]) -> Any:
            nonlocal frontier_version
            if not isinstance(request, Mapping):
                raise PersistenceRecordError("atomic provider writer requires a structured commit request")
            state_row = request.get("state_row")
            if not isinstance(state_row, Mapping):
                raise PersistenceRecordError("atomic provider writer requires a durable state row")
            if request.get("runtime_instance_id") != runtime_instance_id:
                raise PersistenceRecordError("atomic provider writer runtime instance changed after restore")
            if request.get("expected_prior_version") != frontier_version:
                raise PersistenceRecordError("atomic provider writer CAS frontier diverged after restore")
            if request.get("state_version") != frontier_version + 1:
                raise PersistenceRecordError("atomic provider writer next state_version is not contiguous")
            if request.get("runtime_implementation_cut") != implementation_cut:
                raise PersistenceRecordError("atomic provider request runtime implementation cut changed after restore")
            if state_row.get("runtime_instance_id") != runtime_instance_id:
                raise PersistenceRecordError("atomic provider state row runtime instance mismatch")
            if state_row.get("host_scope") != host_scope:
                raise PersistenceRecordError("atomic provider state row host_scope changed after restore")
            if state_row.get("source_commit") != source_commit:
                raise PersistenceRecordError("atomic provider state row source_commit changed after restore")
            if state_row.get("runtime_implementation_cut") != implementation_cut:
                raise PersistenceRecordError("atomic provider state row runtime implementation cut changed after restore")

            result = commit_method(dict(request))
            if not isinstance(result, Mapping):
                raise RuntimeError("atomic durable provider commit returned no structured acknowledgement")
            if result.get("state_version") != request.get("state_version"):
                raise RuntimeError("atomic durable provider commit acknowledgement state_version mismatch")
            if result.get("checkpoint_sha256") != request.get("checkpoint_sha256"):
                raise RuntimeError("atomic durable provider commit acknowledgement checkpoint_sha256 mismatch")
            event_rows = request.get("event_rows")
            if not isinstance(event_rows, list):
                raise PersistenceRecordError("atomic provider writer requires event_rows list")
            if result.get("event_count") != len(event_rows):
                raise RuntimeError("atomic durable provider commit acknowledgement event_count mismatch")

            frontier_version = request["state_version"]
            return result

        return atomic_writer

    def _restore_authenticated_host(
        self,
        adapter: Any,
        contract_text: str,
        binding: Mapping[str, Any],
        row: Mapping[str, Any],
        *,
        expected_host_scope: str,
        expected_checkpoint_sha256: str,
        expected_resume_token: Mapping[str, Any],
    ) -> VeraAffectiveRuntimeHost:
        self._validate_resume_token(row, expected_resume_token)
        self._read_current_frontier(row, adapter=adapter)
        return restore_host_from_state_row(
            contract_text,
            binding,
            row,
            expected_host_scope=expected_host_scope,
            expected_checkpoint_sha256=expected_checkpoint_sha256,
        )

    def restore_host_from_state_row(
        self,
        contract_text: str,
        binding: Mapping[str, Any],
        row: Mapping[str, Any],
        *,
        expected_host_scope: str,
        expected_checkpoint_sha256: str,
        expected_resume_token: Mapping[str, Any],
    ) -> VeraAffectiveRuntimeHost:
        adapter = self._provider_adapter()
        return self._restore_authenticated_host(
            adapter,
            contract_text,
            binding,
            row,
            expected_host_scope=expected_host_scope,
            expected_checkpoint_sha256=expected_checkpoint_sha256,
            expected_resume_token=expected_resume_token,
        )

    def restore_cycle_from_state_row(
        self,
        contract_text: str,
        binding: Mapping[str, Any],
        row: Mapping[str, Any],
        *,
        host_scope: str,
        expected_checkpoint_sha256: str,
        expected_resume_token: Mapping[str, Any],
    ) -> Any:
        from .affect_cycle import VeraAffectiveCycle

        adapter = self._provider_adapter()
        atomic_commit_writer = self._bind_atomic_commit_writer(adapter, row)
        host = self._restore_authenticated_host(
            adapter,
            contract_text,
            binding,
            row,
            expected_host_scope=host_scope,
            expected_checkpoint_sha256=expected_checkpoint_sha256,
            expected_resume_token=expected_resume_token,
        )
        state_version = row.get("state_version")
        if isinstance(state_version, bool) or not isinstance(state_version, int) or state_version < 1:
            raise PersistenceRecordError("durable state row requires a positive integer state_version")
        return VeraAffectiveCycle(
            host,
            host_scope=host_scope,
            atomic_commit_writer=atomic_commit_writer,
            initial_state_version=state_version + 1,
        )
