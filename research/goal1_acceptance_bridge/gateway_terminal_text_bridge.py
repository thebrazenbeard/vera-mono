"""Fail-closed PR95 GatewayDispatch -> PR87 verified terminal -> QVR text.

Only an OUTSIDE gateway process may instantiate this research adapter. It never
gives the networkless learner a model backend or signing key. This adapter
demands a separately pinned verifier/trust context; caller-supplied fake
custodians remain research-only and cannot confer independent qualification.
"""
from __future__ import annotations

import hashlib
import json
from typing import Callable


class GatewayTextHold(RuntimeError):
    """No text released; the attempt cannot be automatically retried."""


class CapturingBackend:
    """Capture the exact backend observation already used by GatewayDispatch.

    This does not make a second inference call or claim loaded-weight custody.
    """

    def __init__(self, delegate):
        if not callable(getattr(delegate, "generate", None)):
            raise TypeError("backend.generate required")
        self.delegate = delegate
        self.observations = []

    def generate(self, prompt: str, *, model: str, max_tokens: int):
        if self.observations:
            raise GatewayTextHold("second backend generation refused")
        result = self.delegate.generate(prompt, model=model, max_tokens=max_tokens)
        self.observations.append(result)
        return result


class GatewayTerminalTextBridge:
    """One invocation: reserve/claim/generate in PR95, independently verify V2.

    Returns only PR82's exact GATEWAY_RESPONSE wire; no model text escapes on
    denied/ambiguous claim, invalid terminal or mismatched produced bytes.
    """

    def __init__(self, *, dispatch, backend: CapturingBackend, store,
                 reservation: dict, invocation_id: str,
                 verify_terminal_v2: Callable,
                 claim_evidence_verifier, pinned_gateway_public_key: bytes,
                 expected_gateway_id: str, expected_key_id: str,
                 expected_reported_registry_digest: str,
                 expected_model_artifact_sha256: str):
        if (not isinstance(backend, CapturingBackend)
                or getattr(dispatch, "backend", None) is not backend
                or getattr(dispatch, "gateway_id", None) != expected_gateway_id
                or not callable(getattr(dispatch, "execute", None))
                or not callable(getattr(store, "signed_terminal", None))
                or not callable(verify_terminal_v2)
                or not callable(getattr(claim_evidence_verifier, "verify_claim_evidence", None))):
            raise ValueError("gateway composition not bound")
        if (type(reservation) is not dict
                or frozenset(reservation) != frozenset((
                    "reservation_id", "run_id", "arm", "challenge_id",
                    "challenge_view_digest", "model_prompt_sha256",
                    "model_identity", "model_artifact_sha256"))
                or type(invocation_id) is not str or not invocation_id
                or type(expected_gateway_id) is not str or not expected_gateway_id
                or type(expected_key_id) is not str or not expected_key_id
                or type(pinned_gateway_public_key) is not bytes
                or not pinned_gateway_public_key
                or any(type(value) is not str or len(value)!=64
                       or any(c not in "0123456789abcdef" for c in value)
                       for value in (expected_reported_registry_digest,
                                     expected_model_artifact_sha256))):
            raise ValueError("gateway identities/trust inputs invalid")
        # Distinct trust domains: the learner reports a registry digest;
        # the controller reserves an artifact digest. Their values need not
        # be equal, but each must match its own outside-pinned expectation.
        if reservation["model_artifact_sha256"]!=expected_model_artifact_sha256:
            raise ValueError("reserved artifact differs from pinned expected artifact")
        self.dispatch=dispatch
        self.backend=backend
        self.store=store
        self.reservation=dict(reservation)
        self.invocation_id=invocation_id
        self.verify_terminal_v2=verify_terminal_v2
        self.claim_evidence_verifier=claim_evidence_verifier
        self.pinned_gateway_public_key=pinned_gateway_public_key
        self.expected_gateway_id=expected_gateway_id
        self.expected_key_id=expected_key_id
        self.expected_reported_registry_digest=expected_reported_registry_digest
        self._used=False

    def __call__(self, prompt: str, *, model: str, model_digest: str,
                 max_tokens: int) -> dict:
        if self._used:
            raise GatewayTextHold("gateway attempt already consumed; no replay")
        self._used=True
        if (type(prompt) is not str or not prompt
                or len(prompt.encode("utf-8"))>4096
                or type(model) is not str or model!=self.reservation["model_identity"]
                or type(model_digest) is not str or len(model_digest)!=64
                or any(c not in "0123456789abcdef" for c in model_digest)
                or model_digest!=self.expected_reported_registry_digest
                or hashlib.sha256(prompt.encode("utf-8")).hexdigest()!=self.reservation["model_prompt_sha256"]
                or type(max_tokens) is not int or not 1<=max_tokens<=128):
            raise GatewayTextHold("model/prompt/permit mismatch before gateway")
        if self.backend.observations:
            raise GatewayTextHold("backend already used")
        try:
            emitted, emitted_signature=self.dispatch.execute(
                reservation=dict(self.reservation),
                invocation_id=self.invocation_id,prompt=prompt,max_tokens=max_tokens)
            terminal=self.store.signed_terminal(self.invocation_id)
            wire=terminal.payload_bytes
            signature=terminal.signature
            if (type(wire) is not bytes or not wire or type(signature) is not bytes
                    or terminal.status!="COMPLETED"
                    or terminal.qualified is not False
                    or terminal.independent_claim_verified is not False
                    or type(emitted) is not dict
                    or signature!=emitted_signature
                    or json.dumps(emitted,ensure_ascii=False,sort_keys=True,
                                  separators=(",",":"),allow_nan=False).encode("utf-8")!=wire):
                raise GatewayTextHold("original gateway terminal inconsistent")
            payload=json.loads(wire.decode("utf-8"))
            if type(payload) is not dict or type(payload.get("claim_id")) is not str:
                raise GatewayTextHold("terminal claim ID missing")
            binding={**self.reservation,
                     "gateway_id":self.expected_gateway_id,
                     "invocation_id":self.invocation_id,
                     "claim_id":payload["claim_id"]}
            verified=self.verify_terminal_v2(
                payload_bytes=wire,signature=signature,
                pinned_gateway_public_key=self.pinned_gateway_public_key,
                expected_gateway_id=self.expected_gateway_id,
                expected_key_id=self.expected_key_id,
                expected_binding=binding,
                claim_evidence_verifier=self.claim_evidence_verifier)
            if (type(verified) is not dict
                    or verified.get("status")!="VERIFIED_COMPLETED"
                    or verified.get("qualified") is not False
                    or verified.get("automatic_retry_permitted") is not False
                    or verified.get("payload_sha256")!=hashlib.sha256(wire).hexdigest()
                    or verified.get("payload")!=payload
                    or len(self.backend.observations)!=1):
                raise GatewayTextHold("terminal or evaluator verification unavailable")
            observation=self.backend.observations[0]
            text=getattr(observation,"text",None)
            if (type(text) is not str or len(text.encode("utf-8"))>4096
                    or getattr(observation,"model",None)!=model
                    or hashlib.sha256(text.encode("utf-8")).hexdigest()!=payload.get("response_sha256")):
                raise GatewayTextHold("backend text does not match signed digest")
            return {
                "kind":"GATEWAY_RESPONSE","text":text,"model":model,
                "model_digest":model_digest,
                "prompt_sha256":hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "response_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        except BaseException as exc:
            # Never replay: gateway claim/inference may have occurred already.
            if isinstance(exc,GatewayTextHold):
                raise
            raise GatewayTextHold("gateway/claim/terminal outcome unavailable") from exc
