"""Opt-in trusted-host bridge from an existing public MemoryLedger to Mini-Vera.

No default approval, key generation, ledger mutation, private memory, or CLI
policy bypass. The caller is responsible for independently anchored ledger
head/revision and a current host authorization callback; a stored PUBLIC label
alone is explicitly insufficient. The provider is re-evaluated for every turn.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from .ledger_bridge import project_existing_ledger

if TYPE_CHECKING:
    from vera_memory import MemoryLedger, MemoryRecord


def approved_ledger_provider(
    ledger: "MemoryLedger", *, record_ids: Sequence[str],
    expected_head: str, expected_revision: int, integrity_key: bytes,
    host_public_project_approval: Callable[["MemoryRecord", str], bool],
) -> Callable[[], tuple[dict[str, Any], bytes, int]]:
    """Bind an externally approved public-only snapshot for rechecking per turn.

    The returned callable is intended for ``local_session.main``'s
    ``live_public_provider`` argument. A changed head fails closed; a trusted
    host must provide a NEW approval/anchor before resuming.
    """
    selected_ids = tuple(record_ids)

    def resolve() -> tuple[dict[str, Any], bytes, int]:
        state, _receipt = project_existing_ledger(
            ledger, record_ids=selected_ids, expected_head=expected_head,
            expected_revision=expected_revision, integrity_key=integrity_key,
            host_public_project_approval=host_public_project_approval,
        )
        return state, integrity_key, expected_revision

    return resolve
