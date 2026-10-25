"""Process-local, owner-gated exact-cue retrieval adaptation.

This intentionally does not ingest conversations, train weights, admit Vera
memory, save samples to disk, or authorize effects. Consent/privacy/provenance
references are caller assertions, not proof of the asserted reviews. A host
must verify them independently before passing any real local information.

An operator may stage a bounded candidate, score it on identity-disjoint
held-out cases, then explicitly approve it. A failing or stale evaluation
cannot activate a candidate. Approved versions remain available for rollback
until the process ends; durable admission is a separate governed operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json


_MAX_SAMPLES = 64
_MAX_HOLDOUT = 128


class LearningBlocked(ValueError):
    """An adaptation failed a privacy, evaluation, or approval guard."""


def _bounded(value: str, *, name: str, limit: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a bounded non-empty exact string")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError(f"{name} contains an invalid Unicode scalar")
    return value


def _cue(value: str) -> str:
    return _bounded(value, name="cue", limit=512).strip().casefold()


def _hash(payload: object) -> str:
    material = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FeedbackSample:
    sample_id: str
    source_id: str
    cue: str
    answer: str
    consent_ref: str
    privacy_review_ref: str
    provenance_ref: str

    def validate(self) -> None:
        for name in ("sample_id", "source_id", "consent_ref", "privacy_review_ref", "provenance_ref"):
            _bounded(getattr(self, name), name=name, limit=256)
        _cue(self.cue)
        _bounded(self.answer, name="answer", limit=1024)


@dataclass(frozen=True, slots=True)
class HeldoutCase:
    case_id: str
    source_id: str
    cue: str
    expected: str

    def validate(self) -> None:
        _bounded(self.case_id, name="case_id", limit=256)
        _bounded(self.source_id, name="source_id", limit=256)
        _cue(self.cue)
        _bounded(self.expected, name="expected", limit=1024)


@dataclass(frozen=True, slots=True)
class LocalFeedbackEvaluation:
    candidate_revision: str
    baseline_revision: str
    heldout_sha256: str
    heldout_cases: int
    baseline_passes: int
    candidate_passes: int
    regressions: tuple[str, ...]
    qualified: bool
    authorization_effect: str = "NONE"
    memory_admission: str = "NONE"


class LocalFeedbackLearner:
    """In-memory retrieval versions; no automatic updates, persistence, or LLM training."""

    def __init__(self) -> None:
        genesis = _hash({"local_feedback_schema": 1, "samples": []})
        self._versions: dict[str, tuple[FeedbackSample, ...]] = {genesis: ()}
        self._active_revision = genesis
        self._pending: tuple[str, tuple[FeedbackSample, ...]] | None = None
        self._last_evaluation: LocalFeedbackEvaluation | None = None
        self._last_evaluated_cases: tuple[HeldoutCase, ...] | None = None
        # Immutable accepted canaries stay in every later qualification suite,
        # including after a rollback. A caller cannot cherry-pick them away.
        self._approved_canaries: tuple[HeldoutCase, ...] = ()
        self._reviews: list[tuple[str, str, str]] = []

    @property
    def active_revision(self) -> str:
        return self._active_revision

    @property
    def review_receipts(self) -> tuple[tuple[str, str, str], ...]:
        """Non-authoritative process-local operator review references."""
        return tuple(self._reviews)

    @staticmethod
    def _lookup(samples: tuple[FeedbackSample, ...], cue: str) -> str | None:
        normalized = _cue(cue)
        for item in samples:
            if _cue(item.cue) == normalized:
                return item.answer
        return None

    def lookup(self, cue: str) -> str | None:
        """Read only the most recently explicitly approved retrieval version."""
        return self._lookup(self._versions[self._active_revision], cue)

    def stage(self, samples: tuple[FeedbackSample, ...]) -> str:
        # Even a rejected replacement invalidates the previous pending review.
        # Otherwise a caller could continue approving an obsolete candidate.
        self._pending = None
        self._last_evaluation = None
        self._last_evaluated_cases = None
        if type(samples) is not tuple or not samples or len(samples) > _MAX_SAMPLES:
            raise LearningBlocked("stage requires a bounded non-empty tuple")
        submitted_ids: set[str] = set()
        submitted_cues: set[str] = set()
        candidate = {_cue(row.cue): row for row in self._versions[self._active_revision]}
        for row in samples:
            if type(row) is not FeedbackSample:
                raise TypeError("stage requires exact FeedbackSample values")
            row.validate()
            cue = _cue(row.cue)
            if row.sample_id in submitted_ids or cue in submitted_cues:
                raise LearningBlocked("duplicate sample ID or conflicting cue in stage")
            submitted_ids.add(row.sample_id)
            submitted_cues.add(cue)
            candidate[cue] = row
        if len(candidate) > _MAX_SAMPLES:
            raise LearningBlocked("candidate exceeds local sample bound")
        ordered = tuple(row for _, row in sorted(candidate.items()))
        if len({row.sample_id for row in ordered}) != len(ordered):
            raise LearningBlocked("sample ID cannot rebind to another cue")
        digest = _hash({"local_feedback_schema": 1, "samples": [
            {name: getattr(row, name) for name in FeedbackSample.__dataclass_fields__}
            for row in ordered
        ]})
        if digest == self._active_revision:
            raise LearningBlocked("stage does not change the approved retrieval version")
        self._pending = (digest, ordered)
        return digest

    def evaluate(
        self,
        candidate_revision: str,
        holdout: tuple[HeldoutCase, ...],
    ) -> LocalFeedbackEvaluation:
        # A later failed holdout cannot leave a previously passing gate armed.
        self._last_evaluation = None
        self._last_evaluated_cases = None
        if self._pending is None or candidate_revision != self._pending[0]:
            raise LearningBlocked("candidate is not the current staged revision")
        if type(holdout) is not tuple or len(holdout) > _MAX_HOLDOUT or (
            not holdout and not self._approved_canaries
        ):
            raise LearningBlocked("evaluation requires new or previously approved held-out cases")
        all_cases = self._approved_canaries + holdout
        if len(all_cases) > _MAX_HOLDOUT:
            raise LearningBlocked("cumulative held-out canaries exceed evaluation bound")
        candidate_samples = self._pending[1]
        active_samples = self._versions[self._active_revision]
        sample_sources = {row.source_id for row in candidate_samples + active_samples}
        sample_ids = {row.sample_id for row in candidate_samples + active_samples}
        case_ids: set[str] = set()
        case_sources: set[str] = set()
        case_cues: set[str] = set()
        material: list[dict[str, str]] = []
        baseline_passes = candidate_passes = 0
        regressions: list[str] = []
        for index, case in enumerate(all_cases):
            if type(case) is not HeldoutCase:
                raise TypeError("evaluate requires exact HeldoutCase values")
            case.validate()
            if (
                case.case_id in case_ids
                or case.case_id in sample_ids
                or case.source_id in sample_sources
                or case.source_id in case_sources
                or _cue(case.cue) in case_cues
            ):
                raise LearningBlocked("held-out case, source, or content is not independent")
            case_ids.add(case.case_id)
            case_sources.add(case.source_id)
            case_cues.add(_cue(case.cue))
            material.append({"case_id": case.case_id, "source_id": case.source_id,
                             "cue": case.cue, "expected": case.expected})
            before = self._lookup(active_samples, case.cue) == case.expected
            after = self._lookup(candidate_samples, case.cue) == case.expected
            baseline_passes += before
            candidate_passes += after
            # A rollback may make the active baseline fail an old canary.
            # Qualification must recover that already approved behavior,
            # not merely exceed the now-regressed baseline's score.
            if not after and (before or index < len(self._approved_canaries)):
                regressions.append(case.case_id)
        result = LocalFeedbackEvaluation(
            candidate_revision=candidate_revision,
            baseline_revision=self._active_revision,
            heldout_sha256=_hash(material),
            heldout_cases=len(all_cases),
            baseline_passes=baseline_passes,
            candidate_passes=candidate_passes,
            regressions=tuple(regressions),
            # Never pin failed cases as future "approved" canaries. For this
            # tiny exact-match probe, partial holdout success is not enough.
            qualified=(
                not regressions
                and candidate_passes == len(all_cases)
                and candidate_passes > baseline_passes
            ),
        )
        self._last_evaluation = result
        self._last_evaluated_cases = all_cases
        return result

    def approve(self, evidence: LocalFeedbackEvaluation, *, approval_ref: str) -> str:
        _bounded(approval_ref, name="approval_ref", limit=256)
        if any(row[2] == approval_ref for row in self._reviews):
            raise LearningBlocked("operator review reference has already been consumed")
        if (
            type(evidence) is not LocalFeedbackEvaluation
            or self._last_evaluation is None
            or evidence != self._last_evaluation
            or self._last_evaluated_cases is None
            or self._pending is None
            or self._pending[0] != evidence.candidate_revision
            or evidence.baseline_revision != self._active_revision
            or not evidence.qualified
        ):
            raise LearningBlocked("candidate lacks a current qualified held-out review")
        revision, samples = self._pending
        self._versions[revision] = samples
        self._active_revision = revision
        self._approved_canaries = self._last_evaluated_cases
        self._pending = None
        self._last_evaluation = None
        self._last_evaluated_cases = None
        self._reviews.append(("APPROVE", revision, approval_ref))
        return revision

    def rollback(self, revision: str, *, approval_ref: str) -> str:
        _bounded(approval_ref, name="approval_ref", limit=256)
        if any(row[2] == approval_ref for row in self._reviews):
            raise LearningBlocked("operator review reference has already been consumed")
        if type(revision) is not str or revision not in self._versions or revision == self._active_revision:
            raise LearningBlocked("rollback requires another previously approved revision")
        self._active_revision = revision
        self._pending = None
        self._last_evaluation = None
        self._last_evaluated_cases = None
        self._reviews.append(("ROLLBACK", revision, approval_ref))
        return revision
