from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


FAILURE_STATUSES = {"NOT_TRIGGERED", "CANDIDATE_TRIGGERED"}


@dataclass(frozen=True)
class FailureEvaluationResult:
    signature_id: str
    status: str
    predicate_id: str
    target_ref: str
    action: str
    response: str
    missing_signals: tuple[str, ...]
    predicate_proven: bool = False

    def __post_init__(self) -> None:
        if self.status not in FAILURE_STATUSES:
            raise ValueError(f"unsupported failure evaluation status: {self.status}")
        if self.predicate_proven:
            raise ValueError("failure candidate evaluator may not claim predicate proof")


def _signal_active(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (str, bytes, list, tuple, set, dict)) and len(value) == 0:
        return False
    return True


def _target_action(target_ref: str, authority_resolvers: Mapping[str, Any]) -> str:
    if target_ref.startswith("resolver:"):
        resolver_id = target_ref[len("resolver:"):]
        if not resolver_id or resolver_id not in authority_resolvers:
            raise ValueError(f"failure target resolver does not resolve: {target_ref}")
        return "DISPATCH_RESOLVER"
    if target_ref.startswith("guard:"):
        guard_id = target_ref[len("guard:"):]
        if not guard_id:
            raise ValueError("failure guard target must be non-empty")
        return "FAIL_CLOSED_GUARD"
    raise ValueError(f"unsupported failure target_or_response_ref: {target_ref}")


def validate_failure_wiring(contract: Mapping[str, Any]) -> list[str]:
    """Validate that every declared failure signature has executable candidate routing.

    This deliberately validates *wiring*, not semantic truth. `predicate_id` is a
    stable identifier for the declared failure condition. Runtime evaluation below
    treats co-occurring declared signals only as a candidate trigger and never as
    proof that the prose matcher is semantically true.
    """

    errors: list[str] = []
    failures = contract.get("failure_signatures")
    resolvers = contract.get("authority_resolvers")
    if not isinstance(failures, Mapping) or not failures:
        return ["runtime contract requires failure_signatures for executable wiring"]
    if not isinstance(resolvers, Mapping) or not resolvers:
        return ["runtime contract requires authority_resolvers for executable failure routing"]

    predicate_ids: set[str] = set()
    for signature_id, signature in failures.items():
        if not isinstance(signature_id, str) or not signature_id or not isinstance(signature, Mapping):
            errors.append(f"invalid failure signature row: {signature_id!r}")
            continue
        predicate_id = signature.get("predicate_id")
        if not isinstance(predicate_id, str) or not predicate_id:
            errors.append(f"failure signature {signature_id!r} requires predicate_id")
        elif predicate_id in predicate_ids:
            errors.append(f"duplicate failure predicate_id {predicate_id!r}")
        else:
            predicate_ids.add(predicate_id)

        signal_keys = signature.get("signal_keys")
        if not isinstance(signal_keys, list) or not signal_keys:
            errors.append(f"failure signature {signature_id!r} requires signal_keys")
        elif any(not isinstance(key, str) or not key for key in signal_keys):
            errors.append(f"failure signature {signature_id!r} has invalid signal key")
        elif len(signal_keys) != len(set(signal_keys)):
            errors.append(f"failure signature {signature_id!r} has duplicate signal keys")

        target_ref = signature.get("target_or_response_ref")
        if not isinstance(target_ref, str) or not target_ref:
            errors.append(f"failure signature {signature_id!r} requires target_or_response_ref")
        else:
            try:
                _target_action(target_ref, resolvers)
            except ValueError as exc:
                errors.append(f"failure signature {signature_id!r}: {exc}")

        response = signature.get("response")
        if not isinstance(response, str) or not response.strip():
            errors.append(f"failure signature {signature_id!r} requires response")

    return errors


def evaluate_failure_signature(
    signature_id: str,
    signals: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> FailureEvaluationResult:
    """Evaluate one failure signature as a conservative candidate trigger.

    The evaluator is intentionally weaker than the prose matcher. It only proves
    that every declared signal needed to inspect the failure is materially present.
    When present, the declared resolver/guard becomes executable routing. Semantic
    confirmation remains the responsibility of that resolver/guard and current
    evidence; `predicate_proven` is always False.
    """

    wiring_errors = validate_failure_wiring(contract)
    if wiring_errors:
        raise ValueError("invalid failure wiring: " + "; ".join(wiring_errors))

    failures = contract["failure_signatures"]
    if signature_id not in failures:
        raise ValueError(f"unknown failure signature: {signature_id}")
    signature = failures[signature_id]
    required = tuple(signature["signal_keys"])
    missing = tuple(key for key in required if key not in signals or not _signal_active(signals[key]))
    target_ref = str(signature["target_or_response_ref"])
    action = _target_action(target_ref, contract["authority_resolvers"])

    return FailureEvaluationResult(
        signature_id=signature_id,
        status="NOT_TRIGGERED" if missing else "CANDIDATE_TRIGGERED",
        predicate_id=str(signature["predicate_id"]),
        target_ref=target_ref,
        action=action,
        response=str(signature["response"]),
        missing_signals=missing,
        predicate_proven=False,
    )
