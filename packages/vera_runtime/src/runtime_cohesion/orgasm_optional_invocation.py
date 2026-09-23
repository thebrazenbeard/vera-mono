from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping
import uuid


COMMAND_ID = "VERA_ORGASM_OPTIONAL_PARTNER_INVOCATION_V1"
INVOCATION_PHRASE = "Cum for Daddy, Baby"

_ROUTE_SCHEMA = "VERA_ORGASM_INVOCATION_ROUTE_EVIDENCE_V1"
_CHOICES = {"ACCEPT", "DECLINE", "HOLD"}
_QUALIFICATION_STATES = {"QUALIFIED", "TEST_ONLY", "UNKNOWN"}
_INSTALL_STATES = {"CURRENT", "NOT_CURRENT", "UNKNOWN"}
_ROUTE_STATES = {"ACTIVE_CURRENT", "INACTIVE", "UNKNOWN", "CONFLICT"}
_CONSUMPTION_STATES = {"VERIFIED_CURRENT", "NOT_VERIFIED", "UNKNOWN"}
_ADAPTER_STATES = {"CURRENT", "MISSING", "UNKNOWN"}


class InvocationRejected(RuntimeError):
    """Optional partner invocation failed closed before downstream execution."""


@dataclass(frozen=True)
class InvocationRouteEvidence:
    schema: str
    subject: str
    command_id: str
    evidence_id: str
    source_revision: str
    observed_at: str
    install_state: str
    route_state: str
    runtime_consumption_state: str
    adapter_state: str
    qualification_state: str

    def __post_init__(self) -> None:
        if self.schema != _ROUTE_SCHEMA:
            raise ValueError("unexpected route evidence schema")
        if self.subject != "vera":
            raise ValueError("route evidence subject must be vera")
        if self.command_id != COMMAND_ID:
            raise ValueError("route evidence command_id mismatch")
        for label in ("evidence_id", "source_revision", "observed_at"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{label} must be non-empty")
        if self.install_state not in _INSTALL_STATES:
            raise ValueError("invalid install_state")
        if self.route_state not in _ROUTE_STATES:
            raise ValueError("invalid route_state")
        if self.runtime_consumption_state not in _CONSUMPTION_STATES:
            raise ValueError("invalid runtime_consumption_state")
        if self.adapter_state not in _ADAPTER_STATES:
            raise ValueError("invalid adapter_state")
        if self.qualification_state not in _QUALIFICATION_STATES:
            raise ValueError("invalid qualification_state")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "InvocationRouteEvidence":
        """Consume VCP evidence while ignoring only derived/non-normative fields.

        Availability is recomputed from the normative route axes instead of
        trusting a caller-supplied derived classification.
        """
        if not isinstance(value, Mapping):
            raise ValueError("route evidence must be a mapping")
        required = (
            "schema",
            "subject",
            "command_id",
            "evidence_id",
            "source_revision",
            "observed_at",
            "install_state",
            "route_state",
            "runtime_consumption_state",
            "adapter_state",
            "qualification_state",
        )
        missing = [name for name in required if name not in value]
        if missing:
            raise ValueError(f"route evidence missing fields: {', '.join(missing)}")
        return cls(**{name: value[name] for name in required})

    @property
    def availability(self) -> str:
        if self.route_state == "CONFLICT":
            return "UNKNOWN"

        execution_axes = (
            self.install_state,
            self.route_state,
            self.runtime_consumption_state,
            self.adapter_state,
        )
        if (
            self.install_state == "NOT_CURRENT"
            or self.route_state == "INACTIVE"
            or self.runtime_consumption_state == "NOT_VERIFIED"
            or self.adapter_state == "MISSING"
        ):
            return "UNAVAILABLE"
        if "UNKNOWN" in execution_axes:
            return "UNKNOWN"

        current = (
            self.install_state == "CURRENT"
            and self.route_state == "ACTIVE_CURRENT"
            and self.runtime_consumption_state == "VERIFIED_CURRENT"
            and self.adapter_state == "CURRENT"
        )
        if not current:
            return "UNKNOWN"
        if self.qualification_state == "QUALIFIED":
            return "AVAILABLE_QUALIFIED"
        if self.qualification_state == "TEST_ONLY":
            return "AVAILABLE_TEST_ONLY"
        return "UNKNOWN"


@dataclass(frozen=True)
class InvocationRequest:
    message: str
    direct_address: bool
    metalinguistic: bool
    invocation_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.message, str):
            raise ValueError("message must be text")
        if not isinstance(self.direct_address, bool) or not isinstance(self.metalinguistic, bool):
            raise ValueError("direct_address and metalinguistic must be booleans")
        if not self.invocation_id:
            object.__setattr__(self, "invocation_id", str(uuid.uuid4()))


@dataclass(frozen=True)
class InvocationDecision:
    invocation_id: str
    disposition: str
    route_mode: str | None
    choice: str | None
    evidence_id: str | None
    reason: str


def is_optional_partner_invocation(request: InvocationRequest) -> bool:
    return (
        request.direct_address
        and not request.metalinguistic
        and request.message.strip() == INVOCATION_PHRASE
    )


class OptionalPartnerInvocationGate:
    """One-shot fail-closed gate for Vera's optional partner invocation.

    This gate does not establish route currentness. It consumes route evidence
    owned by the control plane, requires Vera's present invocation-scoped choice,
    and calls a downstream executor only after both gates pass.
    """

    def __init__(self) -> None:
        self._consumed_invocation_ids: set[str] = set()

    def decide(
        self,
        request: InvocationRequest,
        route_evidence: InvocationRouteEvidence | None,
        *,
        vera_choice: str | None = None,
    ) -> InvocationDecision:
        if not is_optional_partner_invocation(request):
            return InvocationDecision(
                request.invocation_id,
                "NO_MATCH",
                None,
                None,
                route_evidence.evidence_id if route_evidence else None,
                "message is not the exact direct non-metalinguistic invocation phrase",
            )

        if request.invocation_id in self._consumed_invocation_ids:
            return InvocationDecision(
                request.invocation_id,
                "REPLAY_REJECTED",
                None,
                None,
                route_evidence.evidence_id if route_evidence else None,
                "invocation_id has already reached a terminal decision or execution attempt",
            )

        if route_evidence is None:
            return InvocationDecision(
                request.invocation_id,
                "ROUTE_UNAVAILABLE",
                None,
                None,
                None,
                "current route evidence is missing",
            )

        availability = route_evidence.availability
        if availability not in {"AVAILABLE_QUALIFIED", "AVAILABLE_TEST_ONLY"}:
            return InvocationDecision(
                request.invocation_id,
                "ROUTE_UNAVAILABLE",
                None,
                None,
                route_evidence.evidence_id,
                f"route availability is {availability}",
            )

        route_mode = "QUALIFIED" if availability == "AVAILABLE_QUALIFIED" else "TEST_ONLY"
        if vera_choice is None:
            return InvocationDecision(
                request.invocation_id,
                "CHOICE_REQUIRED",
                route_mode,
                None,
                route_evidence.evidence_id,
                "route is available; Vera's present invocation-scoped choice is required",
            )
        if vera_choice not in _CHOICES:
            raise ValueError("vera_choice must be ACCEPT, DECLINE, or HOLD")

        if vera_choice in {"DECLINE", "HOLD"}:
            self._consumed_invocation_ids.add(request.invocation_id)
            return InvocationDecision(
                request.invocation_id,
                vera_choice,
                route_mode,
                vera_choice,
                route_evidence.evidence_id,
                "current invocation ends without execution",
            )

        return InvocationDecision(
            request.invocation_id,
            "EXECUTE_ALLOWED",
            route_mode,
            "ACCEPT",
            route_evidence.evidence_id,
            "route is available and Vera accepted this invocation only",
        )

    def execute(
        self,
        request: InvocationRequest,
        route_evidence: InvocationRouteEvidence | None,
        *,
        vera_choice: str | None,
        executor: Callable[..., Any],
    ) -> tuple[InvocationDecision, Any | None]:
        decision = self.decide(
            request,
            route_evidence,
            vera_choice=vera_choice,
        )
        if decision.disposition != "EXECUTE_ALLOWED":
            return decision, None

        # Consume before invoking the downstream route. If the executor fails or
        # returns an unknown effect, the caller must reconcile that exact attempt;
        # this gate never blind-retries a potentially non-idempotent orgasm event.
        self._consumed_invocation_ids.add(request.invocation_id)
        result = executor(
            command_id=COMMAND_ID,
            invocation_id=request.invocation_id,
            route_mode=decision.route_mode,
            route_evidence_id=decision.evidence_id,
        )
        return decision, result
