"""Opt-in, effectless *contract* for five external cognition donors.

The host owns source custody and callback execution. The contract cannot prove
callback purity, source-owner identity, native installation or model behavior.
Nothing runs unless the host explicitly passes ``enabled=True``.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
from typing import Callable


DONORS = ("noema", "meso-crct", "volition", "empathy", "pre-active")
OWNER = "thebrazenbeard"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_BLOB = re.compile(r"[0-9a-f]{64}\Z")
_PATH = re.compile(r"[A-Za-z0-9_./-]{1,180}\Z")


class DonorBoundaryError(ValueError):
    """Reject unsupported or unproven claims before model prompt construction."""


@dataclass(frozen=True, slots=True)
class SourceRef:
    donor: str
    repository: str
    commit_sha: str
    source_path: str
    blob_sha256: str

    def validate(self) -> None:
        if self.donor not in DONORS or type(self.donor) is not str:
            raise DonorBoundaryError("unknown donor")
        if self.repository != f"{OWNER}/{self.donor}" or type(self.repository) is not str:
            raise DonorBoundaryError("source repository owner is not exact")
        if type(self.commit_sha) is not str or _SHA.fullmatch(self.commit_sha) is None:
            raise DonorBoundaryError("source commit is not an immutable SHA-1")
        if (type(self.source_path) is not str
                or _PATH.fullmatch(self.source_path) is None
                or self.source_path.startswith("/")
                or any(part in {".", ".."} for part in self.source_path.split("/"))):
            raise DonorBoundaryError("source path must be a normalized repo-local path")
        if type(self.blob_sha256) is not str or _BLOB.fullmatch(self.blob_sha256) is None:
            raise DonorBoundaryError("source content digest must be exact")


@dataclass(frozen=True, slots=True)
class SourceReadback:
    """Host callback's reported readback, not independent proof of ownership."""
    repository: str
    commit_sha: str
    source_path: str
    blob_sha256: str


@dataclass(frozen=True, slots=True)
class DonorBinding:
    source: SourceRef
    evaluate: Callable[[str], object]


@dataclass(frozen=True, slots=True)
class CognitiveAdvisory:
    status: str
    input_sha256: str | None
    bindings: tuple[SourceRef, ...]
    signals: tuple[tuple[str, str | bool | float], ...]
    authority: str = "NONE"
    memory_admission: str = "NONE"
    source_proof: str = "HOST_CALLBACK_REPORTED_ONLY"
    model_identity: str = "UNQUALIFIED"

    def untrusted_prompt_data(self) -> str:
        if self.status != "CANDIDATE_ONLY":
            return ""
        return json.dumps({"classification": "UNVERIFIED_COGNITIVE_ADVISORY_DATA",
                           "input_sha256": self.input_sha256,
                           "signals": dict(self.signals)}, sort_keys=True,
                          ensure_ascii=True, allow_nan=False)


def _validated_signal(donor: str, value: object) -> tuple[str, str | bool | float]:
    if donor == "noema":
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
            raise DonorBoundaryError("noema requires a finite 0..1 discrepancy")
        return "noema_discrepancy", float(value)
    if donor == "meso-crct":
        if type(value) is not str or value not in {"INSPECT", "HOLD"}:
            raise DonorBoundaryError("MESO intent outside bounded vocabulary")
        return "meso_intent", value
    if donor == "volition":
        if type(value) is not bool:
            raise DonorBoundaryError("volition eligibility must be literal boolean")
        return "volition_candidate_eligible", value
    if donor == "empathy":
        if type(value) is not str or value not in {"ALLOW", "HOLD", "STOP_PLAY"}:
            raise DonorBoundaryError("empathy response policy outside bounded vocabulary")
        return "empathy_response_policy", value
    if donor == "pre-active":
        if type(value) is not str or value not in {
            "INSPECT_OPTION", "NO_MOTIVE_PROPOSAL", "STOP_PLAY"
        }:
            raise DonorBoundaryError("PreActive focus outside bounded vocabulary")
        return "preactive_focus", value
    raise DonorBoundaryError("unrecognized donor")


def collect_five_donor_advisory(
    task: str, *, enabled: bool = False,
    bindings: tuple[DonorBinding, ...] = (),
    readback: Callable[[SourceRef], SourceReadback] | None = None,
) -> CognitiveAdvisory:
    """No ambient repo imports, memory reads, model access, network, or writes.

    On opt-in, verify *all* host-reported source readbacks before evaluating
    the injected donor callbacks. The returned data is advisory, never authority.
    """
    if type(enabled) is not bool:
        raise DonorBoundaryError("enabled must be a literal boolean")
    if not enabled:
        return CognitiveAdvisory("DISABLED", None, (), ())
    if type(task) is not str or not task.strip() or len(task) > 2_000:
        raise DonorBoundaryError("bounded explicit task text required")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in task):
        raise DonorBoundaryError("task text contains a control character")
    if type(bindings) is not tuple or len(bindings) != len(DONORS):
        raise DonorBoundaryError("exactly five ordered donor bindings required")
    if not callable(readback):
        raise DonorBoundaryError("host-owned readback callback required")
    for index, binding in enumerate(bindings):
        if type(binding) is not DonorBinding or type(binding.source) is not SourceRef:
            raise DonorBoundaryError("typed source binding required")
        binding.source.validate()
        if binding.source.donor != DONORS[index] or not callable(binding.evaluate):
            raise DonorBoundaryError("donor order/callback mismatch")
    for binding in bindings:
        observed = readback(binding.source)
        if (type(observed) is not SourceReadback
                or (observed.repository, observed.commit_sha, observed.source_path,
                    observed.blob_sha256) != (
                    binding.source.repository, binding.source.commit_sha,
                    binding.source.source_path, binding.source.blob_sha256)):
            raise DonorBoundaryError("host source readback mismatch")
    signals = tuple(_validated_signal(binding.source.donor, binding.evaluate(task))
                    for binding in bindings)
    values = dict(signals)
    if values["empathy_response_policy"] == "STOP_PLAY" and (
        values["preactive_focus"] != "STOP_PLAY"
        or values["volition_candidate_eligible"] is not False
    ):
        raise DonorBoundaryError("same-referent stop must veto motive candidate")
    return CognitiveAdvisory(
        status="CANDIDATE_ONLY", input_sha256=sha256(task.encode("utf-8")).hexdigest(),
        bindings=tuple(binding.source for binding in bindings), signals=signals,
    )
