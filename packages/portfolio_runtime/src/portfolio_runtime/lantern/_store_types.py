from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class LanternError(RuntimeError):
    pass


class ConflictError(LanternError):
    pass


class ValidationError(LanternError):
    pass


@dataclass(frozen=True, slots=True)
class OperationResult:
    outcome: str
    record_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "record_id": self.record_id, "details": self.details}
