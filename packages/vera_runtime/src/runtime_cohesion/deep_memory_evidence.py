from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "architecture" / "integration" / "VERA_EXTERNAL_EVIDENCE_PROVIDER_REGISTRY_V1.json"
RESULT_SCHEMA = ROOT / "architecture" / "integration" / "vendor" / "DEEP_MEMORY_EVIDENCE_RESULT_V1.schema.json"

EVIDENCE_SEARCH = "EVIDENCE_SEARCH"
ADMISSION_REVIEW = "HISTORICAL_TO_CURRENT_ADMISSION_REVIEW"
PROVIDER_ID = "deep_memory"
FORBIDDEN_RUNTIME_IDENTITY_KEYS = {
    "model", "model_id", "chat", "chat_id", "session", "session_id", "branch", "branch_id"
}


class EvidenceAuthorizationError(ValueError):
    pass


class EvidenceContractError(ValueError):
    pass


def _required_text(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceContractError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceContractError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceContractError(f"{path} must contain a JSON object")
    return value


@dataclass(frozen=True)
class EvidenceSearchRequest:
    query: str
    authorized_privacy_scopes: tuple[str, ...]
    privacy_mode: str = "AUTHORIZED_SCOPE_FILTER"
    archive_audit_authorized: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", _required_text("query", self.query))
        scopes = tuple(_required_text("privacy scope", scope) for scope in self.authorized_privacy_scopes)
        if len(scopes) != len(set(scopes)):
            raise EvidenceAuthorizationError("authorized privacy scopes must be unique")
        object.__setattr__(self, "authorized_privacy_scopes", scopes)
        if self.privacy_mode == "AUTHORIZED_SCOPE_FILTER":
            if not scopes:
                raise EvidenceAuthorizationError(
                    "EVIDENCE_SEARCH fails closed without exact caller-authorized privacy scopes"
                )
            if self.archive_audit_authorized:
                raise EvidenceAuthorizationError(
                    "archive_audit_authorized may only accompany EXPLICIT_ARCHIVE_AUDIT_ALL"
                )
        elif self.privacy_mode == "EXPLICIT_ARCHIVE_AUDIT_ALL":
            if not self.archive_audit_authorized:
                raise EvidenceAuthorizationError(
                    "archive-wide audit requires separate explicit authorization"
                )
        else:
            raise EvidenceAuthorizationError(f"unsupported privacy_mode: {self.privacy_mode}")


@dataclass(frozen=True)
class HistoricalEvidenceBatch:
    provider_id: str
    operation: str
    query: str
    retrieved_at: str
    privacy_mode: str
    authorized_privacy_scopes: tuple[str, ...]
    results: tuple[Mapping[str, Any], ...]
    claim_ceiling: str = "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY"
    canonical_memory_transfer: bool = False
    execution_authorized: bool = False

    @property
    def count(self) -> int:
        return len(self.results)


@dataclass(frozen=True)
class HistoricalAdmissionReview:
    operation: str
    authority_ref: str
    receipt_ref: str
    memory_id: str
    source_ids: tuple[str, ...]
    event_time: Any
    recorded_at: str | None
    historical_canonicity: str | None
    privacy_scope: str
    provenance_ceiling: Any
    currentness_rule: Any
    historical_canon_overlays: tuple[Mapping[str, Any], ...]
    amendments: tuple[Mapping[str, Any], ...]
    classification_corrections: tuple[Mapping[str, Any], ...]
    current_memory_write_performed: bool = False
    requires_separate_current_memory_write_authority: bool = True


Transport = Callable[..., Mapping[str, Any]]


class DeepMemoryEvidenceAdapter:
    """Read-only, policy-bounded Deep Memory historical-evidence consumer."""

    def __init__(
        self,
        transport: Transport,
        *,
        registry_path: Path = DEFAULT_REGISTRY,
        result_schema_path: Path = RESULT_SCHEMA,
    ) -> None:
        if not callable(transport):
            raise ValueError("transport must be callable")
        self._transport = transport
        self._registry = _strict_json(registry_path)
        self._schema = _strict_json(result_schema_path)
        Draft202012Validator.check_schema(self._schema)
        self._validator = Draft202012Validator(self._schema)
        self._provider = self._discover_provider(PROVIDER_ID)

    def _discover_provider(self, provider_id: str) -> dict[str, Any]:
        if self._registry.get("registry_id") != "VERA_EXTERNAL_EVIDENCE_PROVIDER_REGISTRY_V1":
            raise EvidenceContractError("unsupported external evidence provider registry")
        providers = self._registry.get("providers")
        if not isinstance(providers, list):
            raise EvidenceContractError("external evidence provider registry has no providers list")
        matches = [item for item in providers if item.get("provider_id") == provider_id]
        if len(matches) != 1:
            raise EvidenceContractError(f"expected exactly one provider entry for {provider_id}")
        provider = matches[0]
        if provider.get("provider_class") != "EXTERNAL_EVIDENCE_PROVIDER":
            raise EvidenceContractError("Deep Memory must not be registered as a workstream owner")
        if provider.get("operations") != [EVIDENCE_SEARCH]:
            raise EvidenceContractError("Deep Memory provider operation set must be EVIDENCE_SEARCH only")
        if provider.get("canonical_memory_transfer") is not False:
            raise EvidenceContractError("external evidence provider cannot transfer canonical memory")
        if provider.get("execution_authorized") is not False:
            raise EvidenceContractError("provider discovery cannot grant execution authority")
        if provider.get("runtime_install_authorized") is not False:
            raise EvidenceContractError("provider discovery cannot imply runtime installation")
        if provider.get("identity_keying") != "PROVENANCE_ONLY_NOT_RUNTIME_IDENTITY":
            raise EvidenceContractError("runtime provenance may not key Vera identity")
        return deepcopy(provider)

    @property
    def provider_binding(self) -> Mapping[str, Any]:
        return deepcopy(self._provider)

    def search(self, request: EvidenceSearchRequest) -> HistoricalEvidenceBatch:
        source = self._provider["source"]
        payload = {
            "operation": EVIDENCE_SEARCH,
            "query": request.query,
            "privacy_mode": request.privacy_mode,
            "authorized_privacy_scopes": list(request.authorized_privacy_scopes),
            "provider_source_binding": {
                "repository": source["repository"],
                "commit": source["source_merged_commit"],
                "bindings": deepcopy(source["bindings"]),
            },
        }
        if any(key in payload for key in FORBIDDEN_RUNTIME_IDENTITY_KEYS):
            raise EvidenceContractError("runtime provenance may not be used as Vera identity")

        raw = self._transport(**payload)
        if not isinstance(raw, Mapping):
            raise EvidenceContractError("Deep Memory transport must return a mapping")
        result = deepcopy(dict(raw))
        errors = sorted(self._validator.iter_errors(result), key=lambda error: list(error.path))
        if errors:
            detail = "; ".join(f"{list(error.path)}: {error.message}" for error in errors)
            raise EvidenceContractError(f"Deep Memory result schema validation failed: {detail}")

        if result["query"] != request.query:
            raise EvidenceContractError("provider changed the evidence-search query")
        if result["privacy_mode"] != request.privacy_mode:
            raise EvidenceAuthorizationError("provider changed the caller privacy mode")
        if result["count"] != len(result["results"]):
            raise EvidenceContractError("provider result count does not match results length")

        returned_scopes = tuple(result["authorized_privacy_scopes"])
        if len(returned_scopes) != len(set(returned_scopes)) or set(returned_scopes) != set(request.authorized_privacy_scopes):
            raise EvidenceAuthorizationError(
                "provider authorization scopes differ from exact caller authorization"
            )

        if request.privacy_mode == "AUTHORIZED_SCOPE_FILTER":
            allowed = set(request.authorized_privacy_scopes)
            for item in result["results"]:
                self._validate_item_privacy(item, allowed)

        return HistoricalEvidenceBatch(
            provider_id=PROVIDER_ID,
            operation=EVIDENCE_SEARCH,
            query=result["query"],
            retrieved_at=result["retrieved_at"],
            privacy_mode=result["privacy_mode"],
            authorized_privacy_scopes=returned_scopes,
            results=tuple(deepcopy(result["results"])),
        )

    @staticmethod
    def _validate_item_privacy(item: Mapping[str, Any], allowed: set[str]) -> None:
        scope = item.get("privacy_scope")
        if not isinstance(scope, str) or not scope or scope not in allowed:
            raise EvidenceAuthorizationError(
                f"historical evidence row {item.get('memory_id')!r} lacks exact authorized privacy scope"
            )
        for field_name in ("historical_canon_overlays", "amendments", "classification_corrections"):
            overlays = item.get(field_name, [])
            if not isinstance(overlays, list):
                raise EvidenceContractError(f"{field_name} must be a list when present")
            for overlay in overlays:
                if not isinstance(overlay, Mapping):
                    raise EvidenceContractError(f"{field_name} entries must be objects")
                overlay_scope = overlay.get("privacy_scope")
                if overlay_scope is not None and overlay_scope not in allowed:
                    raise EvidenceAuthorizationError(
                        f"{field_name} contains an unauthorized explicit privacy scope"
                    )


def prepare_historical_admission_review(
    item: Mapping[str, Any],
    *,
    authority_ref: str,
    receipt_ref: str,
) -> HistoricalAdmissionReview:
    """Build a review-only bridge record. This performs no current-memory write."""
    authority_ref = _required_text("authority_ref", authority_ref)
    receipt_ref = _required_text("receipt_ref", receipt_ref)
    if item.get("result_semantics") != "HISTORICAL_EVIDENCE_ONLY_NOT_CURRENT_MEMORY_OR_AUTHORITY":
        raise EvidenceContractError("only bounded historical-evidence rows may enter admission review")
    privacy_scope = item.get("privacy_scope")
    if not isinstance(privacy_scope, str) or not privacy_scope:
        raise EvidenceAuthorizationError("admission review requires an explicit privacy scope")
    source_ids = item.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids:
        raise EvidenceContractError("admission review requires preserved source_ids")

    return HistoricalAdmissionReview(
        operation=ADMISSION_REVIEW,
        authority_ref=authority_ref,
        receipt_ref=receipt_ref,
        memory_id=_required_text("memory_id", item.get("memory_id")),
        source_ids=tuple(source_ids),
        event_time=deepcopy(item.get("event_time")),
        recorded_at=item.get("recorded_at"),
        historical_canonicity=item.get("historical_canonicity"),
        privacy_scope=privacy_scope,
        provenance_ceiling=deepcopy(item.get("provenance_ceiling")),
        currentness_rule=deepcopy(item.get("currentness_rule")),
        historical_canon_overlays=tuple(deepcopy(item.get("historical_canon_overlays", []))),
        amendments=tuple(deepcopy(item.get("amendments", []))),
        classification_corrections=tuple(deepcopy(item.get("classification_corrections", []))),
    )
