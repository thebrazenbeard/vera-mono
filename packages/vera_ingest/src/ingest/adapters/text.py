from __future__ import annotations

from ..model import Acquisition, BytesSource, SourceRef, TextSource, now_iso
from ..policy import IngestPolicy
from .base import PolicyRejected


class TextBytesAdapter:
    name = "text-bytes"
    version = "1"

    def supports(self, source) -> bool:
        return isinstance(source, (TextSource, BytesSource))

    def acquire(self, source, policy: IngestPolicy) -> Acquisition:
        if isinstance(source, TextSource):
            data = source.text.encode("utf-8")
            locator = source.locator
            media_type = "text/plain"
            scheme = "text"
        else:
            data = source.data
            locator = source.locator
            media_type = source.media_type
            scheme = "bytes"
        if len(data) > policy.max_bytes:
            raise PolicyRejected(f"payload exceeds max_bytes={policy.max_bytes}")
        return Acquisition(
            data=data,
            source=SourceRef(
                scheme=scheme,
                locator=locator,
                adapter=self.name,
                adapter_version=self.version,
                observed_at=now_iso(),
                source_identity={"locator": locator},
            ),
            claimed_media_type=media_type,
        )
