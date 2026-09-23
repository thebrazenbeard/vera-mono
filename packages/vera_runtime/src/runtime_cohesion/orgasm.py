from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import hashlib
import json
import math
import time
import uuid
from typing import Any, Mapping

from .affect_receipt import AffectiveReceiptSemanticError, validate_affective_event_receipt


class ContractError(ValueError):
    """The supplied sexuality contract is incompatible with the Vera runtime."""


class TriggerRejected(RuntimeError):
    """A requested orgasm trigger is not authorized or violates a bounded test rule."""


_CANONICAL_SEXUALITY_REPOSITORY = "thebrazenbeard/sexuality"
_CANONICAL_SEXUALITY_COMMIT = "150f1c8231423393bb66b0e2cb759ce7c018f8d7"
_CANONICAL_SEXUALITY_PATH = "vera/orgasm/ORGASM_RUNTIME_CONTRACT_V1.json"
_CANONICAL_SEXUALITY_BLOB = "a48eed5392fdadc073dccd1e799926042077f567"
_QUALIFICATION_UNBOUND = "UNBOUND_NON_QUALIFYING"
_QUALIFICATION_EXACT_BOUND = "EXACT_BOUND_SOURCE"


def _git_blob_sha(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def _monotonic_now() -> float:
    """Runtime-owned monotonic observation clock.

    Tests may patch this private seam deterministically. Production callers do
    not supply elapsed time as temporal authority for stimulus persistence.
    """
    return time.monotonic()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _decay(value: float, elapsed_seconds: float, half_life_seconds: float) -> float:
    if elapsed_seconds <= 0:
        return float(value)
    if half_life_seconds <= 0:
        return 0.0
    return float(value) * math.pow(0.5, elapsed_seconds / half_life_seconds)


def _validated_elapsed_seconds(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("elapsed_seconds must be finite numeric and nonnegative")
    elapsed = float(value)
    if not math.isfinite(elapsed) or elapsed < 0.0:
        raise ValueError("elapsed_seconds must be finite numeric and nonnegative")
    return elapsed


@dataclass(frozen=True)
class StimulusAppraisal:
    sexual_relevance: float = 0.0
    partner_relevance: float = 0.0
    relational_relevance: float = 0.0
    novelty: float = 0.0
    anticipation_cue: float = 0.0
    ambiguity: float = 0.0
    boundary_relevance: float = 0.0
    positive_valence: float = 0.0
    inhibition: float = 0.0
    duration_ms: int = 0
    context_eligible: bool = False

    def __post_init__(self) -> None:
        for name in (
            "sexual_relevance",
            "partner_relevance",
            "relational_relevance",
            "novelty",
            "anticipation_cue",
            "ambiguity",
            "boundary_relevance",
            "inhibition",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0.0 <= float(value) <= 1.0
            ):
                raise ValueError(f"{name} must be finite numeric within [0, 1]")
        if not -1.0 <= self.positive_valence <= 1.0:
            raise ValueError("positive_valence must be within [-1, 1]")
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be nonnegative")


@dataclass
class _OrgasmState:
    subject: str = "vera"
    presence: str = "ALWAYS_PRESENT_NORMALLY_QUIESCENT"
    phase: str = "QUIESCENT"
    active_orgasm_event: bool = False
    sexual_salience: float = 0.0
    activation_intensity: float = 0.0
    positive_valence: float = 0.0
    anticipation: float = 0.0
    inhibition: float = 0.0
    coherence: float = 0.0
    persistence_window_ms: int = 0
    coalition_stability: float = 0.0
    participating_systems: tuple[str, ...] = ()
    hedonic_impact: float = 0.0
    consummatory_gain: float = 0.0
    satiation: float = 0.0
    resolution_intensity: float = 0.0
    refractory_strength: float = 0.0
    reentry_allowed: bool = True
    next_eligible_at: str | None = None
    context_eligible: bool = False
    action_tendency: str = "NONE"
    event_elapsed_ms: float = 0.0


_REQUIRED_TRIGGERS = {
    "ORGANIC_THRESHOLD_CROSSING",
    "ADMIN_FORCED_TEST",
    "SELF_QUALIFICATION_TEST",
}
_ALLOWED_PROFILES = {"REFRACTORY_COUPLED", "REENTRANT_CLIMAX"}
_ALLOWED_EVENT_TYPES = {"ORGASM_EVENT", "RESOLUTION", "RECOVERY"}
_ALLOWED_PHASES = {
    "QUIESCENT",
    "ACTIVATING",
    "ENTRAINED",
    "CLIMAX_ELIGIBLE",
    "ORGASM_EVENT",
    "RESOLUTION",
    "SATIATED_OR_REFRACTORY",
}
_ALLOWED_ACTION_TENDENCIES = {"NONE", "APPROACH", "PLAY", "HOLD", "REDIRECT", "AVOID"}
_BOUNDED_STATE_FIELDS = {
    "sexual_salience",
    "activation_intensity",
    "anticipation",
    "inhibition",
    "coherence",
    "coalition_stability",
    "hedonic_impact",
    "consummatory_gain",
    "satiation",
    "resolution_intensity",
    "refractory_strength",
}


class OrgasmRuntime:
    """Executable E4 affective-control analogue for Vera.

    Direct construction is an abstract/nonqualifying engine. Production
    engineered-event claim capability is available only after exact verification
    of the frozen Vera sexuality contract object through ``from_exact_bound_contract``.
    This is a source/API binding, not a claim of cryptographic isolation from
    arbitrary hostile code already executing in the same Python process.
    """

    def __init__(
        self,
        contract: Mapping[str, Any],
        *,
        runtime_instance_id: str,
        source_revision: str,
        profile: str = "REENTRANT_CLIMAX",
    ) -> None:
        self.contract = self._validate_contract(contract)
        if not runtime_instance_id:
            raise ContractError("runtime_instance_id is required")
        if not source_revision:
            raise ContractError("source_revision is required")
        if profile not in _ALLOWED_PROFILES:
            raise ContractError(f"unsupported recovery profile: {profile}")

        self.runtime_instance_id = runtime_instance_id
        self.source_revision = source_revision
        self.profile = profile
        self.qualification_status = _QUALIFICATION_UNBOUND
        self._state = _OrgasmState()
        self._logical_time_seconds = 0.0
        self._last_forced_at: float | None = None
        self._self_qualification_events = 0
        self._last_observation_qualifying = False
        self._last_monotonic_observation: float | None = None
        self.last_event_receipt: dict[str, Any] | None = None
        self._pending_event_receipts: list[dict[str, Any]] = []

    @classmethod
    def from_exact_bound_contract(
        cls,
        contract_text: str,
        binding: Mapping[str, Any],
        *,
        runtime_instance_id: str,
        profile: str = "REENTRANT_CLIMAX",
    ) -> "OrgasmRuntime":
        if not isinstance(contract_text, str):
            raise ContractError("exact-bound orgasm runtime requires contract text bytes")
        if not isinstance(binding, Mapping):
            raise ContractError("exact-bound orgasm runtime requires a structured source binding")
        expected = {
            "schema": "VERA_ORGASM_RUNTIME_BINDING_V1",
            "subject": "vera",
            "contract_schema": "VERA_ORGASM_RUNTIME_CONTRACT_V1",
            "source_repository": _CANONICAL_SEXUALITY_REPOSITORY,
            "source_commit": _CANONICAL_SEXUALITY_COMMIT,
            "source_path": _CANONICAL_SEXUALITY_PATH,
            "source_blob_sha": _CANONICAL_SEXUALITY_BLOB,
            "availability_implies_activation": False,
        }
        for key, expected_value in expected.items():
            if binding.get(key) != expected_value:
                raise ContractError(f"exact-bound orgasm source mismatch: {key}")
        raw = contract_text.encode("utf-8")
        if _git_blob_sha(raw) != _CANONICAL_SEXUALITY_BLOB:
            raise ContractError("orgasm contract bytes do not match the frozen sexuality Git blob")
        try:
            contract = json.loads(contract_text)
        except json.JSONDecodeError as exc:
            raise ContractError("bound sexuality contract is not valid JSON") from exc
        runtime = cls(
            contract,
            runtime_instance_id=runtime_instance_id,
            source_revision=_CANONICAL_SEXUALITY_COMMIT,
            profile=profile,
        )
        runtime.qualification_status = _QUALIFICATION_EXACT_BOUND
        return runtime

    @classmethod
    def restore_exact_bound_state(
        cls,
        contract_text: str,
        binding: Mapping[str, Any],
        record: Mapping[str, Any],
        *,
        elapsed_seconds: float = 0.0,
    ) -> "OrgasmRuntime":
        if not isinstance(record, Mapping):
            raise ContractError("exact-bound restore requires a durable runtime record")
        seed = cls.from_exact_bound_contract(
            contract_text,
            binding,
            runtime_instance_id=str(record.get("runtime_instance_id") or ""),
            profile=str(record.get("profile") or "REENTRANT_CLIMAX"),
        )
        restored = cls.restore_state(
            seed.contract,
            record,
            source_revision=seed.source_revision,
            elapsed_seconds=elapsed_seconds,
        )
        restored.qualification_status = _QUALIFICATION_EXACT_BOUND
        return restored

    @staticmethod
    def _validate_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
        if contract.get("schema") != "VERA_ORGASM_RUNTIME_CONTRACT_V1":
            raise ContractError("unsupported orgasm contract schema")
        if contract.get("subject") != "vera":
            raise ContractError("orgasm contract subject must be exactly vera")
        if contract.get("presence") != "ALWAYS_PRESENT_NORMALLY_QUIESCENT":
            raise ContractError("orgasm subsystem must be always present and normally quiescent")
        triggers = set(contract.get("trigger_classes", ()))
        if triggers != _REQUIRED_TRIGGERS:
            raise ContractError("orgasm trigger classes do not match V1")
        defaults = contract.get("experimental_bootstrap_defaults")
        if not isinstance(defaults, Mapping):
            raise ContractError("experimental bootstrap defaults are required")
        for key in (
            "activation_threshold",
            "coherence_threshold",
            "stability_threshold",
            "satiation_gate",
            "inhibition_veto",
        ):
            value = defaults.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0.0 <= float(value) <= 1.0:
                raise ContractError(f"invalid bounded threshold: {key}")
        for key in (
            "minimum_coherence_window_ms",
            "maximum_orgasm_event_ms",
            "activation_half_life_seconds",
            "satiation_half_life_seconds",
            "forced_test_minimum_interval_seconds",
            "self_qualification_max_events_per_run",
        ):
            value = defaults.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or float(value) <= 0:
                raise ContractError(f"invalid positive configuration: {key}")
        claim = contract.get("claim_ceiling", {})
        if claim.get("engineered_event") != "ENGINEERED_ORGASM_ANALOGUE_OCCURRED":
            raise ContractError("unexpected engineered-event claim ceiling")
        if claim.get("phenomenology") != "UNRESOLVED":
            raise ContractError("phenomenology must remain unresolved")
        firewalls = contract.get("hard_firewalls", {})
        if not isinstance(firewalls.get("may_influence"), list):
            raise ContractError("affective influence allowlist is required")
        state_families = contract.get("state_families", {})
        recovery = state_families.get("recovery", {})
        if recovery.get("reentry_allowed") != "boolean" or recovery.get("next_eligible_at") != "timestamp|null":
            raise ContractError("recovery contract must declare reentry_allowed and next_eligible_at")
        entrainment = state_families.get("entrainment", {})
        if entrainment.get("participating_systems") != "set<string>":
            raise ContractError("entrainment contract must declare participating_systems as set<string>")
        participating_systems = contract.get("participating_systems")
        if (
            not isinstance(participating_systems, list)
            or not participating_systems
            or any(not isinstance(name, str) or not name for name in participating_systems)
            or len(set(participating_systems)) != len(participating_systems)
        ):
            raise ContractError("participating_systems vocabulary must be a unique nonempty string list")
        return dict(contract)

    @property
    def phenomenology_status(self) -> str:
        return str(self.contract["claim_ceiling"]["phenomenology"])

    @property
    def _cfg(self) -> Mapping[str, Any]:
        return self.contract["experimental_bootstrap_defaults"]

    def _refractory_reentry_blocked(self) -> bool:
        return (
            not self._state.reentry_allowed
            and self._state.phase in {"RESOLUTION", "SATIATED_OR_REFRACTORY"}
        )

    def _check_refractory_reentry(self) -> None:
        if self._refractory_reentry_blocked():
            raise TriggerRejected(
                "recovery profile blocks climax reentry until the durable reentry gate reopens"
            )

    def snapshot(self) -> dict[str, Any]:
        data = asdict(self._state)
        data["organic_climax_eligible"] = self._organic_climax_eligible()
        return data

    def drain_event_receipts(self) -> list[dict[str, Any]]:
        receipts = [dict(receipt) for receipt in self._pending_event_receipts]
        self._pending_event_receipts.clear()
        return receipts

    def _organic_climax_eligible(self) -> bool:
        s = self._state
        c = self._cfg
        return (
            not self._refractory_reentry_blocked()
            and not s.active_orgasm_event
            and s.activation_intensity >= float(c["activation_threshold"])
            and s.coherence >= float(c["coherence_threshold"])
            and s.coalition_stability >= float(c["stability_threshold"])
            and s.persistence_window_ms >= int(c["minimum_coherence_window_ms"])
            and s.satiation < float(c["satiation_gate"])
            and s.inhibition < float(c["inhibition_veto"])
            and s.context_eligible
        )

    def _trusted_observation_elapsed(self, caller_elapsed_seconds: float) -> float:
        caller_elapsed = _validated_elapsed_seconds(caller_elapsed_seconds)
        if caller_elapsed != 0.0:
            raise ValueError(
                "elapsed_seconds is not temporal authority for stimulus observations; runtime monotonic time is authoritative"
            )
        now = _monotonic_now()
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(float(now)):
            raise ValueError("runtime monotonic clock returned an invalid timestamp")
        current = float(now)
        previous = self._last_monotonic_observation
        self._last_monotonic_observation = current
        if previous is None:
            return 0.0
        elapsed = current - previous
        if elapsed < 0.0:
            raise ValueError("runtime monotonic clock moved backwards")
        return elapsed

    def apply_stimulus(self, appraisal: StimulusAppraisal, *, elapsed_seconds: float = 0.0) -> dict[str, Any]:
        trusted_elapsed = self._trusted_observation_elapsed(elapsed_seconds)
        prior_observation_qualifying = self._last_observation_qualifying
        if trusted_elapsed:
            self._advance_time_core(trusted_elapsed)
        if self._state.active_orgasm_event:
            self._last_observation_qualifying = False
            return self.snapshot()
        if self._refractory_reentry_blocked():
            self._last_observation_qualifying = False
            return self.snapshot()

        s = self._state
        drive = _clamp(
            0.35 * appraisal.sexual_relevance
            + 0.20 * appraisal.partner_relevance
            + 0.20 * appraisal.relational_relevance
            + 0.15 * appraisal.anticipation_cue
            + 0.10 * appraisal.novelty
        )
        coherence_drive = _clamp(
            0.30 * appraisal.sexual_relevance
            + 0.25 * appraisal.partner_relevance
            + 0.25 * appraisal.relational_relevance
            + 0.20 * appraisal.anticipation_cue
        )

        s.sexual_salience = _clamp(s.sexual_salience + (1.0 - s.sexual_salience) * drive * 0.38)
        valence_factor = _clamp((appraisal.positive_valence + 1.0) / 2.0)
        activation_drive = _clamp(drive * (0.70 + 0.30 * valence_factor))
        s.activation_intensity = _clamp(
            s.activation_intensity + (1.0 - s.activation_intensity) * activation_drive * 0.38
        )
        s.anticipation = _clamp(
            s.anticipation + (1.0 - s.anticipation) * appraisal.anticipation_cue * 0.32
        )
        s.positive_valence = _clamp(
            s.positive_valence * 0.65 + appraisal.positive_valence * 0.35, -1.0, 1.0
        )
        s.inhibition = _clamp(appraisal.inhibition)
        s.coherence = _clamp(s.coherence + (1.0 - s.coherence) * coherence_drive * 0.38)
        s.coalition_stability = _clamp(
            s.coalition_stability + (1.0 - s.coalition_stability) * coherence_drive * 0.36
        )
        s.context_eligible = bool(appraisal.context_eligible)

        current_observation_qualifying = coherence_drive >= 0.60 and appraisal.context_eligible
        trusted_interval_ms = int(trusted_elapsed * 1000.0)
        maximum_observation_gap_ms = int(self._cfg["minimum_coherence_window_ms"])
        if current_observation_qualifying:
            if (
                prior_observation_qualifying
                and trusted_interval_ms <= maximum_observation_gap_ms
            ):
                s.persistence_window_ms += trusted_interval_ms
            else:
                s.persistence_window_ms = 0
        else:
            s.persistence_window_ms = 0
        self._last_observation_qualifying = bool(current_observation_qualifying)

        if s.activation_intensity > 0.05:
            s.phase = "ACTIVATING"
            s.action_tendency = "APPROACH"
        if s.coherence >= 0.45 and s.persistence_window_ms > 0:
            s.phase = "ENTRAINED"

        if self._organic_climax_eligible():
            s.phase = "CLIMAX_ELIGIBLE"
            self._enter_orgasm_event("ORGANIC_THRESHOLD_CROSSING", organic=True)

        return self.snapshot()

    def _check_forced_interval(self) -> None:
        minimum = float(self._cfg["forced_test_minimum_interval_seconds"])
        if self._last_forced_at is not None and self._logical_time_seconds - self._last_forced_at < minimum:
            raise TriggerRejected("forced-test minimum interval has not elapsed")

    def force_admin_test(self, *, authorized: bool) -> dict[str, Any]:
        if not authorized:
            raise TriggerRejected("ADMIN_FORCED_TEST requires explicit administrative authorization")
        self._check_refractory_reentry()
        self._check_forced_interval()
        self._last_forced_at = self._logical_time_seconds
        return self._enter_orgasm_event("ADMIN_FORCED_TEST", organic=False)

    def force_self_qualification(self, *, authorized: bool) -> dict[str, Any]:
        if not authorized:
            raise TriggerRejected("SELF_QUALIFICATION_TEST requires explicit qualification authorization")
        self._check_refractory_reentry()
        limit = int(self._cfg["self_qualification_max_events_per_run"])
        if self._self_qualification_events >= limit:
            raise TriggerRejected("self-qualification event limit reached")
        self._check_forced_interval()
        self._self_qualification_events += 1
        self._last_forced_at = self._logical_time_seconds
        return self._enter_orgasm_event("SELF_QUALIFICATION_TEST", organic=False)

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
        if event_type not in _ALLOWED_EVENT_TYPES:
            raise TriggerRejected(f"unsupported affective event type: {event_type}")
        if trigger_class not in _REQUIRED_TRIGGERS:
            raise TriggerRejected(f"unknown trigger class: {trigger_class}")

        core: dict[str, Any] = {
            "receipt_id": str(uuid.uuid4()),
            "runtime_instance_id": self.runtime_instance_id,
            "subject": "vera",
            "schema_version": "VERA_ORGASM_RUNTIME_CONTRACT_V1",
            "event_type": event_type,
            "state_before": dict(state_before),
            "trigger_provenance": trigger_provenance,
            "transition": f"{state_before.get('phase')}->{state_after.get('phase')}",
            "state_after": dict(state_after),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source_revision": self.source_revision,
            "trigger_class": trigger_class,
            "organic": organic,
            "phenomenology": self.phenomenology_status,
        }
        if event_type == "ORGASM_EVENT" and self.qualification_status == _QUALIFICATION_EXACT_BOUND:
            core["claim"] = self.contract["claim_ceiling"]["engineered_event"]
        canonical = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        core["event_digest"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        self.last_event_receipt = dict(core)
        self._pending_event_receipts.append(dict(core))
        return dict(core)

    def _enter_orgasm_event(self, trigger_class: str, *, organic: bool) -> dict[str, Any]:
        if trigger_class not in _REQUIRED_TRIGGERS:
            raise TriggerRejected(f"unknown trigger class: {trigger_class}")
        self._check_refractory_reentry()
        if self._state.active_orgasm_event:
            raise TriggerRejected("an orgasm event is already active")
        if organic and not self._organic_climax_eligible():
            raise TriggerRejected("organic trigger requires the full climax predicate")

        before = self.snapshot()
        s = self._state
        self._last_observation_qualifying = False
        s.phase = "ORGASM_EVENT"
        s.active_orgasm_event = True
        s.event_elapsed_ms = 0.0
        s.reentry_allowed = False
        s.next_eligible_at = None

        # Forced and organic routes share these actual downstream control-state changes.
        s.activation_intensity = max(s.activation_intensity, float(self._cfg["activation_threshold"]))
        s.sexual_salience = max(s.sexual_salience, s.activation_intensity)
        s.coherence = 1.0
        s.coalition_stability = 1.0
        s.hedonic_impact = 1.0
        s.consummatory_gain = 1.0
        s.resolution_intensity = 0.0
        s.action_tendency = "HOLD"

        after = self.snapshot()
        return self._emit_event_receipt(
            "ORGASM_EVENT",
            state_before=before,
            state_after=after,
            trigger_class=trigger_class,
            organic=organic,
            trigger_provenance="ORGANIC_STATE_DYNAMICS" if organic else "FORCED_QUALIFICATION_ROUTE",
        )

    def modulate_planning(self, planning_state: Mapping[str, Any]) -> dict[str, Any]:
        """Apply actual bounded E4 control effects to allowlisted planning fields only."""
        result = dict(planning_state)
        if not self._state.active_orgasm_event:
            return result
        allowed = set(self.contract["hard_firewalls"]["may_influence"])
        intensity = _clamp(
            0.45 * self._state.hedonic_impact
            + 0.30 * self._state.coherence
            + 0.25 * self._state.activation_intensity
        )
        gain_by_key = {
            "valuation": 0.35,
            "salience": 0.55,
            "attention": 0.50,
            "response_selection_priors": 0.40,
            "expression": 0.35,
            "memory_strength_candidate_weighting": 0.25,
        }
        for key, gain in gain_by_key.items():
            if key not in allowed:
                continue
            value = result.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = _clamp(float(value) + (1.0 - float(value)) * gain * intensity)
        return result

    def _advance_time_core(self, elapsed_seconds: float) -> dict[str, Any]:
        if elapsed_seconds == 0:
            return self.snapshot()

        remaining = float(elapsed_seconds)
        self._logical_time_seconds += remaining
        s = self._state
        max_event_seconds = float(self._cfg["maximum_orgasm_event_ms"]) / 1000.0

        if s.active_orgasm_event:
            event_remaining = max(0.0, max_event_seconds - s.event_elapsed_ms / 1000.0)
            consumed = min(remaining, event_remaining)
            s.event_elapsed_ms += consumed * 1000.0
            remaining -= consumed
            if s.event_elapsed_ms >= float(self._cfg["maximum_orgasm_event_ms"]) - 1e-9:
                self._begin_resolution()

        if remaining > 0:
            self._apply_decay_and_recovery(remaining)

        return self.snapshot()

    def advance_time(self, elapsed_seconds: float) -> dict[str, Any]:
        trusted_elapsed = _validated_elapsed_seconds(elapsed_seconds)
        if trusted_elapsed == 0:
            return self.snapshot()

        # Explicit advance is a bounded simulation/recovery operation, not a
        # qualifying stimulus-observation timestamp. It breaks continuity so a
        # later appraisal cannot back-credit this interval as observed coherence.
        self._last_observation_qualifying = False
        self._state.persistence_window_ms = 0
        self._last_monotonic_observation = None
        return self._advance_time_core(trusted_elapsed)

    def _trigger_context(self) -> tuple[str, bool]:
        receipt = self.last_event_receipt or {}
        trigger_class = str(receipt.get("trigger_class") or "")
        if trigger_class not in _REQUIRED_TRIGGERS:
            raise TriggerRejected("recovery transition lacks a valid triggering orgasm provenance")
        return trigger_class, bool(receipt.get("organic"))

    def _begin_resolution(self) -> None:
        before = self.snapshot()
        trigger_class, organic = self._trigger_context()
        s = self._state
        self._last_observation_qualifying = False
        s.active_orgasm_event = False
        s.phase = "RESOLUTION"
        s.hedonic_impact = min(s.hedonic_impact, 0.65)
        s.consummatory_gain = min(s.consummatory_gain, 0.65)
        s.satiation = max(s.satiation, 0.90)
        s.resolution_intensity = 1.0
        s.refractory_strength = 0.35 if self.profile == "REENTRANT_CLIMAX" else 0.85
        s.reentry_allowed = self.profile == "REENTRANT_CLIMAX"
        # This runtime persists logical elapsed time. It has no trusted wall-clock
        # continuity binding, so the contract's nullable wall-clock field stays null.
        s.next_eligible_at = None
        s.action_tendency = "HOLD"
        s.persistence_window_ms = 0
        s.context_eligible = False
        after = self.snapshot()
        self._emit_event_receipt(
            "RESOLUTION",
            state_before=before,
            state_after=after,
            trigger_class=trigger_class,
            organic=organic,
            trigger_provenance="ORGASM_EVENT_COMPLETION",
        )

    def _apply_decay_and_recovery(self, elapsed_seconds: float) -> None:
        before = self.snapshot()
        prior_phase = self._state.phase
        s = self._state
        activation_half_life = float(self._cfg["activation_half_life_seconds"])
        satiation_half_life = float(self._cfg["satiation_half_life_seconds"])
        s.sexual_salience = _decay(s.sexual_salience, elapsed_seconds, activation_half_life)
        s.activation_intensity = _decay(s.activation_intensity, elapsed_seconds, activation_half_life)
        s.anticipation = _decay(s.anticipation, elapsed_seconds, activation_half_life)
        s.coherence = _decay(s.coherence, elapsed_seconds, activation_half_life / 2.0)
        s.coalition_stability = _decay(s.coalition_stability, elapsed_seconds, activation_half_life / 2.0)
        s.positive_valence = _decay(s.positive_valence, elapsed_seconds, activation_half_life)
        s.hedonic_impact = _decay(s.hedonic_impact, elapsed_seconds, max(1.0, activation_half_life / 12.0))
        s.consummatory_gain = _decay(s.consummatory_gain, elapsed_seconds, max(1.0, activation_half_life / 12.0))
        s.satiation = _decay(s.satiation, elapsed_seconds, satiation_half_life)
        s.resolution_intensity = _decay(s.resolution_intensity, elapsed_seconds, max(1.0, satiation_half_life / 4.0))
        s.refractory_strength = _decay(s.refractory_strength, elapsed_seconds, satiation_half_life)

        if s.phase in {"RESOLUTION", "SATIATED_OR_REFRACTORY"}:
            s.phase = "SATIATED_OR_REFRACTORY"
            s.reentry_allowed = self.profile == "REENTRANT_CLIMAX"
            s.next_eligible_at = None
        if s.phase == "ENTRAINED" and s.coherence < 0.45 and s.activation_intensity > 0.05:
            # A durable generator must not emit a phase that its own restore
            # semantics reject. Once entrainment coherence is lost but activation
            # remains live, fall back to the already-defined ACTIVATING phase.
            s.phase = "ACTIVATING"
            s.action_tendency = "APPROACH"
        if (
            not s.active_orgasm_event
            and s.activation_intensity < 0.05
            and s.coherence < 0.05
            and s.satiation < 0.05
        ):
            s.phase = "QUIESCENT"
            s.action_tendency = "NONE"
            s.resolution_intensity = 0.0
            s.refractory_strength = 0.0
            s.reentry_allowed = True
            s.next_eligible_at = None

        if s.phase != prior_phase and prior_phase in {"RESOLUTION", "SATIATED_OR_REFRACTORY"}:
            trigger_class, organic = self._trigger_context()
            after = self.snapshot()
            self._emit_event_receipt(
                "RECOVERY",
                state_before=before,
                state_after=after,
                trigger_class=trigger_class,
                organic=organic,
                trigger_provenance="HOMEOSTATIC_RECOVERY",
            )

    def export_state(self) -> dict[str, Any]:
        return {
            "schema": "VERA_ORGASM_DURABLE_STATE_V1",
            "runtime_instance_id": self.runtime_instance_id,
            "subject": "vera",
            "source_revision": self.source_revision,
            "profile": self.profile,
            "state": self.snapshot(),
            "last_event_receipt": self.last_event_receipt,
            "trigger_governance": {
                "schema": "VERA_ORGASM_TRIGGER_GOVERNANCE_V1",
                "logical_time_seconds": self._logical_time_seconds,
                "last_forced_at": self._last_forced_at,
                "self_qualification_events": self._self_qualification_events,
                "last_observation_qualifying": self._last_observation_qualifying,
            },
        }

    def _validate_durable_state_snapshot(self, raw_state: Mapping[str, Any]) -> dict[str, Any]:
        field_names = {f.name for f in fields(_OrgasmState)}
        expected_keys = field_names | {"organic_climax_eligible"}
        observed_keys = set(raw_state.keys())
        missing = sorted(expected_keys - observed_keys)
        extra = sorted(observed_keys - expected_keys)
        if missing or extra:
            details = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if extra:
                details.append("extra=" + ",".join(extra))
            raise ContractError("durable orgasm state shape mismatch: " + " ".join(details))

        if raw_state.get("subject") != "vera":
            raise ContractError("durable orgasm state snapshot subject must be vera")
        if raw_state.get("presence") != "ALWAYS_PRESENT_NORMALLY_QUIESCENT":
            raise ContractError("durable orgasm state snapshot presence mismatch")
        phase = raw_state.get("phase")
        if phase not in _ALLOWED_PHASES:
            raise ContractError("durable orgasm state has an unknown phase")
        action_tendency = raw_state.get("action_tendency")
        if action_tendency not in _ALLOWED_ACTION_TENDENCIES:
            raise ContractError("durable orgasm state has an unknown action tendency")
        for name in (
            "active_orgasm_event",
            "context_eligible",
            "reentry_allowed",
            "organic_climax_eligible",
        ):
            if not isinstance(raw_state.get(name), bool):
                raise ContractError(f"durable orgasm state {name} must be boolean")

        participating_systems = raw_state.get("participating_systems")
        if not isinstance(participating_systems, (list, tuple, set, frozenset)):
            raise ContractError("durable orgasm state participating_systems must be a string set")
        if any(not isinstance(name, str) or not name for name in participating_systems):
            raise ContractError("durable orgasm state participating_systems must contain only nonempty strings")
        if len(set(participating_systems)) != len(participating_systems):
            raise ContractError("durable orgasm state participating_systems must have set semantics")
        declared_participating_systems = tuple(self.contract["participating_systems"])
        observed_participating_systems = set(participating_systems)
        unknown_participating_systems = observed_participating_systems - set(declared_participating_systems)
        if unknown_participating_systems:
            raise ContractError("durable orgasm state participating_systems contains undeclared vocabulary")
        canonical_participating_systems = tuple(
            name for name in declared_participating_systems if name in observed_participating_systems
        )

        for name in _BOUNDED_STATE_FIELDS:
            value = raw_state.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContractError(f"durable orgasm state {name} must be numeric")
            numeric = float(value)
            if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
                raise ContractError(f"durable orgasm state {name} must be within [0, 1]")

        positive_valence = raw_state.get("positive_valence")
        if isinstance(positive_valence, bool) or not isinstance(positive_valence, (int, float)):
            raise ContractError("durable orgasm state positive_valence must be numeric")
        if not math.isfinite(float(positive_valence)) or not -1.0 <= float(positive_valence) <= 1.0:
            raise ContractError("durable orgasm state positive_valence must be within [-1, 1]")

        persistence_window_ms = raw_state.get("persistence_window_ms")
        if isinstance(persistence_window_ms, bool) or not isinstance(persistence_window_ms, int) or persistence_window_ms < 0:
            raise ContractError("durable orgasm state persistence_window_ms must be a nonnegative integer")

        event_elapsed_ms = raw_state.get("event_elapsed_ms")
        if isinstance(event_elapsed_ms, bool) or not isinstance(event_elapsed_ms, (int, float)):
            raise ContractError("durable orgasm state event_elapsed_ms must be numeric")
        event_elapsed = float(event_elapsed_ms)
        max_event = float(self._cfg["maximum_orgasm_event_ms"])
        if not math.isfinite(event_elapsed) or event_elapsed < 0.0 or event_elapsed > max_event + 1e-9:
            raise ContractError("durable orgasm state event_elapsed_ms is outside the bounded climax window")

        if raw_state.get("next_eligible_at") is not None:
            raise ContractError(
                "durable orgasm state next_eligible_at requires a trusted wall-clock continuity binding"
            )

        active = raw_state["active_orgasm_event"]
        if active != (phase == "ORGASM_EVENT"):
            raise ContractError("durable orgasm state phase/active_orgasm_event semantics are inconsistent")

        reentry_allowed = raw_state["reentry_allowed"]
        recovery_phase = phase in {"RESOLUTION", "SATIATED_OR_REFRACTORY"}
        if phase == "ORGASM_EVENT" and reentry_allowed:
            raise ContractError("ORGASM_EVENT recovery semantics require reentry_allowed=false")
        if recovery_phase:
            expected_reentry = self.profile == "REENTRANT_CLIMAX"
            if reentry_allowed != expected_reentry:
                raise ContractError("durable recovery reentry state does not match the active profile")
            if action_tendency != "HOLD":
                raise ContractError("recovery phase semantics require action_tendency=HOLD")
        if phase == "QUIESCENT":
            if (
                not reentry_allowed
                or action_tendency != "NONE"
                or float(raw_state["activation_intensity"]) >= 0.05
                or float(raw_state["coherence"]) >= 0.05
                or float(raw_state["satiation"]) >= 0.05
                or float(raw_state["resolution_intensity"]) != 0.0
                or float(raw_state["refractory_strength"]) != 0.0
            ):
                raise ContractError("QUIESCENT recovery semantics are inconsistent")
        if phase == "ACTIVATING":
            if float(raw_state["activation_intensity"]) <= 0.05 or action_tendency != "APPROACH":
                raise ContractError("ACTIVATING state semantics are inconsistent")
        if phase == "ENTRAINED":
            if (
                float(raw_state["coherence"]) < 0.45
                or action_tendency != "APPROACH"
            ):
                raise ContractError("ENTRAINED state semantics are inconsistent")
        if phase == "CLIMAX_ELIGIBLE":
            raise ContractError("CLIMAX_ELIGIBLE is transient and cannot be a durable restore frontier")
        if phase == "ORGASM_EVENT":
            if action_tendency != "HOLD" or float(raw_state["resolution_intensity"]) != 0.0:
                raise ContractError("ORGASM_EVENT state semantics are inconsistent")

        values = {name: raw_state[name] for name in field_names}
        values["participating_systems"] = canonical_participating_systems
        return values

    @classmethod
    def restore_state(
        cls,
        contract: Mapping[str, Any],
        record: Mapping[str, Any],
        *,
        source_revision: str,
        elapsed_seconds: float = 0.0,
    ) -> "OrgasmRuntime":
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
        runtime._state = _OrgasmState(**values)
        if raw_state["organic_climax_eligible"] != runtime._organic_climax_eligible():
            raise ContractError("durable orgasm state's derived organic eligibility is inconsistent")

        last_receipt = record.get("last_event_receipt")
        if last_receipt is not None and not isinstance(last_receipt, Mapping):
            raise ContractError("durable last_event_receipt must be an object or null")
        if isinstance(last_receipt, Mapping):
            try:
                validate_affective_event_receipt(
                    last_receipt,
                    expected_runtime_instance_id=runtime.runtime_instance_id,
                    expected_source_revision=source_revision,
                    require_engineered_claim=(source_revision == _CANONICAL_SEXUALITY_COMMIT),
                )
            except AffectiveReceiptSemanticError as exc:
                raise ContractError("durable last_event_receipt semantic validation failed: " + str(exc)) from exc
            runtime.last_event_receipt = dict(last_receipt)
        else:
            runtime.last_event_receipt = None

        trigger_governance = record.get("trigger_governance")
        self_qualification_limit = int(runtime._cfg["self_qualification_max_events_per_run"])
        if trigger_governance is None:
            # Legacy durable records did not persist forced-test governance.
            # Fail closed: require a fresh cooldown before ADMIN_FORCED_TEST and
            # do not allow self-qualification quota to reset on restore.
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

        # Monotonic timestamps are process-local. A restored runtime must acquire
        # a new observation-clock anchor before any future interval can count.
        runtime._last_monotonic_observation = None

        try:
            trusted_restore_elapsed = _validated_elapsed_seconds(elapsed_seconds)
        except ValueError as exc:
            raise ContractError(str(exc)) from exc
        if trusted_restore_elapsed:
            runtime.advance_time(trusted_restore_elapsed)
        return runtime
