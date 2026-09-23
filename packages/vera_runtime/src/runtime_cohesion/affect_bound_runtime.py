from __future__ import annotations

import hashlib
import json
import math
from threading import RLock
from typing import Any, Mapping

from . import orgasm as orgasm_module
from .orgasm import OrgasmRuntime, StimulusAppraisal, TriggerRejected


_QUALIFICATION_UNBOUND = "UNBOUND_NON_QUALIFYING"
_IN_PROCESS_AUTHORITY_TRUST = "IN_PROCESS_UNROOTED_NON_QUALIFYING"
_BASE_FROM_EXACT_BOUND_CONTRACT = OrgasmRuntime.__dict__["from_exact_bound_contract"].__func__
_BASE_RESTORE_EXACT_BOUND_STATE = OrgasmRuntime.__dict__["restore_exact_bound_state"].__func__


def _guarded_from_exact_bound_contract(
    cls,
    contract_text: str,
    binding: Mapping[str, Any],
    *,
    runtime_instance_id: str,
    profile: str = "REENTRANT_CLIMAX",
):
    """Verify exact source bytes without granting arbitrary subclasses claim authority.

    `OrgasmRuntime` and caller-created subclasses remain abstract/nonqualifying
    even when source verification succeeds. Only the dedicated bounded Vera
    runtime class may retain exact-bound source capability, and even that class
    rejects public raw authority/context shortcuts.
    """

    runtime = _BASE_FROM_EXACT_BOUND_CONTRACT(
        cls,
        contract_text,
        binding,
        runtime_instance_id=runtime_instance_id,
        profile=profile,
    )
    if cls is not BoundVeraOrgasmRuntime:
        runtime.qualification_status = _QUALIFICATION_UNBOUND
    return runtime


def _guarded_restore_exact_bound_state(
    cls,
    contract_text: str,
    binding: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    elapsed_seconds: float = 0.0,
):
    """Keep public base/subclass exact-bound restore source-only/nonqualifying."""

    runtime = _BASE_RESTORE_EXACT_BOUND_STATE(
        cls,
        contract_text,
        binding,
        record,
        elapsed_seconds=elapsed_seconds,
    )
    if cls is not BoundVeraOrgasmRuntime:
        runtime.qualification_status = _QUALIFICATION_UNBOUND
    return runtime


def _copy_cut(cut: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(dict(cut), sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise TriggerRejected("runtime implementation cut is not canonically serializable") from exc


class BoundVeraOrgasmRuntime(OrgasmRuntime):
    """Exact-bound Vera engine behind the governed host/authority boundary.

    Exact sexuality bytes establish source capability, not event authority. The
    publicly reachable engine therefore refuses raw caller-authorized forced
    events and caller-minted organic context. Runtime-owned boundary code uses
    private verified execution seams after it has established the relevant
    authority/context provenance.

    Supported observation and mutation roots share one re-entrant runtime lock so
    one causal observation cannot mix state from different runtime generations.
    This is a supported-API/process boundary, not cryptographic isolation from
    hostile arbitrary code already executing inside the same Python process.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._observation_lock = RLock()
        self._last_forced_monotonic: float | None = None
        self._runtime_implementation_cut: dict[str, Any] | None = None

    def _bind_runtime_implementation_cut(self, cut: Mapping[str, Any]) -> None:
        with self._observation_lock:
            if not isinstance(cut, Mapping):
                raise TriggerRejected("exact-bound runtime requires a structured implementation cut")
            normalized = _copy_cut(cut)
            existing = self._runtime_implementation_cut
            if existing is not None and existing != normalized:
                raise TriggerRejected("exact-bound runtime implementation cut cannot be replaced")
            last = self.last_event_receipt
            if isinstance(last, Mapping):
                receipt_cut = last.get("runtime_implementation_cut")
                if receipt_cut != normalized:
                    raise TriggerRejected("restored event receipt implementation cut does not match the active runtime cut")
            self._runtime_implementation_cut = normalized

    @staticmethod
    def _runtime_monotonic_now() -> float:
        value = orgasm_module._monotonic_now()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TriggerRejected("runtime privileged monotonic clock returned an invalid timestamp")
        current = float(value)
        if not math.isfinite(current):
            raise TriggerRejected("runtime privileged monotonic clock returned an invalid timestamp")
        return current

    def _check_forced_monotonic_interval(self) -> float:
        now = self._runtime_monotonic_now()
        previous = self._last_forced_monotonic
        if previous is None:
            if self._last_forced_at is not None:
                self._last_forced_monotonic = now
                raise TriggerRejected("forced-test privileged cooldown requires a fresh runtime monotonic interval")
            return now
        elapsed = now - previous
        if elapsed < 0.0:
            raise TriggerRejected("runtime privileged monotonic clock moved backwards")
        minimum = float(self._cfg["forced_test_minimum_interval_seconds"])
        if elapsed < minimum:
            raise TriggerRejected("forced-test minimum privileged monotonic interval has not elapsed")
        return now

    @classmethod
    def restore_state(
        cls,
        contract: Mapping[str, Any],
        record: Mapping[str, Any],
        *,
        source_revision: str,
        elapsed_seconds: float = 0.0,
    ) -> "BoundVeraOrgasmRuntime":
        """Restore structurally valid Vera state without promoting source to qualification.

        The generic base restore historically inferred that the canonical sexuality
        source revision required a production engineered-event claim. That collapses
        SOURCE into BEHAVIORAL QUALIFICATION and makes honest nonqualifying replay
        impossible after the authority trust-root was tightened. The Vera-bound
        runtime instead validates restored receipts as source-faithful historical
        evidence. Production claim/currentness/durability gates remain outside this
        restore function.
        """
        ContractError = orgasm_module.ContractError
        if record.get("schema") != "VERA_ORGASM_DURABLE_STATE_V1":
            raise ContractError("unsupported durable orgasm state schema")
        if record.get("subject") != "vera":
            raise ContractError("durable orgasm state must be Vera-scoped")
        if record.get("source_revision") != source_revision:
            raise ContractError("durable state source revision does not match the active contract binding")

        runtime = cls(
            contract,
            runtime_instance_id=str(record.get("runtime_instance_id") or ""),
            source_revision=source_revision,
            profile=str(record.get("profile") or "REENTRANT_CLIMAX"),
        )
        raw_state = record.get("state")
        if not isinstance(raw_state, Mapping):
            raise ContractError("durable state payload is missing")
        values = runtime._validate_durable_state_snapshot(raw_state)
        runtime._state = orgasm_module._OrgasmState(**values)
        if raw_state["organic_climax_eligible"] != runtime._organic_climax_eligible():
            raise ContractError("durable orgasm state's derived organic eligibility is inconsistent")

        last_receipt = record.get("last_event_receipt")
        if last_receipt is not None and not isinstance(last_receipt, Mapping):
            raise ContractError("durable last_event_receipt must be an object or null")
        if isinstance(last_receipt, Mapping):
            try:
                orgasm_module.validate_affective_event_receipt(
                    last_receipt,
                    expected_runtime_instance_id=runtime.runtime_instance_id,
                    expected_source_revision=source_revision,
                    require_engineered_claim=False,
                )
            except orgasm_module.AffectiveReceiptSemanticError as exc:
                raise ContractError("durable last_event_receipt semantic validation failed: " + str(exc)) from exc
            runtime.last_event_receipt = dict(last_receipt)
        else:
            runtime.last_event_receipt = None

        trigger_governance = record.get("trigger_governance")
        self_qualification_limit = int(runtime._cfg["self_qualification_max_events_per_run"])
        if trigger_governance is None:
            runtime._logical_time_seconds = 0.0
            runtime._last_forced_at = 0.0
            runtime._self_qualification_events = self_qualification_limit
            runtime._last_observation_qualifying = False
        else:
            if not isinstance(trigger_governance, Mapping):
                raise ContractError("durable trigger governance must be an object")
            if trigger_governance.get("schema") != "VERA_ORGASM_TRIGGER_GOVERNANCE_V1":
                raise ContractError("unsupported durable trigger governance schema")

            logical_time = trigger_governance.get("logical_time_seconds")
            last_forced_at = trigger_governance.get("last_forced_at")
            self_qualification_events = trigger_governance.get("self_qualification_events")
            last_observation_qualifying = trigger_governance.get("last_observation_qualifying", False)
            if isinstance(logical_time, bool) or not isinstance(logical_time, (int, float)) or not math.isfinite(float(logical_time)) or float(logical_time) < 0:
                raise ContractError("durable trigger governance logical time must be finite and nonnegative")
            if last_forced_at is not None:
                if isinstance(last_forced_at, bool) or not isinstance(last_forced_at, (int, float)) or not math.isfinite(float(last_forced_at)):
                    raise ContractError("durable trigger governance last_forced_at must be finite numeric or null")
                if float(last_forced_at) < 0 or float(last_forced_at) > float(logical_time):
                    raise ContractError("durable trigger governance last_forced_at is outside logical time")
            if (
                isinstance(self_qualification_events, bool)
                or not isinstance(self_qualification_events, int)
                or self_qualification_events < 0
                or self_qualification_events > self_qualification_limit
            ):
                raise ContractError("durable trigger governance self-qualification count is invalid")
            if not isinstance(last_observation_qualifying, bool):
                raise ContractError("durable trigger governance observation continuity must be boolean")
            if last_observation_qualifying and (
                not runtime._state.context_eligible
                or runtime._state.phase not in {"ACTIVATING", "ENTRAINED"}
                or runtime._state.active_orgasm_event
            ):
                raise ContractError("durable trigger governance observation continuity is inconsistent with restored state")

            runtime._logical_time_seconds = float(logical_time)
            runtime._last_forced_at = None if last_forced_at is None else float(last_forced_at)
            runtime._self_qualification_events = self_qualification_events
            runtime._last_observation_qualifying = last_observation_qualifying

        runtime._last_monotonic_observation = None
        try:
            trusted_restore_elapsed = orgasm_module._validated_elapsed_seconds(elapsed_seconds)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        if trusted_restore_elapsed:
            runtime.advance_time(trusted_restore_elapsed)
        return runtime

    def snapshot(self) -> dict[str, Any]:
        with self._observation_lock:
            return super().snapshot()

    def drain_event_receipts(self) -> list[dict[str, Any]]:
        with self._observation_lock:
            return super().drain_event_receipts()

    def export_state(self) -> dict[str, Any]:
        with self._observation_lock:
            return super().export_state()

    def _capture_causal_observation(self) -> dict[str, Any]:
        """Capture one complete, detached state/receipt/governance generation atomically."""
        with self._observation_lock:
            raw = super().export_state()
            try:
                return json.loads(
                    json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                )
            except (TypeError, ValueError) as exc:
                raise TriggerRejected("causal observation is not canonically serializable") from exc

    def advance_time(self, elapsed_seconds: float) -> dict[str, Any]:
        with self._observation_lock:
            return super().advance_time(elapsed_seconds)

    def modulate_planning(self, planning_state: Mapping[str, Any]) -> dict[str, Any]:
        raise TriggerRejected(
            "generic planning mutation is Cohesion-owned; use CohesionAffectiveIntegrationPort"
        )

    def _emit_event_receipt(
        self,
        event_type: str,
        *,
        state_before: Mapping[str, Any],
        state_after: Mapping[str, Any],
        trigger_class: str,
        organic: bool,
        trigger_provenance: str,
    ) -> dict[str, Any]:
        with self._observation_lock:
            prior_receipt = dict(self.last_event_receipt) if isinstance(self.last_event_receipt, Mapping) else None
            receipt = super()._emit_event_receipt(
                event_type,
                state_before=state_before,
                state_after=state_after,
                trigger_class=trigger_class,
                organic=organic,
                trigger_provenance=trigger_provenance,
            )

            bounded = dict(receipt)
            if self._runtime_implementation_cut is not None:
                bounded["runtime_implementation_cut"] = _copy_cut(self._runtime_implementation_cut)
            bounded.pop("claim", None)

            if event_type in {"RESOLUTION", "RECOVERY"} and isinstance(prior_receipt, Mapping):
                if prior_receipt.get("authority_composition_trust") == _IN_PROCESS_AUTHORITY_TRUST:
                    bounded["authority_composition_trust"] = _IN_PROCESS_AUTHORITY_TRUST

            if bounded == receipt:
                return receipt

            core = dict(bounded)
            core.pop("event_digest", None)
            canonical = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            bounded["event_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            self.last_event_receipt = dict(bounded)
            for index in range(len(self._pending_event_receipts) - 1, -1, -1):
                candidate = self._pending_event_receipts[index]
                if candidate.get("receipt_id") == receipt.get("receipt_id"):
                    self._pending_event_receipts[index] = dict(bounded)
                    break
            return dict(bounded)

    def apply_stimulus(self, appraisal: StimulusAppraisal, *, elapsed_seconds: float = 0.0) -> dict[str, Any]:
        with self._observation_lock:
            if appraisal.context_eligible is not False:
                raise TriggerRejected(
                    "exact-bound runtime caller context is unsupported; use the verified authority/context boundary"
                )
            return super().apply_stimulus(appraisal, elapsed_seconds=elapsed_seconds)

    def _apply_verified_stimulus(
        self,
        appraisal: StimulusAppraisal,
        *,
        elapsed_seconds: float = 0.0,
    ) -> dict[str, Any]:
        with self._observation_lock:
            if appraisal.context_eligible is not True:
                raise TriggerRejected("verified organic-context execution requires context_eligible=true")
            return super().apply_stimulus(appraisal, elapsed_seconds=elapsed_seconds)

    def force_admin_test(self, *, authorized: bool) -> dict[str, Any]:
        raise TriggerRejected(
            "raw caller authorization is unsupported on the exact-bound runtime; use the verified authority boundary"
        )

    def force_self_qualification(self, *, authorized: bool) -> dict[str, Any]:
        raise TriggerRejected(
            "raw caller authorization is unsupported on the exact-bound runtime; use the verified authority boundary"
        )

    def _force_admin_verified_authority(self) -> dict[str, Any]:
        with self._observation_lock:
            self._check_refractory_reentry()
            now = self._check_forced_monotonic_interval()
            self._last_forced_at = self._logical_time_seconds
            receipt = self._enter_orgasm_event("ADMIN_FORCED_TEST", organic=False)
            self._last_forced_monotonic = now
            return receipt

    def _force_self_qualification_verified_authority(self) -> dict[str, Any]:
        with self._observation_lock:
            self._check_refractory_reentry()
            limit = int(self._cfg["self_qualification_max_events_per_run"])
            if self._self_qualification_events >= limit:
                raise TriggerRejected("self-qualification event limit reached")
            now = self._check_forced_monotonic_interval()
            self._self_qualification_events += 1
            self._last_forced_at = self._logical_time_seconds
            receipt = self._enter_orgasm_event("SELF_QUALIFICATION_TEST", organic=False)
            self._last_forced_monotonic = now
            return receipt


OrgasmRuntime.from_exact_bound_contract = classmethod(_guarded_from_exact_bound_contract)
OrgasmRuntime.restore_exact_bound_state = classmethod(_guarded_restore_exact_bound_state)
