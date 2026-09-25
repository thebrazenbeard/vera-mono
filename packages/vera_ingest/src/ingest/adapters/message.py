from __future__ import annotations

from ..canonical import canonical_json
from ..model import Acquisition, MessageSource, SourceRef, now_iso
from ..policy import IngestPolicy
from .base import PolicyRejected


class MessageAdapter:
    name = "message"
    version = "1"

    def supports(self, source) -> bool:
        return isinstance(source, MessageSource)

    def acquire(self, source: MessageSource, policy: IngestPolicy) -> Acquisition:
        try:
            data = canonical_json(dict(source.payload)).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise PolicyRejected("message payload must be strict JSON data") from exc
        if len(data) > policy.max_bytes:
            raise PolicyRejected(f"message exceeds max_bytes={policy.max_bytes}")
        claimed = {"event_time": source.event_time} if source.event_time is not None else {}
        return Acquisition(
            data=data,
            source=SourceRef(
                scheme="message",
                locator=f"{source.source}:{source.message_id}",
                adapter=self.name,
                adapter_version=self.version,
                observed_at=now_iso(),
                source_identity={"source": source.source, "message_id": source.message_id},
                claimed_metadata=claimed,
                observed_metadata={"ingestion_time_semantics": "OBSERVATION_TIME_NOT_EVENT_TIME"},
            ),
            claimed_media_type="application/json",
        )
