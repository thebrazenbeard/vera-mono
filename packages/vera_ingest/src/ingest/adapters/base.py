from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..model import Acquisition
from ..policy import IngestPolicy


class IngestError(Exception):
    pass


class PolicyRejected(IngestError):
    pass


class AcquisitionFailed(IngestError):
    pass


@runtime_checkable
class SourceAdapter(Protocol):
    name: str
    version: str

    def supports(self, source: Any) -> bool: ...

    def acquire(self, source: Any, policy: IngestPolicy) -> Acquisition: ...
