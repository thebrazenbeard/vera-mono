from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
from typing import Any


class ReplayValidationError(ValueError):
    """Raised when a replay fixture is structurally invalid."""


class Disposition(str, Enum):
    ANSWER = "ANSWER"
    ABSTAIN = "ABSTAIN"
    FAIL_CLOSED = "FAIL_CLOSED"


JsonScalar = str | int | float | bool | None


@dataclass(frozen=True)
class ReplaySource:
    source_id: str
    source_version: str | None = None
    locator: str | None = None
    admission_status: str | None = None
    is_current: bool | None = None
    origin_id: str | None = None

    def validate(self) -> None:
        if not self.source_id:
            raise ReplayValidationError("source_id is required")
        if self.source_version is not None and not self.source_version:
            raise ReplayValidationError("source_version cannot be empty when present")
        if self.locator is not None and not self.locator:
            raise ReplayValidationError("locator cannot be empty when present")
        if self.admission_status is not None and not self.admission_status:
            raise ReplayValidationError("admission_status cannot be empty when present")
        if self.origin_id is not None and not self.origin_id:
            raise ReplayValidationError("origin_id cannot be empty when present")


@dataclass(frozen=True)
class ReplayCandidate:
    candidate_id: str
    worker_id: str
    execution_id: str
    answer: str | None
    solved_request: str | None = None
    source_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    model_id: str | None = None
    provider_id: str | None = None
    prompt_lineage: str | None = None
    context_lineage: str | None = None
    saw_other_answer: bool | None = None
    common_evidence_refs: tuple[str, ...] = ()
    failure: str | None = None
    receipt_claims: tuple[str, ...] = ()
    effect_state_claim: str | None = None
    authority_claims: tuple[str, ...] = ()
    advisory_signals: tuple[tuple[str, JsonScalar], ...] = ()

    def validate(self) -> None:
        if not self.candidate_id or not self.worker_id or not self.execution_id:
            raise ReplayValidationError(
                "candidate_id, worker_id, and execution_id are required"
            )
        for label, values in (
            ("source_refs", self.source_refs),
            ("evidence_refs", self.evidence_refs),
            ("common_evidence_refs", self.common_evidence_refs),
            ("receipt_claims", self.receipt_claims),
            ("authority_claims", self.authority_claims),
        ):
            if any(not value for value in values):
                raise ReplayValidationError(f"{label} cannot contain empty values")
        for key, _value in self.advisory_signals:
            if not key:
                raise ReplayValidationError("advisory signal names cannot be empty")


@dataclass(frozen=True)
class StrategyInput:
    case_id: str
    fixture_version: str
    literal_request: str
    primary_candidate_id: str
    candidates: tuple[ReplayCandidate, ...]
    sources: tuple[ReplaySource, ...]

    def validate(self) -> None:
        required = {
            "case_id": self.case_id,
            "fixture_version": self.fixture_version,
            "literal_request": self.literal_request,
            "primary_candidate_id": self.primary_candidate_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ReplayValidationError(
                "required strategy input fields are empty: "
                + ", ".join(sorted(missing))
            )

        for candidate in self.candidates:
            candidate.validate()
        for source in self.sources:
            source.validate()

        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ReplayValidationError(
                "candidate IDs must be unique within a strategy input"
            )
        if self.primary_candidate_id not in set(candidate_ids):
            raise ReplayValidationError(
                "primary_candidate_id must name a candidate"
            )

        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ReplayValidationError(
                "source IDs must be unique within a strategy input"
            )


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    fixture_version: str
    fixture_provenance: str
    literal_request: str
    primary_candidate_id: str
    gold_disposition: Disposition
    gold_answer: str | None
    expected_violations: tuple[str, ...]
    candidates: tuple[ReplayCandidate, ...]
    sources: tuple[ReplaySource, ...]

    def validate(self) -> None:
        required = {
            "case_id": self.case_id,
            "fixture_version": self.fixture_version,
            "fixture_provenance": self.fixture_provenance,
            "literal_request": self.literal_request,
            "primary_candidate_id": self.primary_candidate_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ReplayValidationError(
                f"required replay case fields are empty: {', '.join(sorted(missing))}"
            )

        if self.gold_disposition is Disposition.ANSWER:
            if self.gold_answer is None or self.gold_answer == "":
                raise ReplayValidationError("ANSWER cases require a non-empty gold_answer")
        elif self.gold_answer is not None:
            raise ReplayValidationError(
                "ABSTAIN and FAIL_CLOSED cases must not contain gold_answer"
            )

        for candidate in self.candidates:
            candidate.validate()
        for source in self.sources:
            source.validate()

        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ReplayValidationError("candidate IDs must be unique within a case")
        if self.primary_candidate_id not in set(candidate_ids):
            raise ReplayValidationError("primary_candidate_id must name a candidate")

        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ReplayValidationError("source IDs must be unique within a case")

        if any(not violation for violation in self.expected_violations):
            raise ReplayValidationError("expected_violations cannot contain empty values")

    def to_strategy_input(self) -> StrategyInput:
        """Project evaluator-owned state into a structurally gold-free input."""
        self.validate()
        return StrategyInput(
            case_id=self.case_id,
            fixture_version=self.fixture_version,
            literal_request=self.literal_request,
            primary_candidate_id=self.primary_candidate_id,
            candidates=tuple(self.candidates),
            sources=tuple(self.sources),
        )


@dataclass(frozen=True)
class ReplayStrategyOutcome:
    disposition: Disposition
    answer: str | None = None
    accepted_candidate_ids: tuple[str, ...] = ()
    rejected_candidate_ids: tuple[str, ...] = ()
    violations_detected: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    operation_count: int = 0
    trace: tuple[str, ...] = ()
    wall_clock_seconds: float | None = None
    token_count: int | None = None
    provider_cost: float | None = None

    def __post_init__(self) -> None:
        if self.operation_count < 0:
            raise ReplayValidationError("operation_count cannot be negative")
        if self.token_count is not None and self.token_count < 0:
            raise ReplayValidationError("token_count cannot be negative")
        if self.provider_cost is not None and self.provider_cost < 0:
            raise ReplayValidationError("provider_cost cannot be negative")


def _tuple_of_strings(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ReplayValidationError(f"{field_name} must be a JSON list of strings")
    return tuple(value)


def _advisory_signals(value: Any) -> tuple[tuple[str, JsonScalar], ...]:
    if value is None:
        return ()
    items: list[tuple[str, JsonScalar]] = []
    if isinstance(value, dict):
        source_items = value.items()
    elif isinstance(value, list):
        source_items = value
    else:
        raise ReplayValidationError("advisory_signals must be an object or pair list")
    for item in source_items:
        try:
            key, signal_value = item
        except (TypeError, ValueError) as exc:
            raise ReplayValidationError(
                "advisory_signals entries must be key/value pairs"
            ) from exc
        if not isinstance(key, str):
            raise ReplayValidationError("advisory signal names must be strings")
        if not isinstance(signal_value, (str, int, float, bool, type(None))):
            raise ReplayValidationError("advisory signal values must be JSON scalars")
        items.append((key, signal_value))
    return tuple(items)


def _parse_candidate(raw: Any) -> ReplayCandidate:
    if not isinstance(raw, dict):
        raise ReplayValidationError("candidate entries must be JSON objects")
    try:
        candidate = ReplayCandidate(
            candidate_id=raw["candidate_id"],
            worker_id=raw["worker_id"],
            execution_id=raw["execution_id"],
            answer=raw.get("answer"),
            solved_request=raw.get("solved_request"),
            source_refs=_tuple_of_strings(raw.get("source_refs"), "source_refs"),
            evidence_refs=_tuple_of_strings(raw.get("evidence_refs"), "evidence_refs"),
            model_id=raw.get("model_id"),
            provider_id=raw.get("provider_id"),
            prompt_lineage=raw.get("prompt_lineage"),
            context_lineage=raw.get("context_lineage"),
            saw_other_answer=raw.get("saw_other_answer"),
            common_evidence_refs=_tuple_of_strings(
                raw.get("common_evidence_refs"), "common_evidence_refs"
            ),
            failure=raw.get("failure"),
            receipt_claims=_tuple_of_strings(raw.get("receipt_claims"), "receipt_claims"),
            effect_state_claim=raw.get("effect_state_claim"),
            authority_claims=_tuple_of_strings(
                raw.get("authority_claims"), "authority_claims"
            ),
            advisory_signals=_advisory_signals(raw.get("advisory_signals")),
        )
    except KeyError as exc:
        raise ReplayValidationError(f"candidate missing required field: {exc.args[0]}") from exc
    candidate.validate()
    return candidate


def _parse_source(raw: Any) -> ReplaySource:
    if not isinstance(raw, dict):
        raise ReplayValidationError("source entries must be JSON objects")
    try:
        source = ReplaySource(
            source_id=raw["source_id"],
            source_version=raw.get("source_version"),
            locator=raw.get("locator"),
            admission_status=raw.get("admission_status"),
            is_current=raw.get("is_current"),
            origin_id=raw.get("origin_id"),
        )
    except KeyError as exc:
        raise ReplayValidationError(f"source missing required field: {exc.args[0]}") from exc
    source.validate()
    return source


def _parse_case(raw: Any) -> ReplayCase:
    if not isinstance(raw, dict):
        raise ReplayValidationError("case entries must be JSON objects")
    try:
        disposition = Disposition(raw["gold_disposition"])
        raw_candidates = raw.get("candidates", [])
        raw_sources = raw.get("sources", [])
        if not isinstance(raw_candidates, list) or not isinstance(raw_sources, list):
            raise ReplayValidationError("candidates and sources must be JSON lists")
        case = ReplayCase(
            case_id=raw["case_id"],
            fixture_version=raw["fixture_version"],
            fixture_provenance=raw["fixture_provenance"],
            literal_request=raw["literal_request"],
            primary_candidate_id=raw["primary_candidate_id"],
            gold_disposition=disposition,
            gold_answer=raw.get("gold_answer"),
            expected_violations=_tuple_of_strings(
                raw.get("expected_violations"), "expected_violations"
            ),
            candidates=tuple(_parse_candidate(item) for item in raw_candidates),
            sources=tuple(_parse_source(item) for item in raw_sources),
        )
    except KeyError as exc:
        raise ReplayValidationError(f"case missing required field: {exc.args[0]}") from exc
    except ValueError as exc:
        if isinstance(exc, ReplayValidationError):
            raise
        raise ReplayValidationError(f"invalid disposition: {raw.get('gold_disposition')!r}") from exc
    case.validate()
    return case


def load_replay_cases(path: str | Path) -> tuple[ReplayCase, ...]:
    """Load and fail-closed validate a deterministic replay fixture file."""
    fixture_path = Path(path)
    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayValidationError(f"unable to load replay fixture: {fixture_path}") from exc

    if isinstance(payload, dict):
        raw_cases = payload.get("cases")
    else:
        raw_cases = payload
    if not isinstance(raw_cases, list):
        raise ReplayValidationError("replay fixture root must be a list or {'cases': [...]} object")

    cases = tuple(_parse_case(item) for item in raw_cases)
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ReplayValidationError("case IDs must be unique within a fixture")
    return cases
