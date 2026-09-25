from __future__ import annotations

import mimetypes
from pathlib import Path

from ..model import Acquisition, FileSource, SourceRef, now_iso
from ..policy import IngestPolicy
from .base import AcquisitionFailed, PolicyRejected


class FileAdapter:
    name = "file"
    version = "1"

    def supports(self, source) -> bool:
        return isinstance(source, FileSource)

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _has_link_component(path: Path) -> bool:
        absolute = path.absolute()
        for component in (absolute, *absolute.parents):
            if component.is_symlink():
                return True
            is_junction = getattr(component, "is_junction", None)
            if is_junction is not None and is_junction():
                return True
        return False

    def acquire(self, source: FileSource, policy: IngestPolicy) -> Acquisition:
        path = Path(source.path).expanduser()
        if not path.exists() or not path.is_file():
            raise AcquisitionFailed(f"file not found: {path}")
        if not policy.follow_symlinks and self._has_link_component(path):
            raise PolicyRejected("symlink/junction input is disabled by policy")
        resolved = path.resolve(strict=True)
        if policy.allowed_roots:
            roots = tuple(Path(root).expanduser().resolve(strict=True) for root in policy.allowed_roots)
            if not any(self._within(resolved, root) for root in roots):
                raise PolicyRejected("file resolves outside allowed_roots")
        size = resolved.stat().st_size
        if size > policy.max_bytes:
            raise PolicyRejected(f"file exceeds max_bytes={policy.max_bytes}")
        data = resolved.read_bytes()
        if len(data) > policy.max_bytes:
            raise PolicyRejected(f"file exceeds max_bytes={policy.max_bytes}")
        if len(data) != size:
            raise AcquisitionFailed("file size changed during acquisition")
        suffix = resolved.suffix.lower()
        if suffix == ".json":
            media_type = "application/json"
        elif suffix in {".jsonl", ".ndjson"}:
            media_type = "application/x-ndjson"
        else:
            media_type, _ = mimetypes.guess_type(resolved.name)
        return Acquisition(
            data=data,
            source=SourceRef(
                scheme="file",
                locator=str(resolved),
                adapter=self.name,
                adapter_version=self.version,
                observed_at=now_iso(),
                source_identity={"resolved_path": str(resolved)},
                observed_metadata={"size_bytes": size},
            ),
            claimed_media_type=media_type,
        )
