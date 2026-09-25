from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .canonical import canonical_digest


@dataclass(frozen=True, slots=True)
class IngestPolicy:
    max_bytes: int = 10 * 1024 * 1024
    allow_http: bool = False
    deny_private_networks: bool = True
    max_redirects: int = 3
    timeout_seconds: float = 15.0
    allowed_roots: tuple[str, ...] = ()
    follow_symlinks: bool = False

    def validate(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if any(not root for root in self.allowed_roots):
            raise ValueError("allowed_roots cannot contain empty paths")
        if any(not Path(root).expanduser().is_absolute() for root in self.allowed_roots):
            raise ValueError("allowed_roots must be absolute paths")

    @property
    def policy_id(self) -> str:
        self.validate()
        return canonical_digest(
            {
                "schema": "INGEST_POLICY_V1",
                "max_bytes": self.max_bytes,
                "allow_http": self.allow_http,
                "deny_private_networks": self.deny_private_networks,
                "max_redirects": self.max_redirects,
                "timeout_seconds": self.timeout_seconds,
                "allowed_roots": list(self.allowed_roots),
                "follow_symlinks": self.follow_symlinks,
            }
        )
