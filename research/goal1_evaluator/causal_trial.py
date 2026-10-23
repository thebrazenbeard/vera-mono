"""Four-arm causal-learning protocol prototype (synthetic, evaluator-controlled).

No model is invoked here. This module binds caller-reported model prompt/response
hashes to a controller-assigned pre-feedback receipt. Hashes are not independent
proof of dispatch or model execution; this is not an independent security boundary
against a process with the same OS privileges.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

ARMS = ("LEARNED", "FROZEN", "PLACEBO", "SHUFFLED")
TRAIN = (("bits:100", "A"), ("bits:010", "B"), ("bits:001", "B"), ("bits:111", "A"))
HOLDOUT = (("bits:110", "B"), ("bits:101", "B"), ("bits:011", "A"), ("bits:000", "A"))
BUDGET_PER_PREDICTION = 1
MAX_ATTEMPTS_PER_ARM_CASE = 1
STOP_AFTER_HOLDOUT_CASES = 4
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_DISPATCH_FIELDS = frozenset({
    "witness_kind", "gateway_id", "signature", "resource_usage", "reservation_id",
    "attestation_id", "invocation_id", "run_id", "arm",
    "challenge_id", "challenge_view_digest", "model_prompt_sha256",
    "model_response_sha256", "model_identity", "model_artifact_sha256",
    "dispatch_monotonic_ns", "response_monotonic_ns", "outcome_status",
})


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _require_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True)
class Challenge:
    challenge_id: str
    phase: str
    features: str

    def learner_view(self) -> dict[str, str]:
        return {"challenge_id": self.challenge_id, "features": self.features}


class CausalTrialController:
    """Small controller that keeps labels in private state and assigns order itself."""

    def __init__(self, suite_id: str = "GOAL1-LIVE-20261023-02", *, dispatch_evidence_verifier=None, expected_model_identity: str = "synthetic-test-model", expected_model_artifact_sha256: str | None = None):
        if not suite_id:
            raise ValueError("suite_id required")
        self.suite_id = suite_id
        if dispatch_evidence_verifier is not None:
            from research.goal1_evaluator.dispatch_attestation import Ed25519DispatchEvidenceVerifier
            if not isinstance(dispatch_evidence_verifier, Ed25519DispatchEvidenceVerifier):
                raise TypeError("dispatch verifier must be a pinned Ed25519DispatchEvidenceVerifier; boolean verifier stubs are forbidden")
        self._dispatch_evidence_verifier = dispatch_evidence_verifier
        self._expected_model_identity = expected_model_identity
        self._expected_model_artifact_sha256 = expected_model_artifact_sha256 or ("a" * 64)
        self._used_invocations: set[str] = set()
        self._used_attestations: set[str] = set()
        rows = []
        self._truth: dict[str, str] = {}
        for phase, specs in (("train", TRAIN), ("holdout", HOLDOUT)):
            for i, (features, label) in enumerate(specs):
                cid = digest({"suite": suite_id, "phase": phase, "index": i})[:24]
                rows.append(Challenge(cid, phase, features))
                self._truth[cid] = label
        self._challenges = {c.challenge_id: c for c in rows}
        self.challenge_ids_frozen = tuple(c.challenge_id for c in rows)
        self.scoring_method_frozen = "exact-match accuracy on all 4 holdout cases; no partial batch score"
        self.budgets_frozen = {"units_per_prediction": BUDGET_PER_PREDICTION, "max_attempts_per_arm_case": MAX_ATTEMPTS_PER_ARM_CASE}
        self.stopping_rule_frozen = f"stop after all 4 holdout cases are committed for each arm; {STOP_AFTER_HOLDOUT_CASES} cases/arm"
        self._predictions: dict[tuple[str, str], dict[str, object]] = {}
        self._feedback_released: set[tuple[str, str]] = set()
        self._seq = 0
        self._closed = False
        self._prompt_corrections: dict[str, str] = {}

    def issue(self, phase: str) -> tuple[dict[str, str], ...]:
        if phase not in ("train", "holdout"):
            raise ValueError("invalid phase")
        return tuple(c.learner_view() for c in self._challenges.values() if c.phase == phase)

    def commit_prediction(
        self, *, arm: str, challenge_id: str, prediction: str,
        challenge_view_digest: str, model_prompt_sha256: str,
        model_response_sha256: str, budget_units: int,
        dispatch_evidence: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Commit prediction plus distinct challenge, prompt, and response identities.

        model_prompt_sha256/model_response_sha256 are caller-reported hashes of the
        exact prompt/response bytes. This function cannot prove those bytes were
        actually submitted/returned; the host adapter must obtain them from the
        model transport and provide independent dispatch evidence if required.
        """
        if self._closed:
            raise ValueError("trial is closed")
        if arm not in ARMS:
            raise ValueError("unknown arm")
        challenge = self._challenges.get(challenge_id)
        if challenge is None:
            raise ValueError("unknown challenge")
        if prediction not in ("A", "B", "ABSTAIN"):
            raise ValueError("invalid prediction")
        if type(budget_units) is not int or budget_units != BUDGET_PER_PREDICTION:
            raise ValueError("budget mismatch")
        expected_view_digest = digest(challenge.learner_view())
        if challenge_view_digest != expected_view_digest:
            raise ValueError("challenge view digest mismatch")
        _require_sha256(model_prompt_sha256, "model_prompt_sha256")
        _require_sha256(model_response_sha256, "model_response_sha256")
        key = (arm, challenge_id)
        if key in self._predictions:
            raise ValueError("duplicate attempt or reused case for arm")
        evidence = self._verify_dispatch_evidence(
            dispatch_evidence, arm=arm, challenge_id=challenge_id,
            challenge_view_digest=expected_view_digest,
            prompt_sha256=model_prompt_sha256, response_sha256=model_response_sha256,
        )
        self._seq += 1
        body = {
            "arm": arm,
            "challenge_id": challenge_id,
            "challenge_view_digest": expected_view_digest,
            "prediction": prediction,
            "model_prompt_sha256": model_prompt_sha256,
            "model_response_sha256": model_response_sha256,
            "dispatch_attestation_id": evidence["attestation_id"],
            "dispatch_reservation_id": evidence["reservation_id"],
            "gateway_id": evidence["gateway_id"],
            "dispatch_resource_usage": dict(evidence["resource_usage"]),
            "dispatch_resource_usage_attested": True,
            "invocation_id": evidence["invocation_id"],
            "model_identity": evidence["model_identity"],
            "model_artifact_sha256": evidence["model_artifact_sha256"],
            "dispatch_evidence_verified": True,
            "sequence": self._seq,
            "budget_units": budget_units,
            "budget_kind": "protocol_counter_not_measured_usage",
            "resource_usage_measured": False,
        }
        receipt = dict(body, receipt_digest=digest(body))
        self._predictions[key] = receipt
        self._used_invocations.add(str(evidence["invocation_id"]))
        self._used_attestations.add(str(evidence["attestation_id"]))
        return dict(receipt)

    def _verify_dispatch_evidence(self, evidence, *, arm, challenge_id, challenge_view_digest, prompt_sha256, response_sha256):
        if evidence is None or self._dispatch_evidence_verifier is None:
            raise ValueError("independently verified dispatch evidence required")
        if not isinstance(evidence, dict) or not REQUIRED_DISPATCH_FIELDS.issubset(evidence):
            raise ValueError("dispatch evidence fields missing")
        # The verifier must authenticate an attestation from a separately controlled
        # dispatch gateway/observer. A same-host caller-created record is not enough.
        verifier = self._dispatch_evidence_verifier
        if evidence["witness_kind"] != "independent_dispatch_gateway":
            raise ValueError("independent dispatch witness required")
        if (evidence["arm"] != arm or evidence["challenge_id"] != challenge_id
                or evidence["challenge_view_digest"] != challenge_view_digest
                or evidence["model_prompt_sha256"] != prompt_sha256
                or evidence["model_response_sha256"] != response_sha256):
            raise ValueError("dispatch evidence binding mismatch")
        if evidence["model_identity"] != self._expected_model_identity:
            raise ValueError("model identity mismatch")
        if evidence["model_artifact_sha256"] != self._expected_model_artifact_sha256:
            raise ValueError("model artifact identity mismatch")
        if (not isinstance(evidence["invocation_id"], str) or not evidence["invocation_id"]
                or not isinstance(evidence["attestation_id"], str) or not evidence["attestation_id"]):
            raise ValueError("dispatch invocation/attestation identity missing")
        if evidence["invocation_id"] in self._used_invocations or evidence["attestation_id"] in self._used_attestations:
            raise ValueError("replayed dispatch invocation or attestation")
        start, end = evidence["dispatch_monotonic_ns"], evidence["response_monotonic_ns"]
        if type(start) is not int or type(end) is not int or start < 0 or end <= start:
            raise ValueError("invalid dispatch timestamp ordering")
        try:
            verified = verifier.verify(evidence)
        except Exception as exc:
            raise ValueError("dispatch attestation verification failed") from exc
        if verified is not True:
            raise ValueError("dispatch attestation verification failed")
        return evidence

    def release_feedback(self, *, arm: str, challenge_id: str) -> str:
        key = (arm, challenge_id)
        challenge = self._challenges.get(challenge_id)
        if arm not in ARMS or challenge is None or challenge.phase != "train":
            raise ValueError("feedback allowed only for known training cases")
        if key not in self._predictions:
            raise ValueError("prediction must be committed before feedback")
        if key in self._feedback_released:
            raise ValueError("feedback is one-use")
        if arm == "FROZEN":
            # Do not consume a feedback token when feedback is disallowed.
            raise ValueError("FROZEN arm receives no feedback")
        self._feedback_released.add(key)
        truth = self._truth[challenge_id]
        if arm == "PLACEBO":
            return "A"  # Deliberately non-informative fixed feedback.
        if arm == "SHUFFLED":
            train_ids = [c.challenge_id for c in self._challenges.values() if c.phase == "train"]
            index = train_ids.index(challenge_id)
            return self._truth[train_ids[(index + 1) % len(train_ids)]]
        return truth

    def record_correction_context(self, *, arm: str, challenge_id: str, text: str) -> None:
        """Stores context only; does not change scores or establish learning."""
        if arm not in ARMS or challenge_id not in self._challenges or not text:
            raise ValueError("invalid correction context")
        self._prompt_corrections[arm] = text

    def score(self) -> dict[str, dict[str, object]]:
        holdout_ids = [c.challenge_id for c in self._challenges.values() if c.phase == "holdout"]
        expected = {(arm, cid) for arm in ARMS for cid in holdout_ids}
        if set(self._predictions).intersection(expected) != expected:
            raise ValueError("all holdout predictions must be committed before scoring")
        result = {}
        for arm in ARMS:
            rows = [self._predictions[(arm, cid)] for cid in holdout_ids]
            correct = sum(row["prediction"] == self._truth[row["challenge_id"]] for row in rows)
            result[arm] = {
                "scored_cases": len(rows),
                "correct": correct,
                "accuracy": correct / len(rows),
                "budget_units": sum(row["budget_units"] for row in rows),
                "budget_kind": "protocol_counter_not_measured_usage",
                "resource_usage_measured": False,
            }
        self._closed = True
        return result

    def audit_receipts(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(v) for v in self._predictions.values())

    def correction_context_is_learning_evidence(self, arm: str) -> bool:
        # Explicit invariant: stored text is not an outcome or causal evidence.
        return False
