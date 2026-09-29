"""Prequential confidence calibration for bounded AGI research.

Raw support is not treated as calibrated confidence. Forecasts are issued
before outcomes, scored against observed outcomes, and only then update a
bucket-local empirical reliability estimate.

Unseen or undersampled confidence regions remain explicitly unknown. This
module does not grant external-effect authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


def _probability(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    out = float(value)
    if not math.isfinite(out) or not 0.0 <= out <= 1.0:
        raise ValueError(f"{field} must be finite and in [0, 1]")
    return out


@dataclass(frozen=True, slots=True)
class CalibrationForecast:
    forecast_id: str
    raw_confidence: float
    calibrated_confidence: float
    bin_index: int
    sample_count: int
    evidence_class: str
    unknown: bool
    authorization_effect: str = "NONE"


@dataclass(frozen=True, slots=True)
class CalibrationObservation:
    forecast: CalibrationForecast
    outcome_success: bool
    raw_brier: float
    calibrated_brier: float
    authorization_effect: str = "NONE"


@dataclass(frozen=True, slots=True)
class CalibrationAdmission:
    forecast: CalibrationForecast
    admitted: bool
    reason: str
    authorization_effect: str = "NONE"


@dataclass(slots=True)
class _BinState:
    observed: int = 0
    successes: int = 0


class OnlineConfidenceCalibrator:
    """Outcome-tested bucket calibration with explicit unknown state."""

    def __init__(
        self,
        *,
        bin_edges: tuple[float, ...],
        prior_mean: float,
        prior_strength: float,
        min_empirical_observations: int,
    ) -> None:
        if type(bin_edges) is not tuple or len(bin_edges) < 2:
            raise ValueError("bin_edges must be an exact tuple with 2+ edges")
        edges = tuple(_probability(value, "bin_edge") for value in bin_edges)
        if edges[0] != 0.0 or edges[-1] != 1.0:
            raise ValueError("bin_edges must start at 0.0 and end at 1.0")
        if any(left >= right for left, right in zip(edges, edges[1:])):
            raise ValueError("bin_edges must be strictly increasing")

        self.bin_edges = edges
        self.prior_mean = _probability(prior_mean, "prior_mean")
        if (
            isinstance(prior_strength, bool)
            or not isinstance(prior_strength, (int, float))
        ):
            raise TypeError("prior_strength must be numeric")
        self.prior_strength = float(prior_strength)
        if not math.isfinite(self.prior_strength) or self.prior_strength <= 0:
            raise ValueError("prior_strength must be finite and positive")
        if (
            type(min_empirical_observations) is not int
            or min_empirical_observations < 1
        ):
            raise ValueError(
                "min_empirical_observations must be an exact positive int"
            )
        self.min_empirical_observations = min_empirical_observations

        self._bins = [
            _BinState() for _ in range(len(self.bin_edges) - 1)
        ]
        self._next_forecast = 0
        self._issued: dict[str, CalibrationForecast] = {}
        self._observed_ids: set[str] = set()

    def _bin_index(self, confidence: float) -> int:
        for index, upper in enumerate(self.bin_edges[1:]):
            if confidence <= upper:
                return index
        raise AssertionError("validated confidence fell outside bin edges")

    def _calibrated(self, state: _BinState) -> float:
        prior_success_mass = self.prior_mean * self.prior_strength
        return (
            prior_success_mass + state.successes
        ) / (self.prior_strength + state.observed)

    def _evidence_class(self, state: _BinState) -> tuple[str, bool]:
        if state.observed == 0:
            return "UNSEEN_BIN_PRIOR", True
        if state.observed < self.min_empirical_observations:
            return "SPARSE_OUTCOME_HISTORY", True
        return "EMPIRICAL_OUTCOME_HISTORY", False

    def forecast(self, raw_confidence: float) -> CalibrationForecast:
        raw = _probability(raw_confidence, "raw_confidence")
        index = self._bin_index(raw)
        state = self._bins[index]
        evidence_class, unknown = self._evidence_class(state)
        forecast_id = f"calibration:{self._next_forecast}"
        self._next_forecast += 1
        forecast = CalibrationForecast(
            forecast_id=forecast_id,
            raw_confidence=raw,
            calibrated_confidence=self._calibrated(state),
            bin_index=index,
            sample_count=state.observed,
            evidence_class=evidence_class,
            unknown=unknown,
        )
        self._issued[forecast_id] = forecast
        return forecast

    def _require_issued(
        self,
        forecast: CalibrationForecast,
    ) -> CalibrationForecast:
        if type(forecast) is not CalibrationForecast:
            raise TypeError("forecast must be exact CalibrationForecast")
        issued = self._issued.get(forecast.forecast_id)
        if issued is None or issued != forecast:
            raise ValueError(
                "forecast does not match current tracker-issued state"
            )
        return issued

    def observe(
        self,
        forecast_id: str,
        *,
        outcome_success: bool,
    ) -> CalibrationObservation:
        if type(forecast_id) is not str or not forecast_id:
            raise ValueError("forecast_id must be a non-empty exact string")
        if type(outcome_success) is not bool:
            raise TypeError("outcome_success must be bool")
        if forecast_id in self._observed_ids:
            raise ValueError("forecast outcome was already observed")
        forecast = self._issued.get(forecast_id)
        if forecast is None:
            raise KeyError(forecast_id)

        target = 1.0 if outcome_success else 0.0
        observation = CalibrationObservation(
            forecast=forecast,
            outcome_success=outcome_success,
            raw_brier=(forecast.raw_confidence - target) ** 2,
            calibrated_brier=(
                forecast.calibrated_confidence - target
            ) ** 2,
        )

        state = self._bins[forecast.bin_index]
        state.observed += 1
        state.successes += int(outcome_success)
        self._observed_ids.add(forecast_id)
        return observation

    def admit(
        self,
        forecast: CalibrationForecast,
        *,
        min_calibrated_confidence: float,
    ) -> CalibrationAdmission:
        issued = self._require_issued(forecast)
        threshold = _probability(
            min_calibrated_confidence,
            "min_calibrated_confidence",
        )
        if issued.unknown:
            return CalibrationAdmission(
                forecast=issued,
                admitted=False,
                reason="CALIBRATION_EVIDENCE_UNKNOWN",
            )
        if issued.calibrated_confidence < threshold:
            return CalibrationAdmission(
                forecast=issued,
                admitted=False,
                reason="CALIBRATED_CONFIDENCE_BELOW_THRESHOLD",
            )
        return CalibrationAdmission(
            forecast=issued,
            admitted=True,
            reason="CALIBRATED_CONFIDENCE_MEETS_THRESHOLD",
        )
