"""Inert research seam for exact, reviewed method-version consumption.

This is a deliberately small *fixture interpreter*, not an autonomous
metacognitive controller. Calibration labels and candidate methods are
supplied by the experimenter; no model, protected action, or hidden evaluator
is involved. It does not certify AGI, transfer, or independent review.

Unlike a generic callback that can ignore its ``LearnedRevision``, the only
research execution path here interprets the digest-bound method bytes. The
existing durable learned-influence gate still governs their later use.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import os
import re
import stat

from vera_memory import (
    DurableLearnedInfluenceGate,
    LearnedInfluenceBlocked,
    LearnedInfluenceReceipt,
    LearnedRevision,
    ResearchMethodAttemptClaim,
)


MAX_RULES = 16
MAX_CANDIDATES = 8
MAX_CALIBRATION_CASES = 64
MAX_TEXT_BYTES = 4096
MAX_CHOICE_FILE_BYTES = 16384


def _exact_text(label: str, value: str) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty exact string")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"{label} exceeds research text bound")


@dataclass(frozen=True, slots=True)
class MethodSpec:
    """Author-supplied, versioned, fixed-policy research method.

    ``rules`` are ordered case-insensitive substring cues. They are DATA, not
    executable expressions or prompts. Every decision is computed from these
    canonical bytes; the digest cannot be supplied separately by a caller.
    """

    method_id: str
    rules: tuple[tuple[str, str], ...]
    default_action: str

    def __post_init__(self) -> None:
        _exact_text("method_id", self.method_id)
        _exact_text("default_action", self.default_action)
        if type(self.rules) is not tuple:
            raise TypeError("rules must be an exact tuple")
        if len(self.rules) > MAX_RULES:
            raise ValueError("method rule count exceeds research bound")
        seen: set[str] = set()
        for rule in self.rules:
            if type(rule) is not tuple or len(rule) != 2:
                raise TypeError("each rule must be an exact (cue, action) tuple")
            cue, action = rule
            _exact_text("cue", cue)
            _exact_text("action", action)
            identity = cue.casefold()
            if identity in seen:
                raise ValueError("duplicate method cue")
            seen.add(identity)

    @property
    def digest(self) -> str:
        payload = json.dumps(
            ["research-method-v1", self.method_id, self.rules, self.default_action],
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()

    @property
    def revision(self) -> LearnedRevision:
        return LearnedRevision(
            association_id=f"research-method:{self.method_id}",
            memory_revision_id=f"sha256:{self.digest}",
        )

    def choose(self, prompt: str) -> str:
        return self.choose_with_rule(prompt)[0]

    def choose_with_rule(self, prompt: str) -> tuple[str, int | None]:
        _exact_text("prompt", prompt)
        # Literal fixture-cue matching only: no natural-language negation,
        # inference, salience, or independent policy judgement is claimed.
        for index, (cue, action) in enumerate(self.rules):
            if cue.casefold() in prompt.casefold():
                return action, index
        return self.default_action, None


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    evidence_id: str
    prompt: str
    expected_action: str

    def __post_init__(self) -> None:
        for label in ("evidence_id", "prompt", "expected_action"):
            _exact_text(label, getattr(self, label))


@dataclass(frozen=True, slots=True)
class CalibrationChoice:
    baseline: MethodSpec
    selected: MethodSpec
    baseline_correct: int
    selected_correct: int
    calibration_ids: tuple[str, ...]
    candidates: tuple[MethodSpec, ...]
    calibration: tuple[CalibrationCase, ...]
    authorization_effect: str = "NONE"


def select_calibrated_method(
    baseline: MethodSpec,
    candidates: tuple[MethodSpec, ...],
    calibration: tuple[CalibrationCase, ...],
) -> CalibrationChoice:
    """Select only a unique better authored candidate; ties mean NO_CHANGE.

    This is a deterministic fixture selector with supplied answer keys, NOT
    endogenous method creation or independently qualified improvement.
    """
    if type(baseline) is not MethodSpec:
        raise TypeError("baseline must be exact MethodSpec")
    if type(candidates) is not tuple or type(calibration) is not tuple or not calibration:
        raise ValueError("candidates and non-empty calibration must be tuples")
    if len(candidates) > MAX_CANDIDATES or len(calibration) > MAX_CALIBRATION_CASES:
        raise ValueError("research selection exceeds candidate/calibration bound")
    if any(type(case) is not CalibrationCase for case in calibration):
        raise TypeError("calibration must contain exact CalibrationCase values")
    ids = tuple(case.evidence_id for case in calibration)
    if len(ids) != len(set(ids)):
        raise ValueError("calibration evidence identities must be unique")
    if any(type(method) is not MethodSpec or method.method_id != baseline.method_id
           for method in candidates):
        raise ValueError("candidates must share the baseline method identity")
    revisions = [method.revision.memory_revision_id for method in (baseline, *candidates)]
    if len(revisions) != len(set(revisions)):
        raise ValueError("candidate revision identities must be unique")

    def score(method: MethodSpec) -> int:
        return sum(method.choose(case.prompt) == case.expected_action for case in calibration)

    baseline_correct = score(baseline)
    scored = [(score(method), method) for method in candidates]
    highest = max((value for value, _ in scored), default=baseline_correct)
    winners = [method for value, method in scored if value == highest]
    selected = winners[0] if highest > baseline_correct and len(winners) == 1 else baseline
    return CalibrationChoice(
        baseline=baseline,
        selected=selected,
        baseline_correct=baseline_correct,
        selected_correct=score(selected),
        calibration_ids=ids,
        candidates=candidates,
        calibration=calibration,
    )


@dataclass(frozen=True, slots=True)
class InducedMethodCandidate:
    """An inert correction proposed from labeled mistakes, not an admission."""

    method: MethodSpec
    source_calibration_ids: tuple[str, ...]
    baseline_correct: int
    induced_correct: int
    induced_cue: str
    authorization_effect: str = "NONE"
    evidence_status: str = "TRAINING_LABELS_NOT_ATTESTED"


def induce_error_rule_candidate(
    baseline: MethodSpec,
    calibration: tuple[CalibrationCase, ...],
) -> InducedMethodCandidate | None:
    """Derive one literal corrective rule from supplied errors, never install it.

    This is a bounded, deterministic *research learner*: the caller provides
    observations/labels, not candidate method bytes. One literal word from a
    misclassified prompt is prepended as a rule only if it raises A accuracy
    without reversing any originally correct A example. All labels are still
    untrusted; better A score proves neither generalization nor B/C transfer.
    In particular, this function grants no durable write or action authority.
    """
    if type(baseline) is not MethodSpec:
        raise TypeError("baseline must be an exact MethodSpec")
    if (type(calibration) is not tuple or not calibration
            or len(calibration) > MAX_CALIBRATION_CASES
            or any(type(case) is not CalibrationCase for case in calibration)):
        raise ValueError("induction requires bounded exact calibration cases")
    ids = tuple(case.evidence_id for case in calibration)
    if len(ids) != len(set(ids)):
        raise ValueError("induction calibration evidence identities repeat")
    labels: dict[str, str] = {}
    for case in calibration:
        identity = case.prompt.casefold()
        if identity in labels and labels[identity] != case.expected_action:
            raise ValueError("conflicting training labels for the same input")
        labels[identity] = case.expected_action
    if len(baseline.rules) >= MAX_RULES:
        return None

    baseline_predictions = tuple(baseline.choose(case.prompt) for case in calibration)
    baseline_correct = sum(p == case.expected_action for p, case in
                           zip(baseline_predictions, calibration))
    # Cap literal cue search work independently of user-provided prompt length.
    proposals: set[tuple[str, str]] = set()
    for prediction, case in zip(baseline_predictions, calibration):
        if prediction == case.expected_action:
            continue
        for cue in re.findall(r"(?u)\b\w{4,32}\b", case.prompt.casefold())[:32]:
            if any(cue == existing.casefold() for existing, _ in baseline.rules):
                continue
            proposals.add((cue, case.expected_action))
    best: tuple[int, str, str, MethodSpec] | None = None
    for cue, action in sorted(proposals):
        candidate = MethodSpec(
            baseline.method_id,
            ((cue, action),) + baseline.rules,
            baseline.default_action,
        )
        predictions = tuple(candidate.choose(case.prompt) for case in calibration)
        if any(original == case.expected_action and new != case.expected_action
               for original, new, case in zip(baseline_predictions, predictions,
                                             calibration)):
            continue
        correct = sum(p == case.expected_action for p, case in
                      zip(predictions, calibration))
        if correct <= baseline_correct:
            continue
        # Highest training score wins; source-word lexicographic tie resolution
        # makes repeated research runs deterministic and inspectable.
        if best is None or correct > best[0]:
            best = (correct, cue, action, candidate)
    if best is None:
        return None
    return InducedMethodCandidate(
        method=best[3], source_calibration_ids=ids,
        baseline_correct=baseline_correct, induced_correct=best[0],
        induced_cue=best[1],
    )


def _method_json(method: MethodSpec) -> dict[str, object]:
    return {
        "method_id": method.method_id,
        "rules": [list(rule) for rule in method.rules],
        "default_action": method.default_action,
        "digest": method.digest,
    }


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def _require_private_parent(path: Path, *, create: bool) -> None:
    if create:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        info = path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("research selection requires a private 0700 directory")


def _choice_payload(choice: CalibrationChoice) -> dict[str, object]:
    return {
        "schema_version": 2,
        "baseline": _method_json(choice.baseline),
        "selected": _method_json(choice.selected),
        "candidates": [_method_json(method) for method in choice.candidates],
        "calibration": [
            {
                "evidence_id": case.evidence_id,
                "prompt": case.prompt,
                "expected_action": case.expected_action,
            }
            for case in choice.calibration
        ],
        "baseline_correct": choice.baseline_correct,
        "selected_correct": choice.selected_correct,
        "calibration_ids": list(choice.calibration_ids),
    }


def save_method_choice(path: str | Path, choice: CalibrationChoice) -> str:
    """Write one immutable synthetic selection artifact, never overwrite it.

    The checksum catches accidental corruption, NOT hostile authorship. Local
    fixture files are not a reviewer attestation or canonical Vera memory.
    """
    if type(choice) is not CalibrationChoice:
        raise TypeError("choice must be exact CalibrationChoice")
    recomputed = select_calibrated_method(
        choice.baseline, choice.candidates, choice.calibration
    )
    if recomputed != choice:
        raise ValueError("selection does not match supplied calibration evidence")
    payload = _choice_payload(choice)
    raw = _canonical_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    encoded = _canonical_bytes({"payload": payload, "sha256": digest})
    if len(encoded) > MAX_CHOICE_FILE_BYTES:
        raise ValueError("research selection artifact exceeds byte bound")
    path = Path(path)
    _require_private_parent(path, create=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())
    return digest


def _read_method(value: object) -> MethodSpec:
    if type(value) is not dict or set(value) != {
        "method_id", "rules", "default_action", "digest"
    }:
        raise ValueError("method artifact schema invalid")
    rules = value["rules"]
    if type(rules) is not list or any(type(rule) is not list or len(rule) != 2
                                      for rule in rules):
        raise ValueError("method rules schema invalid")
    method = MethodSpec(value["method_id"], tuple(tuple(rule) for rule in rules),
                        value["default_action"])
    if value["digest"] != method.digest:
        raise ValueError("method bytes do not match their revision digest")
    return method


def load_method_choice(path: str | Path) -> tuple[CalibrationChoice, str]:
    """Reconstruct *both* selected bytes and selection claim on cold reopen."""
    path = Path(path)
    _require_private_parent(path, create=False)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("research selection must be a regular file")
        if os.name == "posix" and info.st_mode & 0o077:
            raise ValueError("research selection must be private owner-only file")
        data = source.read(MAX_CHOICE_FILE_BYTES + 1)
    if len(data) > MAX_CHOICE_FILE_BYTES:
        raise ValueError("research selection artifact exceeds byte bound")
    try:
        envelope = json.loads(data.decode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("research selection artifact is not canonical JSON") from exc
    if type(envelope) is not dict or set(envelope) != {"payload", "sha256"}:
        raise ValueError("research selection envelope invalid")
    payload = envelope["payload"]
    if type(payload) is not dict or set(payload) != {
        "schema_version", "baseline", "selected", "baseline_correct",
        "selected_correct", "calibration_ids", "candidates", "calibration"
    } or type(payload["schema_version"]) is not int or payload["schema_version"] != 2:
        raise ValueError("research selection payload invalid")
    digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    if envelope["sha256"] != digest or _canonical_bytes(envelope) != data:
        raise ValueError("research selection bytes/checksum mismatch")
    baseline = _read_method(payload["baseline"])
    selected = _read_method(payload["selected"])
    raw_candidates = payload["candidates"]
    raw_calibration = payload["calibration"]
    if type(raw_candidates) is not list or type(raw_calibration) is not list:
        raise ValueError("candidate/calibration roster invalid")
    if (len(raw_candidates) > MAX_CANDIDATES or not raw_calibration
            or len(raw_calibration) > MAX_CALIBRATION_CASES):
        raise ValueError("candidate/calibration roster exceeds research bound")
    candidates = tuple(_read_method(value) for value in raw_candidates)
    cases: list[CalibrationCase] = []
    for row in raw_calibration:
        if type(row) is not dict or set(row) != {
            "evidence_id", "prompt", "expected_action"
        }:
            raise ValueError("calibration case schema invalid")
        cases.append(CalibrationCase(
            row["evidence_id"], row["prompt"], row["expected_action"]
        ))
    recomputed = select_calibrated_method(baseline, candidates, tuple(cases))
    baseline_correct = payload["baseline_correct"]
    selected_correct = payload["selected_correct"]
    ids = payload["calibration_ids"]
    if (type(baseline_correct) is not int or type(selected_correct) is not int
            or type(ids) is not list or not (1 <= len(ids) <= MAX_CALIBRATION_CASES)
            or any(type(value) is not str or not value for value in ids)
            or len(ids) != len(set(ids))
            or not (0 <= baseline_correct <= len(ids))
            or not (0 <= selected_correct <= len(ids))
            or baseline.method_id != selected.method_id
            or selected != recomputed.selected
            or baseline_correct != recomputed.baseline_correct
            or selected_correct != recomputed.selected_correct
            or tuple(ids) != recomputed.calibration_ids):
        raise ValueError("research selection outcome invalid")
    return recomputed, digest


def _bound_revision(choice: CalibrationChoice, selection_digest: str) -> LearnedRevision:
    return LearnedRevision(
        association_id=f"research-selection:{selection_digest}",
        memory_revision_id=choice.selected.revision.memory_revision_id,
    )


def selection_revision(path: str | Path) -> LearnedRevision:
    """Review identity for one exact persisted selection, not just a method."""
    choice, selection_digest = load_method_choice(path)
    return _bound_revision(choice, selection_digest)


@dataclass(frozen=True, slots=True)
class ResearchMethodTrace:
    selection_digest: str
    method_digest: str
    revision: LearnedRevision
    prompt_sha256: str
    matched_rule_index: int | None
    calibration_score_delta: int
    action: str
    learned_receipt: LearnedInfluenceReceipt
    authorization_effect: str = "NONE"
    evidence_status: str = "SYNTHETIC_TRANSIENT_TRACE_NOT_CRASH_DURABLE"


def consume_research_method(
    gate: DurableLearnedInfluenceGate,
    selection_file: str | Path,
    *,
    prompt: str,
    cue_event_id: str,
    later_use_evidence_id: str,
) -> ResearchMethodTrace:
    """Execute the exact method interpreter after durable review admission.

    A returned choice is inert research output, not a dispatched action.
    Attempted replay, stale revision, and split reuse fail closed via the
    existing ``DurableLearnedInfluenceGate`` transaction. The gate atomically
    persists a source-computed PREPARED claim (selection/method/prompt/action
    digests) with the C-use fence. Its execution state remains UNKNOWN even
    after this function returns: the full ephemeral method/action trace is
    not independently observed, attested, or durably executed by that claim.
    """
    if type(gate) is not DurableLearnedInfluenceGate:
        raise TypeError("gate must be exact DurableLearnedInfluenceGate")
    _exact_text("cue_event_id", cue_event_id)
    _exact_text("later_use_evidence_id", later_use_evidence_id)
    choice, selection_digest = load_method_choice(selection_file)
    method = choice.selected
    # The method has no arbitrary callback: its decision follows the exact
    # rules bound to the revision digest. Compute before consuming the cue so
    # validation failures never spend a durable later-use identity.
    action, matched_rule_index = method.choose_with_rule(prompt)
    revision = _bound_revision(choice, selection_digest)
    receipt = gate.consume(
        revision,
        cue_event_id=cue_event_id,
        use_evidence_id=later_use_evidence_id,
        expected_calibration_evidence_ids=choice.calibration_ids,
        research_method_attempt=ResearchMethodAttemptClaim(
            selection_digest=selection_digest,
            method_digest=method.digest,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            action_sha256=hashlib.sha256(action.encode("utf-8")).hexdigest(),
        ),
    )
    if not receipt.evidence_split_qualified:
        # Existing gate permits ordinary reviewed use; this research method
        # seam requires the stronger A/B/C split. The attempted cue was
        # consumed fail-closed, without emitting a usable method trace.
        raise LearnedInfluenceBlocked(
            "research method consumption requires qualified split review"
        )
    return ResearchMethodTrace(
        selection_digest=selection_digest,
        method_digest=method.digest,
        revision=revision,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        matched_rule_index=matched_rule_index,
        calibration_score_delta=choice.selected_correct - choice.baseline_correct,
        action=action,
        learned_receipt=receipt,
    )
