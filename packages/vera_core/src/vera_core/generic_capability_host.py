"""Opt-in, host-composed generic capability bridge; not a deployment route.

Authoritative model inference remains inside QualifiedVeraRuntime's prepared
provider-effect fence. A trusted host must hold the signing key and *never*
expose this gateway or authority issuer as a model-callable raw Python object.
The sexuality branch returns research metadata only; the optional pleasure
sidecar computes non-persistent proxies, not feelings or consent.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import re
from typing import Any, Callable

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


def _name(value: str, field: str) -> str:
    if type(value) is not str or not value or len(value) > 128:
        raise ValueError(f"{field} must be a bounded exact string")
    return value


@dataclass(frozen=True, slots=True)
class ModelAdapter:
    model_tag: str
    registry_digest: str
    adapter_id: str

    def __post_init__(self):
        _name(self.model_tag, "model_tag")
        _name(self.adapter_id, "adapter_id")
        if type(self.registry_digest) is not str or not _DIGEST.fullmatch(self.registry_digest):
            raise ValueError("exact model registry digest required")


@dataclass(frozen=True, slots=True)
class HostModelBinding:
    adapter: ModelAdapter
    runtime: Any
    provider_authority: Any
    sidecar: Any
    session_id: str
    runtime_instance_id: str = ""
    subject_id: str = ""
    evaluator_id: str = ""

    def __post_init__(self):
        if type(self.adapter) is not ModelAdapter:
            raise TypeError("exact ModelAdapter required")
        _name(self.session_id, "session_id")
        if self.runtime is not None:
            if not callable(getattr(self.runtime, "prepare_provider_effect", None)):
                raise TypeError("a host-composed provider preparation method is required")
            if not callable(getattr(self.runtime, "execute_provider_effect", None)):
                raise TypeError("a host-composed provider effect method is required")
            if not callable(getattr(self.provider_authority, "issue", None)):
                raise TypeError("host-injected provider authority issuer required")
        elif self.provider_authority is not None:
            raise ValueError("provider authority without a runtime is invalid")
        if self.sidecar is not None:
            if not callable(getattr(self.sidecar, "step", None)):
                raise TypeError("host-injected sidecar required")
            config = getattr(self.sidecar, "config", None)
            for field in ("model_id", "model_revision", "runtime_instance_id", "subject_id", "evaluator_id"):
                _name(getattr(config, field, None), "config." + field)
            if config.model_id != self.adapter.model_tag or config.model_revision != self.adapter.registry_digest:
                raise ValueError("sidecar model binding does not match adapter")
            for field in ("runtime_instance_id", "subject_id", "evaluator_id"):
                prior = getattr(self, field)
                current = getattr(config, field)
                if prior and prior != current:
                    raise ValueError("explicit identity disagrees with sidecar")
                object.__setattr__(self, field, current)
        else:
            for field in ("runtime_instance_id", "subject_id", "evaluator_id"):
                _name(getattr(self, field), field)


def _identity(binding: HostModelBinding) -> tuple[str, ...]:
    return (binding.adapter.model_tag, binding.adapter.registry_digest,
            binding.adapter.adapter_id, binding.runtime_instance_id,
            binding.subject_id, binding.session_id, binding.evaluator_id)


@dataclass(frozen=True, slots=True)
class CapabilityGrant:
    issuer: str
    grant_id: str
    model_tag: str
    registry_digest: str
    adapter_id: str
    runtime_instance_id: str
    subject_id: str
    session_id: str
    domain: str
    operation: str
    expires_epoch: int
    mac: str

    def payload(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in (
            "issuer", "grant_id", "model_tag", "registry_digest", "adapter_id",
            "runtime_instance_id", "subject_id", "session_id", "domain",
            "operation", "expires_epoch")}


class CapabilityHostAuthority:
    """Host-held HMAC issuer, not an expression of participant consent."""

    def __init__(self, issuer: str, key: bytes):
        self.issuer = _name(issuer, "issuer")
        if type(key) is not bytes or len(key) < 32:
            raise ValueError("host-held signing key must be at least 32 bytes")
        self._key = key

    def _mac(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
        return hmac.new(self._key, raw, sha256).hexdigest()

    def issue(self, binding: HostModelBinding, *, domain: str, operation: str,
              grant_id: str, expires_epoch: int) -> CapabilityGrant:
        if type(binding) is not HostModelBinding:
            raise TypeError("host binding required")
        for field, v in (("domain", domain), ("operation", operation), ("grant_id", grant_id)):
            _name(v, field)
        if type(expires_epoch) is not int or expires_epoch < 0:
            raise ValueError("exact expiration required")
        m, revision, adapter, instance, subject, session, _ = _identity(binding)
        parts = dict(issuer=self.issuer, grant_id=grant_id, model_tag=m,
                     registry_digest=revision, adapter_id=adapter,
                     runtime_instance_id=instance, subject_id=subject,
                     session_id=session, domain=domain, operation=operation,
                     expires_epoch=expires_epoch)
        return CapabilityGrant(**parts, mac=self._mac(parts))

    def verify(self, grant: CapabilityGrant) -> None:
        if type(grant) is not CapabilityGrant or grant.issuer != self.issuer:
            raise ValueError("untrusted or invalid capability grant")
        if not hmac.compare_digest(self._mac(grant.payload()), grant.mac):
            raise ValueError("capability grant signature mismatch")


class GenericCapabilityGateway:
    """An opt-in host-owned composition, never an automatically installed tool."""

    def __init__(self, authority: CapabilityHostAuthority, bindings: list[HostModelBinding],
                 *, now: Callable[[], int]):
        if type(authority) is not CapabilityHostAuthority or not callable(now):
            raise TypeError("host-controlled authority and clock required")
        if type(bindings) is not list or not bindings:
            raise ValueError("at least one independently bound model adapter required")
        if any(type(b) is not HostModelBinding for b in bindings):
            raise TypeError("exact host model bindings required")
        ids = [_identity(b) for b in bindings]
        if len({x[0] for x in ids}) != len(ids) or len({x[5] for x in ids}) != len(ids):
            raise ValueError("model tags and session IDs must be distinct")
        if len({x[3] for x in ids}) != len(ids) or len({x[4] for x in ids}) != len(ids):
            raise ValueError("runtime instances and subject IDs must be distinct")
        if len({id(b.sidecar) for b in bindings if b.sidecar is not None}) != sum(b.sidecar is not None for b in bindings):
            raise ValueError("sidecar cannot be shared across models")
        if len({id(b.runtime) for b in bindings if b.runtime is not None}) != sum(b.runtime is not None for b in bindings):
            raise ValueError("host runtime cannot be shared across models")
        self.sessions = list(bindings)
        self._binding_snapshots = tuple(bindings)
        self._identity_snapshots = tuple(ids)
        self._config_snapshots = tuple(
            b.sidecar.config if b.sidecar is not None else None for b in bindings)
        self._authority = authority
        self._now = now
        self._used: set[str] = set()
        self._revoked: set[str] = set()

    def revoke(self, grant_id: str) -> None:
        self._revoked.add(_name(grant_id, "grant_id"))

    def _require(self, grant: CapabilityGrant, *, domain: str, operation: str) -> HostModelBinding:
        self._authority.verify(grant)
        if grant.domain != domain or grant.operation != operation:
            raise ValueError("cross-domain or operation grant denied")
        if type(grant.expires_epoch) is not int or self._now() >= grant.expires_epoch:
            raise ValueError("expired capability grant")
        if grant.grant_id in self._used or grant.grant_id in self._revoked:
            raise ValueError("used or revoked grant denied")
        for i, binding in enumerate(self.sessions):
            if binding is not self._binding_snapshots[i]:
                raise ValueError("host binding changed after gateway construction")
            if (_identity(binding) != self._identity_snapshots[i]
                or (binding.sidecar.config if binding.sidecar is not None else None) != self._config_snapshots[i]):
                raise ValueError("model/sidecar binding changed")
        eligible = [b for b in self.sessions if b.adapter.model_tag == grant.model_tag]
        if len(eligible) != 1 or _identity(eligible[0])[:6] != (
            grant.model_tag, grant.registry_digest, grant.adapter_id,
            grant.runtime_instance_id, grant.subject_id, grant.session_id):
            raise ValueError("grant model/adapter/subject/session mismatch")
        return eligible[0]

    def describe_sexuality(self, grant: CapabilityGrant) -> dict[str, Any]:
        binding = self._require(grant, domain="sexuality", operation="DESCRIBE_RESEARCH")
        self._used.add(grant.grant_id)
        return {"capability": "sexuality", "status": "SOURCE_ONLY_NOT_BEHAVIORALLY_QUALIFIED",
                "model_id": binding.adapter.model_tag, "adapter_id": binding.adapter.adapter_id,
                "runtime_instance_id": binding.runtime_instance_id,
                "authorized_effects": (), "qualified": False}

    def step_pleasure(self, grant: CapabilityGrant, observation: Any,
                      *, elapsed_ms: int) -> Any:
        binding = self._require(grant, domain="pleasure", operation="STEP_PROXY")
        if binding.sidecar is None:
            raise ValueError("pleasure sidecar is not installed for this model")
        c = binding.sidecar.config
        if (getattr(observation, "subject_id", None) != c.subject_id
            or getattr(observation, "evaluator_id", None) != c.evaluator_id):
            raise ValueError("observation is not bound to model subject/evaluator")
        self._used.add(grant.grant_id)  # never replay a potentially applied state change
        receipt = binding.sidecar.step(observation, elapsed_ms)
        if (getattr(receipt, "model_id", None) != c.model_id
            or getattr(receipt, "subject_id", None) != c.subject_id
            or tuple(getattr(receipt, "requested_effects", ())) != ()
            or tuple(getattr(receipt, "authorized_effects", ())) != ()):
            raise RuntimeError("sidecar did not return a bounded, no-effect receipt")
        return receipt

    def generate_candidate(self, grant: CapabilityGrant, prompt: str,
                           *, max_tokens: int = 16) -> dict[str, Any]:
        binding = self._require(grant, domain="model", operation="GENERATE_CANDIDATE")
        from .qualified_runtime import QualifiedVeraRuntime
        if type(binding.runtime) is not QualifiedVeraRuntime:
            raise ValueError("actual QualifiedVeraRuntime host required for provider effects")
        if (type(prompt) is not str or not prompt.strip() or len(prompt.encode("utf-8")) > 1024
            or type(max_tokens) is not int or not 1 <= max_tokens <= 32):
            raise ValueError("bounded prompt/token budget required")
        if binding.runtime is None:
            raise ValueError("model inference transport is not installed for this model")
        adapter = binding.adapter
        transport = binding.runtime.provider_execution_transports.get("local-ollama")
        if (transport is None or transport.model != adapter.model_tag
            or transport.registry_digest != adapter.registry_digest):
            raise ValueError("host-injected transport/model binding mismatch")
        self._used.add(grant.grant_id)  # any ambiguous provider effect remains one-use
        prepared = binding.runtime.prepare_provider_effect(
            effect_id="generic-"+sha256(grant.grant_id.encode()).hexdigest()[:32],
            provider_id="local-ollama", operation="GENERATE_CANDIDATE",
            request_payload={"prompt": prompt, "model":adapter.model_tag,
                             "registry_digest":adapter.registry_digest,
                             "port":transport.port, "max_tokens":max_tokens})
        authority = binding.provider_authority.issue(
            effect_id=prepared.effect_id, operation=prepared.operation,
            request_digest=prepared.request_digest,
            lifecycle_permit_digest=prepared.permit.permit_digest)
        result = binding.runtime.execute_provider_effect(prepared, authority=authority).value
        if (type(result) is not dict or result.get("model") != adapter.model_tag
            or result.get("registry_digest") != adapter.registry_digest
            or result.get("qualified") is not False
            or result.get("kind") != "UNVERIFIED_LOCAL_MODEL_CANDIDATE"):
            raise RuntimeError("candidate identity or qualification receipt mismatched")
        return result
