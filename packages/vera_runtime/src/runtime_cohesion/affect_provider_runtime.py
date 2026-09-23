from __future__ import annotations

from threading import RLock
from typing import Any, Mapping

from .adapters import AdapterRegistry
from .affect_persistence import (
    AffectiveProviderRestoreBoundary,
    PersistenceRecordError,
    restore_host_from_state_row,
)
from .affect_scope import (
    _attest_affective_host_provider_current,
    _mark_provider_bound_atomic_writer,
)


_PROVIDER = "supabase"
_PROVIDER_PROJECT_ID = "klmbpaigzeguvnpccqzz"
_PROVIDER_TABLE = "public.vera_affective_runtime_state_v1"
_PROVIDER_ROUTE = "route:supabase"
_PROVIDER_SOURCE = f"supabase:{_PROVIDER_PROJECT_ID}/{_PROVIDER_TABLE}"
_ATOMIC_COMMIT_FUNCTION = "public.vera_affective_runtime_commit_v1(bigint,jsonb,jsonb)"

_COMPOSITION_LOCK = RLock()
_RUNTIME_PROVIDER_ADAPTER: Any | None = None


def _validate_runtime_provider_adapter(adapter: Any) -> None:
    expected = {
        "provider": _PROVIDER,
        "provider_project_id": _PROVIDER_PROJECT_ID,
        "provider_table": _PROVIDER_TABLE,
        "provider_route": _PROVIDER_ROUTE,
        "atomic_commit_function": _ATOMIC_COMMIT_FUNCTION,
    }
    for field, value in expected.items():
        if getattr(adapter, field, None) != value:
            raise ValueError(f"runtime affective provider adapter {field} mismatch")
    for method in ("probe", "read", "commit_affective_runtime"):
        if not callable(getattr(adapter, method, None)):
            raise ValueError(f"runtime affective provider adapter lacks {method}")


def _install_runtime_affective_provider_adapter(adapter: Any) -> None:
    """Install one fixed in-process affective provider composition.

    This hook remains useful for source-level provider/CAS integration tests, but
    hostile review established that a first-writer Python hook cannot authenticate
    provider origin. Exact strings, callable methods, one-shot installation, and
    omission from ``runtime_cohesion.__all__`` are composition constraints only.

    Therefore installing an adapter here MUST NOT, by itself, enable production
    ``ATOMIC_DURABLE`` status, CURRENT provider-state evidence, production commit
    schemas, or durable resume tokens. Those claims remain unavailable until an
    independently rooted external provider integration is installed and verified.
    """
    _validate_runtime_provider_adapter(adapter)
    global _RUNTIME_PROVIDER_ADAPTER
    with _COMPOSITION_LOCK:
        if _RUNTIME_PROVIDER_ADAPTER is None:
            _RUNTIME_PROVIDER_ADAPTER = adapter
            return
        if _RUNTIME_PROVIDER_ADAPTER is adapter:
            return
        raise RuntimeError("runtime affective provider composition is already installed and cannot be replaced")


def _reset_runtime_affective_provider_for_tests() -> None:
    """Private test isolation hook; never a production claimant operation."""
    global _RUNTIME_PROVIDER_ADAPTER
    with _COMPOSITION_LOCK:
        _RUNTIME_PROVIDER_ADAPTER = None


def _runtime_provider_adapter() -> Any:
    """Return the configured in-process adapter without promoting its origin."""
    with _COMPOSITION_LOCK:
        adapter = _RUNTIME_PROVIDER_ADAPTER
    if adapter is None:
        raise PersistenceRecordError(
            "runtime affective provider composition is not installed before claimant restore input"
        )
    _validate_runtime_provider_adapter(adapter)
    return adapter


def restore_current_affective_cycle(
    contract_text: str,
    binding: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    host_scope: str,
    expected_checkpoint_sha256: str,
    expected_resume_token: Mapping[str, Any],
    elapsed_seconds: float = 0.0,
) -> Any:
    """Restore through the configured provider-composition harness.

    The function retains the historical API name because it checks the candidate
    against what the configured adapter reports as its current frontier. That
    check is necessary for CAS/frontier mechanics, but the adapter's own origin is
    not independently authenticated by this source-only package.

    Consequently the returned cycle is explicitly NON_QUALIFYING_ATOMIC_TEST,
    never ATOMIC_DURABLE. It emits HISTORICAL rows, a TEST commit schema, and no
    durable resume token. This prevents either a caller winning first adapter
    installation or caller-reachable in-process attestation helpers from minting
    provider-authenticated provenance. A future production restore path requires
    an independently rooted external provider capability/configuration boundary.
    """
    from .affect_cycle import VeraAffectiveCycle

    adapter = _runtime_provider_adapter()
    boundary = AffectiveProviderRestoreBoundary(
        adapters=AdapterRegistry({_PROVIDER: adapter}),
        provider=_PROVIDER,
        provider_route=_PROVIDER_ROUTE,
        provider_source=_PROVIDER_SOURCE,
        provider_project_id=_PROVIDER_PROJECT_ID,
        provider_table=_PROVIDER_TABLE,
    )

    provider_adapter = boundary._provider_adapter()
    boundary._validate_resume_token(row, expected_resume_token)
    boundary._read_current_frontier(row, adapter=provider_adapter)
    host = restore_host_from_state_row(
        contract_text,
        binding,
        row,
        expected_host_scope=host_scope,
        elapsed_seconds=elapsed_seconds,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
    )

    state_version = row.get("state_version")
    if isinstance(state_version, bool) or not isinstance(state_version, int) or state_version < 1:
        raise PersistenceRecordError("durable state row requires a positive integer state_version")

    # These process-local marks preserve diagnostic consistency and allow the
    # replay-only host to enter the bounded non-qualifying harness. They are not
    # provider-origin authentication and affect_scope deliberately refuses to use
    # them as a production ATOMIC_DURABLE qualification predicate.
    attestation_token = object()
    _attest_affective_host_provider_current(
        host,
        host_scope=host_scope,
        state_version=state_version,
        attestation_token=attestation_token,
    )
    atomic_commit_writer = boundary._bind_atomic_commit_writer(provider_adapter, row)
    _mark_provider_bound_atomic_writer(
        atomic_commit_writer,
        host=host,
        host_scope=host_scope,
        state_version=state_version,
        attestation_token=attestation_token,
    )

    return VeraAffectiveCycle(
        host,
        host_scope=host_scope,
        atomic_commit_writer=atomic_commit_writer,
        initial_state_version=state_version + 1,
        non_qualifying_atomic_test_mode=True,
    )


__all__ = ["restore_current_affective_cycle"]
