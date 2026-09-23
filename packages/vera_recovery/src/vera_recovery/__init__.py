"""Native vera-mono recovery/checkpoint primitives.

The legacy r8a0 package remains available as a compatibility surface. New
monorepo lifecycle code should use this package.
"""

from .native import (
    NativeCheckpointError,
    NativeRecoveryCheckpoint,
    NativeRecoveryCheckpointStore,
    StaleCheckpointHead,
)

__all__ = [
    "NativeCheckpointError",
    "NativeRecoveryCheckpoint",
    "NativeRecoveryCheckpointStore",
    "StaleCheckpointHead",
]
