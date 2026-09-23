from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

MAX_ADDRESS_LENGTH = 320
_ADDRESS_RE = re.compile(
    r"^(?P<namespace>[a-z][a-z0-9_-]*):(?P<node>[A-Za-z0-9][A-Za-z0-9._/-]*)$"
)


class Performative(str, Enum):
    QUERY = "QUERY"
    REPORT = "REPORT"
    REQUEST = "REQUEST"
    EXECUTE = "EXECUTE"
    REVIEW = "REVIEW"
    ACK = "ACK"
    REJECT = "REJECT"
    WAIT = "WAIT"
    CONFLICT = "CONFLICT"
    CANCEL = "CANCEL"
    RECEIPT = "RECEIPT"


class EffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    REVERSIBLE_MUTATION = "REVERSIBLE_MUTATION"
    PROTECTED_MUTATION = "PROTECTED_MUTATION"
    IRREVERSIBLE = "IRREVERSIBLE"


class SecurityProfile(str, Enum):
    OPEN = "OPEN"
    PRIVATE = "PRIVATE"
    SEALED = "SEALED"


class AdmissionDecision(str, Enum):
    ALLOW = "ALLOW"
    DUPLICATE = "DUPLICATE"
    REJECT = "REJECT"
    QUARANTINE = "QUARANTINE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class Address:
    namespace: str
    node: str

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not isinstance(self.node, str):
            raise ValueError("address namespace and node must be strings")
        raw = f"{self.namespace}:{self.node}"
        if len(raw) > MAX_ADDRESS_LENGTH or _ADDRESS_RE.fullmatch(raw) is None:
            raise ValueError(f"invalid Intranel address: {raw!r}")

    @classmethod
    def parse(cls, raw: str) -> "Address":
        if not isinstance(raw, str) or len(raw) > MAX_ADDRESS_LENGTH:
            raise ValueError("address must be a bounded string")
        match = _ADDRESS_RE.fullmatch(raw)
        if match is None:
            raise ValueError(f"invalid Intranel address: {raw!r}")
        return cls(match.group("namespace"), match.group("node"))

    def __str__(self) -> str:
        return f"{self.namespace}:{self.node}"
