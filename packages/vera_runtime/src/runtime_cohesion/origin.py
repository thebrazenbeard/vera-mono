from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping, Protocol
import re
import weakref


SEMANTIC_CURRENTNESS_DISPATCH_ID = "dispatch:semantic-currentness"
SEMANTIC_CURRENTNESS_DOMAIN = "SEMANTICS_PROVENANCE_CURRENTNESS"
SEMANTIC_CURRENTNESS_PROPOSITION = "SEMANTIC_PROVENANCE_CURRENTNESS_STATUS"
SEMANTIC_CURRENTNESS_REFERENT_SCOPE = "EXACT_PROPOSITION_REFERENT_SOURCE_BINDING"
SEMANTIC_DECISIVE_CLASSES = frozenset({"control_source", "live_observation"})
SEMANTIC_ORIGIN_COMPOSITION_TRUST = "IN_PROCESS_UNROOTED_NON_QUALIFYING"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ProviderOriginProof:
    """Exact-object origin result produced by an origin verifier.

    The proof describes what a verifier claims to have observed. It is not, by
    itself, proof that the verifier was independently rooted. In particular,
    the in-process composition hook below is deliberately nonqualifying: code
    that can install a first writer can also manufacture a perfectly shaped
    proof. Qualifying provider/currentness admission therefore requires an
    independently rooted host/provider boundary that this source-only module
    does not pretend to provide.
    """

    issuer_provider: str
    repository: str
    commit: str
    path: str
    git_blob: str
    sha256: str
    source_logical_id: str
    owner_logical_id: str
    owner_path: str
    owner_git_blob: str
    currentness_state: str
    supersession_state: str
    observed_at: str
    validation_method: str

    def __post_init__(self) -> None:
        for name in (
            "issuer_provider",
            "repository",
            "commit",
            "path",
            "git_blob",
            "sha256",
            "source_logical_id",
            "owner_logical_id",
            "owner_path",
            "owner_git_blob",
            "currentness_state",
            "supersession_state",
            "observed_at",
            "validation_method",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if not _HEX40.fullmatch(self.commit):
            raise ValueError("origin commit must be an exact 40-hex Git commit")
        if not _HEX40.fullmatch(self.git_blob):
            raise ValueError("origin git_blob must be an exact 40-hex Git blob")
        if not _HEX40.fullmatch(self.owner_git_blob):
            raise ValueError("origin owner_git_blob must be an exact 40-hex Git blob")
        if not _HEX64.fullmatch(self.sha256):
            raise ValueError("origin sha256 must be an exact 64-hex SHA-256")
        candidate = self.observed_at[:-1] + "+00:00" if self.observed_at.endswith("Z") else self.observed_at
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("origin observed_at must be valid ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("origin observed_at must be timezone-aware")


class SemanticOriginVerifier(Protocol):
    provider: str

    def verify(self, envelope: Any) -> ProviderOriginProof | None: ...


@dataclass(frozen=True)
class ValidatedProviderOrigin:
    issuer_provider: str
    repository: str
    commit: str
    path: str
    git_blob: str
    sha256: str
    source_logical_id: str
    owner_logical_id: str
    owner_path: str
    owner_git_blob: str
    currentness_state: str
    supersession_state: str
    validation_method: str


_COMPOSITION_LOCK = RLock()
_RUNTIME_ORIGIN_VERIFIERS: Mapping[str, SemanticOriginVerifier] | None = None
_REGISTRY_LOCK = RLock()
_VALIDATED_ORIGINS: dict[int, tuple[weakref.ReferenceType[Any], ValidatedProviderOrigin]] = {}


def semantic_origin_composition_trust() -> str:
    """Return the evidence ceiling of the source-only verifier composition."""

    return SEMANTIC_ORIGIN_COMPOSITION_TRUST


def _policy_for(contract: Mapping[str, Any]) -> Mapping[str, Any] | None:
    registry = contract.get("provider_origin_validation")
    if not isinstance(registry, Mapping):
        return None
    policy = registry.get(SEMANTIC_CURRENTNESS_DISPATCH_ID)
    return policy if isinstance(policy, Mapping) else None


def _relational_binding(contract: Mapping[str, Any]) -> Mapping[str, Any] | None:
    registry = contract.get("resolver_dispatch_decisive_evidence")
    decisive = registry.get(SEMANTIC_CURRENTNESS_DISPATCH_ID) if isinstance(registry, Mapping) else None
    relational = decisive.get("relational_binding") if isinstance(decisive, Mapping) else None
    return relational if isinstance(relational, Mapping) else None


def _expected_origin(contract: Mapping[str, Any]) -> dict[str, str] | None:
    root = contract.get("control_root")
    if not isinstance(root, Mapping):
        return None
    fields = {
        "repository": root.get("source_repository"),
        "commit": root.get("source_commit"),
        "path": root.get("source_path"),
        "git_blob": root.get("source_git_blob"),
        "sha256": root.get("manifest_sha256"),
        "source_logical_id": root.get("source_logical_id"),
        "owner_logical_id": root.get("owner_logical_id"),
        "owner_path": root.get("owner_path"),
        "owner_git_blob": root.get("owner_git_blob"),
    }
    if not all(isinstance(value, str) and value for value in fields.values()):
        return None
    if not _HEX40.fullmatch(str(fields["commit"])) or not _HEX40.fullmatch(str(fields["git_blob"])):
        return None
    if not _HEX40.fullmatch(str(fields["owner_git_blob"])):
        return None
    if not _HEX64.fullmatch(str(fields["sha256"])):
        return None
    return {key: str(value) for key, value in fields.items()}


def _install_semantic_origin_verifiers(verifiers: Mapping[str, SemanticOriginVerifier]) -> None:
    """Install one source/mechanics origin-verifier composition.

    This private composition is intentionally separate from AdapterRegistry and
    remains useful for deterministic mechanics and hostile source tests. It is
    *not* an authentication root: a same-process first writer can implement both
    the verifier and the proof it returns. Consequently this hook is permanently
    classified ``IN_PROCESS_UNROOTED_NON_QUALIFYING`` and cannot, by itself,
    register semantic-currentness provenance for provider-strict admission.
    """

    if not isinstance(verifiers, Mapping) or not verifiers:
        raise ValueError("semantic origin verifier composition must be a non-empty mapping")
    normalized: dict[str, SemanticOriginVerifier] = {}
    for provider, verifier in verifiers.items():
        if not isinstance(provider, str) or not provider:
            raise ValueError("semantic origin verifier provider keys must be non-empty strings")
        if getattr(verifier, "provider", None) != provider:
            raise ValueError(f"semantic origin verifier provider mismatch for {provider!r}")
        if not callable(getattr(verifier, "verify", None)):
            raise ValueError(f"semantic origin verifier for {provider!r} lacks verify")
        normalized[provider] = verifier

    global _RUNTIME_ORIGIN_VERIFIERS
    with _COMPOSITION_LOCK:
        if _RUNTIME_ORIGIN_VERIFIERS is None:
            _RUNTIME_ORIGIN_VERIFIERS = MappingProxyType(dict(normalized))
            return
        existing = _RUNTIME_ORIGIN_VERIFIERS
        if set(existing) == set(normalized) and all(existing[key] is normalized[key] for key in existing):
            return
        raise RuntimeError("runtime semantic origin verifier composition is already installed and cannot be replaced")


def _reset_semantic_origin_verifiers_for_tests() -> None:
    """Private test-isolation hook; never a claimant provenance operation."""

    global _RUNTIME_ORIGIN_VERIFIERS
    with _COMPOSITION_LOCK:
        _RUNTIME_ORIGIN_VERIFIERS = None
    with _REGISTRY_LOCK:
        _VALIDATED_ORIGINS.clear()


def _runtime_origin_verifier(provider: str) -> SemanticOriginVerifier | None:
    with _COMPOSITION_LOCK:
        verifiers = _RUNTIME_ORIGIN_VERIFIERS
        return None if verifiers is None else verifiers.get(provider)


def _validate_unrooted_origin_proof(
    envelope: Any,
    contract: Mapping[str, Any],
) -> ProviderOriginProof | None:
    """Validate proof *shape and cross-binding* without promoting its trust.

    A successful result means only that the in-process verifier produced a
    structurally coherent proof for the exact envelope. It does not authenticate
    the verifier itself and therefore cannot satisfy provider-strict currentness.
    """

    evidence_class = getattr(envelope, "evidence_class", None)
    referent = getattr(envelope, "referent", None)
    if evidence_class not in SEMANTIC_DECISIVE_CLASSES or referent != SEMANTIC_CURRENTNESS_DOMAIN:
        return None

    expected = _expected_origin(contract)
    policy = _policy_for(contract)
    relational = _relational_binding(contract)
    if expected is None or policy is None or relational is None:
        return None
    if policy.get("required_for_provider_admission") is not True:
        return None
    if policy.get("claimant_metadata_is_not_origin_proof") is not True:
        return None
    expected_policy_fields = [
        "source_repository",
        "source_commit",
        "source_path",
        "source_git_blob",
        "manifest_sha256",
        "owner_logical_id",
        "owner_path",
        "owner_git_blob",
    ]
    if policy.get("exact_control_root_fields") != expected_policy_fields:
        return None

    provider_rules = policy.get("provider_methods")
    if not isinstance(provider_rules, Mapping):
        return None
    rule = provider_rules.get(evidence_class)
    if not isinstance(rule, Mapping):
        return None
    expected_provider = rule.get("provider")
    expected_method = rule.get("validation_method")
    if not isinstance(expected_provider, str) or not isinstance(expected_method, str):
        return None
    if getattr(envelope, "provider", None) != expected_provider:
        return None

    verifier = _runtime_origin_verifier(expected_provider)
    if verifier is None:
        return None
    try:
        proof = verifier.verify(envelope)
    except Exception:
        return None
    if not isinstance(proof, ProviderOriginProof):
        return None
    if proof.issuer_provider != expected_provider or proof.validation_method != expected_method:
        return None

    required_currentness = relational.get("required_currentness_state")
    required_supersession = relational.get("required_supersession_state")
    required_source_identity = relational.get("required_source_identity")
    if not all(isinstance(value, str) and value for value in (required_currentness, required_supersession, required_source_identity)):
        return None

    if proof.observed_at != getattr(envelope, "observed_at", None):
        return None
    if any(getattr(proof, field) != value for field, value in expected.items()):
        return None
    if proof.currentness_state != required_currentness:
        return None
    if proof.supersession_state != required_supersession:
        return None

    if getattr(envelope, "revision", None) != expected["commit"]:
        return None
    if getattr(envelope, "content_digest", None) != expected["sha256"]:
        return None
    if getattr(envelope, "supersession_state", None) != required_supersession:
        return None

    metadata = getattr(envelope, "metadata", None)
    if not isinstance(metadata, Mapping):
        return None
    metadata_expected = {
        "binding_source_identity": required_source_identity,
        "binding_source_revision": expected["commit"],
        "binding_currentness_state": required_currentness,
        "binding_supersession_state": required_supersession,
    }
    if any(metadata.get(field) != value for field, value in metadata_expected.items()):
        return None
    return proof


def validate_and_register_semantic_origin(
    envelope: Any,
    contract: Mapping[str, Any],
) -> bool:
    """Fail closed unless semantic origin is rooted outside this process hook.

    The current source-only integration exposes no independently rooted provider
    capability. We still validate the in-process proof for mechanical regression
    coverage, but a coherent unrooted proof is deliberately *not registered* as
    a ``ValidatedProviderOrigin``. A future production host must supply an
    independently rooted capability via a separately governed boundary; adding
    such a boundary is not simulated here.
    """

    proof = _validate_unrooted_origin_proof(envelope, contract)
    if proof is None:
        return False
    return False


def validated_semantic_origin(envelope: Any, contract: Mapping[str, Any]) -> ValidatedProviderOrigin | None:
    """Resolve qualifying provider origin for this exact live envelope.

    Source-only in-process verifier composition is explicitly unrooted and can
    never produce this result. Until an independently rooted host/provider
    capability is integrated, provider-strict semantic-currentness admission
    therefore remains fail-closed/UNRESOLVED rather than fabricating CURRENT.
    """

    expected = _expected_origin(contract)
    relational = _relational_binding(contract)
    if expected is None or relational is None:
        return None
    required_currentness = relational.get("required_currentness_state")
    required_supersession = relational.get("required_supersession_state")
    if not isinstance(required_currentness, str) or not isinstance(required_supersession, str):
        return None

    key = id(envelope)
    with _REGISTRY_LOCK:
        entry = _VALIDATED_ORIGINS.get(key)
        validated = entry[1] if entry is not None and entry[0]() is envelope else None

    if validated is None:
        # Deliberately exercise/validate the unrooted composition, but never
        # convert it into qualifying provider-currentness provenance.
        validate_and_register_semantic_origin(envelope, contract)
        return None
    if any(getattr(validated, field) != value for field, value in expected.items()):
        return None
    if validated.currentness_state != required_currentness or validated.supersession_state != required_supersession:
        return None
    return validated
