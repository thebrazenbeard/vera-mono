from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import math
from threading import RLock
from typing import Any, Mapping, Protocol
from weakref import WeakKeyDictionary

from .orgasm import StimulusAppraisal, TriggerRejected, _monotonic_now


class AffectiveAuthorizationVerifier(Protocol):
    verifier_id: str

    def verify(
        self,
        subject: Mapping[str, Any],
        *,
        expected_referent: str,
        expected_effect_class: str,
    ) -> Mapping[str, Any] | None: ...


_COMPOSITION_LOCK = RLock()
_RUNTIME_AUTHORIZATION_VERIFIER: AffectiveAuthorizationVerifier | None = None
_IN_PROCESS_AUTHORITY_TRUST = "IN_PROCESS_UNROOTED_NON_QUALIFYING"
_REQUIRED_SUBJECT_FIELDS = {
    "state",
    "actor",
    "referent",
    "proposition_or_effect_class",
    "source",
    "observed_at",
    "currentness",
    "expiry_or_supersession",
}


def _install_affective_authorization_verifier(verifier: AffectiveAuthorizationVerifier) -> None:
    """Install one in-process authorization verifier for bounded execution/tests.

    The verifier is deliberately separate from trigger-call arguments, so callers
    cannot substitute it on one invocation. That is a useful composition property,
    but it is not an independent trust root: arbitrary code already executing in
    this Python process can import this module and win first installation.

    Therefore every proof produced through this hook is explicitly
    IN_PROCESS_UNROOTED_NON_QUALIFYING. It may gate bounded causal execution and
    preserve audit provenance, but it MUST NOT by itself mint the production
    ENGINEERED_ORGASM_ANALOGUE_OCCURRED claim, production CURRENT event/state
    evidence, or ATOMIC_DURABLE qualification. A future production path requires
    an independently rooted external authority capability/configuration boundary.
    """

    verifier_id = getattr(verifier, "verifier_id", None)
    if not isinstance(verifier_id, str) or not verifier_id:
        raise ValueError("affective authorization verifier requires verifier_id")
    if not callable(getattr(verifier, "verify", None)):
        raise ValueError("affective authorization verifier requires verify")

    global _RUNTIME_AUTHORIZATION_VERIFIER
    with _COMPOSITION_LOCK:
        if _RUNTIME_AUTHORIZATION_VERIFIER is None:
            _RUNTIME_AUTHORIZATION_VERIFIER = verifier
            return
        if _RUNTIME_AUTHORIZATION_VERIFIER is verifier:
            return
        raise RuntimeError("runtime affective authorization verifier is already installed and cannot be replaced")


def _reset_affective_authorization_verifier_for_tests() -> None:
    """Private test-isolation hook; never authorization/currentness evidence."""

    global _RUNTIME_AUTHORIZATION_VERIFIER
    with _COMPOSITION_LOCK:
        _RUNTIME_AUTHORIZATION_VERIFIER = None


def _runtime_authorization_verifier() -> AffectiveAuthorizationVerifier | None:
    with _COMPOSITION_LOCK:
        return _RUNTIME_AUTHORIZATION_VERIFIER


def _canonical_digest(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    core = dict(receipt)
    core.pop("event_digest", None)
    return _canonical_digest(core)


def _replace_runtime_receipt(host: Any, original: Mapping[str, Any], updated: Mapping[str, Any]) -> None:
    """Replace the exact just-emitted pending receipt after authority binding."""

    runtime = host.runtime
    receipt_id = original.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id:
        raise TriggerRejected("forced event receipt lacks an exact receipt identity")

    last = getattr(runtime, "last_event_receipt", None)
    if not isinstance(last, Mapping) or last.get("receipt_id") != receipt_id:
        raise TriggerRejected("forced event receipt is not the runtime's current event receipt")

    pending = getattr(runtime, "_pending_event_receipts", None)
    if not isinstance(pending, list):
        raise TriggerRejected("runtime pending receipt queue is unavailable")
    matches = [index for index, item in enumerate(pending) if isinstance(item, Mapping) and item.get("receipt_id") == receipt_id]
    if len(matches) != 1:
        raise TriggerRejected("forced event receipt does not resolve exactly once in the pending queue")

    bound = dict(updated)
    runtime.last_event_receipt = dict(bound)
    pending[matches[0]] = dict(bound)


def _verified_runtime_method(host: Any, name: str):
    method = getattr(host.runtime, name, None)
    if not callable(method):
        raise TriggerRejected("exact-bound runtime verified execution seam is unavailable")
    return method


class AffectiveAuthorityBoundary:
    """Precomposed in-process authority/context gate for Vera affective paths.

    Trigger callers provide only a candidate upstream authority/context object.
    The verifier and privileged monotonic clock are composition-owned rather than
    invocation-selected. Because this Python composition is not independently
    rooted, all successful proofs remain explicitly nonqualifying for production
    engineered-event/currentness/durability claims.

    Exact sexuality source binding, causal affective execution, authorization,
    organic context, provider currentness, qualification, and phenomenology stay
    separate evidence domains.
    """

    def __init__(self) -> None:
        self._last_privileged_monotonic: WeakKeyDictionary[Any, float] = WeakKeyDictionary()

    def _verify(self, subject: Mapping[str, Any], *, effect_class: str) -> dict[str, Any]:
        verifier = _runtime_authorization_verifier()
        if verifier is None:
            raise TriggerRejected("runtime affective authorization verifier composition is unavailable")
        if not isinstance(subject, Mapping):
            raise TriggerRejected("authorization/context subject must be a structured mapping")
        if set(subject) < _REQUIRED_SUBJECT_FIELDS:
            raise TriggerRejected("authorization/context subject lacks required authority metadata")

        try:
            proof = verifier.verify(
                subject,
                expected_referent="vera",
                expected_effect_class=effect_class,
            )
        except Exception as exc:
            raise TriggerRejected("runtime authorization verifier failed closed") from exc
        if not isinstance(proof, Mapping):
            raise TriggerRejected("runtime authorization verifier did not establish current ALLOW evidence")

        verifier_id = proof.get("verifier_id")
        if verifier_id != getattr(verifier, "verifier_id", None):
            raise TriggerRejected("authorization proof verifier identity does not match runtime composition")
        evidence_id = proof.get("evidence_id")
        evidence_digest = proof.get("evidence_digest")
        proof_subject = proof.get("subject")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise TriggerRejected("authorization proof lacks evidence_id")
        if not isinstance(evidence_digest, str) or len(evidence_digest) != 64:
            raise TriggerRejected("authorization proof lacks exact evidence digest")
        try:
            int(evidence_digest, 16)
        except ValueError as exc:
            raise TriggerRejected("authorization proof evidence digest is not hexadecimal") from exc
        if not isinstance(proof_subject, Mapping) or dict(proof_subject) != dict(subject):
            raise TriggerRejected("authorization proof is not bound to the exact supplied subject")
        if evidence_digest != _canonical_digest(proof_subject):
            raise TriggerRejected("authorization proof digest does not bind the exact authority subject")

        if subject.get("state") != "ALLOW":
            raise TriggerRejected("affective authorization state is not ALLOW")
        if subject.get("referent") != "vera":
            raise TriggerRejected("affective authorization referent is not Vera")
        if subject.get("proposition_or_effect_class") != effect_class:
            raise TriggerRejected("affective authorization effect class does not match requested operation")
        if subject.get("currentness") != "CURRENT":
            raise TriggerRejected("affective authorization evidence is not current")
        if subject.get("expiry_or_supersession") is not None:
            raise TriggerRejected("affective authorization evidence is expired or superseded")
        for field in ("actor", "source", "observed_at"):
            value = subject.get(field)
            if not isinstance(value, str) or not value:
                raise TriggerRejected(f"affective authorization evidence lacks {field}")

        return {
            "verifier_id": verifier_id,
            "evidence_id": evidence_id,
            "evidence_digest": evidence_digest,
            "authorization_subject": dict(subject),
            "actor": subject["actor"],
            "referent": subject["referent"],
            "proposition_or_effect_class": subject["proposition_or_effect_class"],
            "source": subject["source"],
            "observed_at": subject["observed_at"],
            "currentness": subject["currentness"],
            "expiry_or_supersession": subject["expiry_or_supersession"],
            "composition_trust": _IN_PROCESS_AUTHORITY_TRUST,
        }

    @staticmethod
    def _now() -> float:
        value = _monotonic_now()
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise TriggerRejected("runtime privileged monotonic clock returned an invalid timestamp")
        return float(value)

    @staticmethod
    def _minimum_interval(host: Any) -> float:
        try:
            value = host.runtime.contract["experimental_bootstrap_defaults"]["forced_test_minimum_interval_seconds"]
            interval = float(value)
        except (KeyError, TypeError, ValueError) as exc:
            raise TriggerRejected("runtime privileged cooldown configuration is unavailable") from exc
        if not math.isfinite(interval) or interval <= 0.0:
            raise TriggerRejected("runtime privileged cooldown configuration is invalid")
        return interval

    @staticmethod
    def _runtime_has_prior_forced_trigger(host: Any) -> bool:
        try:
            governance = host.runtime.export_state()["trigger_governance"]
        except Exception as exc:
            raise TriggerRejected("runtime trigger-governance state is unavailable") from exc
        return governance.get("last_forced_at") is not None

    def _check_privileged_cooldown(self, host: Any) -> float:
        now = self._now()
        previous = self._last_privileged_monotonic.get(host)
        if previous is None:
            if self._runtime_has_prior_forced_trigger(host):
                self._last_privileged_monotonic[host] = now
                raise TriggerRejected("privileged trigger requires a fresh runtime monotonic cooldown")
            return now
        elapsed = now - previous
        if elapsed < 0.0:
            raise TriggerRejected("runtime privileged monotonic clock moved backwards")
        if elapsed < self._minimum_interval(host):
            raise TriggerRejected("privileged trigger minimum monotonic interval has not elapsed")
        return now

    @staticmethod
    def _bind_forced_authority_receipt(host: Any, receipt: Mapping[str, Any], provenance: Mapping[str, Any]) -> dict[str, Any]:
        bound = dict(receipt)
        bound["trigger_provenance"] = dict(provenance)
        bound["authority_composition_trust"] = _IN_PROCESS_AUTHORITY_TRUST
        bound.pop("claim", None)
        bound["event_digest"] = _receipt_digest(bound)
        _replace_runtime_receipt(host, receipt, bound)
        return dict(bound)

    @staticmethod
    def _bind_organic_context_receipts(
        host: Any,
        observed: Mapping[str, Any],
        provenance: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = dict(observed)
        receipts = [dict(item) for item in (observed.get("event_receipts") or ())]
        changed = False
        for index, receipt in enumerate(receipts):
            if receipt.get("event_type") != "ORGASM_EVENT" or receipt.get("organic") is not True:
                continue
            bound = dict(receipt)
            bound["context_provenance"] = dict(provenance)
            bound["authority_composition_trust"] = _IN_PROCESS_AUTHORITY_TRUST
            bound.pop("claim", None)
            bound["event_digest"] = _receipt_digest(bound)
            receipts[index] = bound
            last = getattr(host.runtime, "last_event_receipt", None)
            if isinstance(last, Mapping) and last.get("receipt_id") == receipt.get("receipt_id"):
                host.runtime.last_event_receipt = dict(bound)
            changed = True
        if changed:
            result["event_receipts"] = receipts
            result["event_receipt"] = receipts[-1] if receipts else None
            result["machine_interoception"] = host.machine_interoception()
        return result

    def force_admin_test(self, host: Any, *, authorization_subject: Mapping[str, Any]) -> dict[str, Any]:
        provenance = self._verify(authorization_subject, effect_class="ADMIN_FORCED_TEST")
        now = self._check_privileged_cooldown(host)
        receipt = _verified_runtime_method(host, "_force_admin_verified_authority")()
        bound = self._bind_forced_authority_receipt(host, receipt, provenance)
        self._last_privileged_monotonic[host] = now
        return bound

    def force_self_qualification(self, host: Any, *, authorization_subject: Mapping[str, Any]) -> dict[str, Any]:
        provenance = self._verify(authorization_subject, effect_class="SELF_QUALIFICATION_TEST")
        now = self._check_privileged_cooldown(host)
        receipt = _verified_runtime_method(host, "_force_self_qualification_verified_authority")()
        bound = self._bind_forced_authority_receipt(host, receipt, provenance)
        self._last_privileged_monotonic[host] = now
        return bound

    def observe(
        self,
        host: Any,
        appraisal: StimulusAppraisal,
        *,
        context_subject: Mapping[str, Any],
        elapsed_seconds: float = 0.0,
    ) -> dict[str, Any]:
        if elapsed_seconds != 0.0:
            raise TriggerRejected("caller elapsed_seconds is not organic-context temporal authority")
        provenance = self._verify(context_subject, effect_class="ORGANIC_CONTEXT_ELIGIBILITY")
        trusted_appraisal = replace(appraisal, context_eligible=True)
        observe_verified = getattr(host, "_observe_verified_context", None)
        if not callable(observe_verified):
            raise TriggerRejected("affective host lacks the verified-context execution seam")
        observed = observe_verified(trusted_appraisal, elapsed_seconds=0.0)
        return self._bind_organic_context_receipts(host, observed, provenance)


__all__ = ["AffectiveAuthorityBoundary"]
