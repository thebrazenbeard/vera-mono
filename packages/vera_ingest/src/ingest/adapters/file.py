from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from ..model import Acquisition, FileSource, SourceRef, StreamingAcquisition, now_iso
from ..policy import IngestPolicy
from .base import AcquisitionFailed, PolicyRejected


class FileAdapter:
    name = "file"
    version = "1"

    def supports(self, source) -> bool:
        return isinstance(source, FileSource)

    @staticmethod
    def _media_type(resolved: Path) -> str | None:
        suffix = resolved.suffix.lower()
        if suffix == ".json":
            return "application/json"
        if suffix in {".jsonl", ".ndjson"}:
            return "application/x-ndjson"
        media_type, _ = mimetypes.guess_type(resolved.name)
        return media_type

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

    @staticmethod
    def _identity_signature(value) -> tuple[int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_size,
            value.st_mtime_ns,
        )

    @classmethod
    def _stability_signature(cls, value) -> tuple[int, int, int, int, int]:
        return (*cls._identity_signature(value), value.st_ctime_ns)

    def _iter_bound_file(
        self,
        resolved: Path,
        *,
        expected_stat,
        policy: IngestPolicy,
    ):
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if not policy.follow_symlinks:
            flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(resolved, flags)
        except OSError as exc:
            raise AcquisitionFailed(f"file open failed: {resolved}") from exc

        observed_bytes = 0
        try:
            opened_stat = os.fstat(fd)
            if self._identity_signature(opened_stat) != self._identity_signature(expected_stat):
                raise AcquisitionFailed("file identity changed before acquisition")

            while True:
                chunk = os.read(fd, 64 * 1024)
                if not chunk:
                    break
                observed_bytes += len(chunk)
                if observed_bytes > policy.max_bytes:
                    raise PolicyRejected(
                        f"file exceeds max_bytes={policy.max_bytes}"
                    )
                yield chunk

            final_stat = os.fstat(fd)
            if self._stability_signature(final_stat) != self._stability_signature(opened_stat):
                raise AcquisitionFailed("file changed during acquisition")
            if observed_bytes != opened_stat.st_size:
                raise AcquisitionFailed("file size changed during acquisition")
        except (AcquisitionFailed, PolicyRejected):
            raise
        except OSError as exc:
            raise AcquisitionFailed(f"file read failed: {resolved}") from exc
        finally:
            os.close(fd)

    def _read_bound_file(
        self,
        resolved: Path,
        *,
        expected_stat,
        policy: IngestPolicy,
    ) -> tuple[bytes, object]:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if not policy.follow_symlinks:
            flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(resolved, flags)
        except OSError as exc:
            raise AcquisitionFailed(f"file open failed: {resolved}") from exc

        try:
            opened_stat = os.fstat(fd)
            if self._identity_signature(opened_stat) != self._identity_signature(expected_stat):
                raise AcquisitionFailed("file identity changed before acquisition")

            chunks: list[bytes] = []
            remaining = policy.max_bytes + 1
            while remaining > 0:
                chunk = os.read(fd, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > policy.max_bytes:
                raise PolicyRejected(f"file exceeds max_bytes={policy.max_bytes}")

            final_stat = os.fstat(fd)
            if self._stability_signature(final_stat) != self._stability_signature(opened_stat):
                raise AcquisitionFailed("file changed during acquisition")
            if len(data) != opened_stat.st_size:
                raise AcquisitionFailed("file size changed during acquisition")
            return data, opened_stat
        except OSError as exc:
            raise AcquisitionFailed(f"file read failed: {resolved}") from exc
        finally:
            os.close(fd)

    def acquire_stream(
        self,
        source: FileSource,
        policy: IngestPolicy,
    ) -> StreamingAcquisition:
        path = Path(source.path).expanduser()
        if not path.exists() or not path.is_file():
            raise AcquisitionFailed(f"file not found: {path}")
        if not policy.follow_symlinks and self._has_link_component(path):
            raise PolicyRejected("symlink/junction input is disabled by policy")
        resolved = path.resolve(strict=True)
        if policy.allowed_roots:
            roots = tuple(
                Path(root).expanduser().resolve(strict=True)
                for root in policy.allowed_roots
            )
            if not any(self._within(resolved, root) for root in roots):
                raise PolicyRejected("file resolves outside allowed_roots")
        expected_stat = resolved.stat()
        if expected_stat.st_size > policy.max_bytes:
            raise PolicyRejected(
                f"file exceeds max_bytes={policy.max_bytes}"
            )
        return StreamingAcquisition(
            chunks=self._iter_bound_file(
                resolved,
                expected_stat=expected_stat,
                policy=policy,
            ),
            source=SourceRef(
                scheme="file",
                locator=str(resolved),
                adapter=self.name,
                adapter_version=self.version,
                observed_at=now_iso(),
                source_identity={"resolved_path": str(resolved)},
                observed_metadata={"size_bytes": expected_stat.st_size},
            ),
            claimed_media_type=self._media_type(resolved),
        )

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
        expected_stat = resolved.stat()
        if expected_stat.st_size > policy.max_bytes:
            raise PolicyRejected(f"file exceeds max_bytes={policy.max_bytes}")
        data, opened_stat = self._read_bound_file(
            resolved,
            expected_stat=expected_stat,
            policy=policy,
        )
        media_type = self._media_type(resolved)
        return Acquisition(
            data=data,
            source=SourceRef(
                scheme="file",
                locator=str(resolved),
                adapter=self.name,
                adapter_version=self.version,
                observed_at=now_iso(),
                source_identity={"resolved_path": str(resolved)},
                observed_metadata={"size_bytes": opened_stat.st_size},
            ),
            claimed_media_type=media_type,
        )
