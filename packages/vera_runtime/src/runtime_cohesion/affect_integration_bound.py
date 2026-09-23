from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from threading import RLock
from typing import Any, Mapping
from weakref import WeakKeyDictionary

from .affect_host import VeraAffectiveRuntimeHost, validate_runtime_implementation_cut
from .affect_integration import AffectiveModulationApplication, AffectiveModulationArbiter
from .affect_signal import build_affective_modulation_signal


_INTEGRATION_CUT_SCHEMA = "VERA_COHESION_AFFECTIVE_INTEGRATION_CUT_V1"
_REQUIRED_INTEGRATION_PATHS = frozenset({
    "runtime_cohesion/__init__.py",
    "runtime_cohesion/adapters.py",
    "runtime_cohesion/affect_integration.py",
    "runtime_cohesion/affect_integration_bound.py",
    "runtime_cohesion/affect_signal.py",
    "runtime_cohesion/audit.py",
    "runtime_cohesion/executor.py",
    "runtime_cohesion/item_typing.py",
    "runtime_cohesion/origin.py",
    "runtime_cohesion/provider_admission.py",
    "runtime_cohesion/reconcile.py",
    "runtime_cohesion/runtime.py",
})


def _require_git_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise ValueError(f"{label} must be an exact 40-character Git SHA")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be hexadecimal") from exc
    return value


def _git_blob_sha(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def validate_cohesion_affective_integration_cut(
    cut: Mapping[str, Any],
    *,
    repository_root: Path | str | None = None,
) -> dict[str, Any]:
    """Cross-bind the CV-owned affective application cut to Git and live bytes."""
    if not isinstance(cut, Mapping):
        raise ValueError("Cohesion affective integration cut must be a structured mapping")
    if cut.get("schema") != _INTEGRATION_CUT_SCHEMA:
        raise ValueError("unsupported Cohesion affective integration cut schema")
    if cut.get("repository") != "thebrazenbeard/vera":
        raise ValueError("Cohesion affective integration cut repository mismatch")
    commit = _require_git_sha(cut.get("commit"), label="Cohesion affective integration commit")
    modules = cut.get("modules")
    if not isinstance(modules, Mapping) or set(modules) != _REQUIRED_INTEGRATION_PATHS:
        raise ValueError("Cohesion affective integration cut module set mismatch")

    root = Path(repository_root) if repository_root is not None else Path(__file__).resolve().parents[1]
    root = root.resolve()
    normalized: dict[str, str] = {}
    for path in sorted(_REQUIRED_INTEGRATION_PATHS):
        blob = _require_git_sha(modules[path], label=f"Cohesion integration blob for {path}")
        file_path = (root / path).resolve()
        try:
            file_path.relative_to(root)
        except ValueError as exc:
            raise ValueError("Cohesion integration path escapes repository root") from exc
        if not file_path.is_file():
            raise ValueError(f"Cohesion integration file is missing: {path}")
        if _git_blob_sha(file_path.read_bytes()) != blob:
            raise ValueError(f"executing Cohesion integration bytes do not match cut: {path}")
        try:
            resolved = subprocess.run(
                ["git", "rev-parse", f"{commit}:{path}"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError(f"Cohesion integration commit/path cannot be resolved: {path}") from exc
        if resolved != blob:
            raise ValueError(f"Cohesion integration commit resolves a different blob: {path}")
        normalized[path] = blob

    return {
        "schema": _INTEGRATION_CUT_SCHEMA,
        "repository": "thebrazenbeard/vera",
        "commit": commit,
        "modules": normalized,
    }


def _cut_digest(cut: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(cut), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IntegratedAffectivePlanningResult:
    application: AffectiveModulationApplication
    affective_runtime_cut_commit: str
    cohesion_integration_cut_commit: str
    cohesion_integration_cut_sha256: str
    qualification: str
    phenomenology: str


@dataclass
class _SharedAffectiveApplicationFrontier:
    """One process-local replay/high-water frontier for one exact host generation."""

    arbiter: AffectiveModulationArbiter
    lock: RLock


_FRONTIER_REGISTRY_LOCK = RLock()
_HOST_APPLICATION_FRONTIERS: WeakKeyDictionary[
    VeraAffectiveRuntimeHost,
    _SharedAffectiveApplicationFrontier,
] = WeakKeyDictionary()


def _frontier_for_host(
    host: VeraAffectiveRuntimeHost,
    runtime_cut: Mapping[str, Any],
) -> _SharedAffectiveApplicationFrontier:
    """Return the unique process-local application frontier for this exact host.

    Wrapper reconstruction over the same host must not reset replay history or
    the logical-time high-water. A genuinely distinct host object represents a
    distinct application generation unless a later durable restore protocol
    explicitly binds a successor frontier.
    """

    with _FRONTIER_REGISTRY_LOCK:
        frontier = _HOST_APPLICATION_FRONTIERS.get(host)
        if frontier is None:
            frontier = _SharedAffectiveApplicationFrontier(
                arbiter=AffectiveModulationArbiter(
                    runtime_instance_id=host.runtime.runtime_instance_id,
                    runtime_implementation_cut=runtime_cut,
                ),
                lock=RLock(),
            )
            _HOST_APPLICATION_FRONTIERS[host] = frontier
        return frontier


class CohesionAffectiveIntegrationPort:
    """Supported Vera boundary from one bound OV host to generic planning.

    Construction accepts only the exact ``VeraAffectiveRuntimeHost`` class. Both
    the affective core cut and the CV-owned integration cut are derived from that
    host's sealed binding and required to satisfy one exact-generation cross-bind.

    The supported planning path does not accept caller-supplied affective data.
    One coherent immutable/plain-data observation is captured from the bound host
    internally for each application, converted to a diagnostic/ancestry signal,
    and passed directly to the stateful Cohesion arbiter. The signal is evidence
    about that application, not caller authority over it.

    Replay history and logical-time high-water are owned by one process-local
    frontier keyed to the exact host object, not by whichever public wrapper was
    constructed most recently. This remains a supported API/process boundary,
    not hostile-process isolation, durable restart continuity, or provider
    qualification.
    """

    def __init__(self, *, host: VeraAffectiveRuntimeHost) -> None:
        if type(host) is not VeraAffectiveRuntimeHost:
            raise TypeError("Cohesion affective integration requires the exact VeraAffectiveRuntimeHost class")
        host_binding = host.binding
        if not isinstance(host_binding, Mapping):
            raise ValueError("exact-bound affective host lacks structured source binding")

        self._host = host
        self._affective_runtime_cut = validate_runtime_implementation_cut(
            host.runtime_implementation_cut
        )
        integration_candidate = host_binding.get("cohesion_integration_cut")
        if not isinstance(integration_candidate, Mapping):
            raise ValueError("exact-bound affective host binding lacks Cohesion integration cut")
        self._cohesion_integration_cut = validate_cohesion_affective_integration_cut(
            integration_candidate
        )

        cross = host_binding.get("cross_binding")
        if not isinstance(cross, Mapping):
            raise ValueError("exact-bound affective host binding lacks cross-binding metadata")
        generation = _require_git_sha(cross.get("generation_commit"), label="cross-binding generation")
        if generation != self._affective_runtime_cut["commit"] or generation != self._cohesion_integration_cut["commit"]:
            raise ValueError("affective core and Cohesion integration cuts are not one exact generation")
        if cross.get("affective_core_and_cohesion_integration_same_generation") is not True:
            raise ValueError("cross-binding does not require one affective/Cohesion generation")
        if cross.get("supported_execution_requires_both_exact_cuts") is not True:
            raise ValueError("cross-binding does not require both exact cuts")
        if cross.get("generic_planning_mutation_owner") != "COHESION_INTEGRATION_ARBITRATION_PORT":
            raise ValueError("cross-binding generic planning owner mismatch")
        if cross.get("orgasm_subsystem_generic_planning_mutation_authority") is not False:
            raise ValueError("cross-binding illegally grants Orgasm generic planning mutation authority")

        self._frontier = _frontier_for_host(host, self._affective_runtime_cut)

    @property
    def runtime_instance_id(self) -> str:
        with self._frontier.lock:
            return self._frontier.arbiter.runtime_instance_id

    @property
    def minimum_logical_time_seconds(self) -> float:
        with self._frontier.lock:
            return self._frontier.arbiter.minimum_logical_time_seconds

    def apply(
        self,
        planning_state: Mapping[str, Any],
    ) -> IntegratedAffectivePlanningResult:
        # Serialize signal acquisition + replay validation + frontier advancement
        # for every wrapper over the same exact host generation.
        with self._frontier.lock:
            signal = build_affective_modulation_signal(self._host)
            application = self._frontier.arbiter.apply(planning_state, signal)
        return IntegratedAffectivePlanningResult(
            application=application,
            affective_runtime_cut_commit=self._affective_runtime_cut["commit"],
            cohesion_integration_cut_commit=self._cohesion_integration_cut["commit"],
            cohesion_integration_cut_sha256=_cut_digest(self._cohesion_integration_cut),
            qualification="SOURCE_INTEGRATED_NOT_BEHAVIORALLY_QUALIFIED",
            phenomenology="UNRESOLVED",
        )


__all__ = [
    "CohesionAffectiveIntegrationPort",
    "IntegratedAffectivePlanningResult",
    "validate_cohesion_affective_integration_cut",
]
