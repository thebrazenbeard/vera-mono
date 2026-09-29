from __future__ import annotations

from dataclasses import replace
import uuid

from .adapters import FileAdapter, GitHubAdapter, HttpAdapter, MessageAdapter, TextBytesAdapter
from .adapters.base import AcquisitionFailed, PolicyRejected
from .canonical import canonical_digest
from .model import (
    Derivation,
    EvidenceClass,
    IngestRecord,
    IngestResult,
    IngestStatus,
    StageReceipt,
    now_iso,
)
from .normalization import NORMALIZER_VERSION, NormalizationError, normalize_bytes, sniff_media_type
from .policy import IngestPolicy
from .storage import FileSystemStore, StoreConflict


class Ingestor:
    def __init__(self, store: FileSystemStore, adapters=None):
        self.store = store
        self.adapters = list(adapters or [TextBytesAdapter(), FileAdapter(), HttpAdapter(), GitHubAdapter(), MessageAdapter()])

    def _adapter(self, source):
        for adapter in self.adapters:
            if adapter.supports(source):
                return adapter
        raise TypeError(f"no adapter registered for source type {type(source).__name__}")

    def _receipt(
        self,
        *,
        ingest_id: str | None,
        stage: str,
        outcome: str,
        input_ids=(),
        output_ids=(),
        details=None,
    ) -> StageReceipt:
        receipt_id = f"r_{uuid.uuid4().hex}"
        body = StageReceipt(
            receipt_id=receipt_id,
            ingest_id=ingest_id,
            stage=stage,
            stage_version="1",
            issued_at=now_iso(),
            outcome=outcome,
            input_artifact_ids=tuple(input_ids),
            output_artifact_ids=tuple(output_ids),
            details=details or {},
        )
        receipt = replace(body, receipt_digest=canonical_digest(body.body()))
        self.store.put_receipt(receipt.receipt_id, receipt.to_dict())
        return receipt

    def _result_from_existing(
        self,
        *,
        ingest_id,
        acquisition,
        raw_artifact,
        receipt_ids,
        warnings,
        existing,
    ) -> IngestResult:
        existing_status = IngestStatus(existing["status"])
        result_status = (
            IngestStatus.DUPLICATE
            if existing_status is IngestStatus.ACCEPTED
            else existing_status
        )
        duplicate = self._receipt(
            ingest_id=ingest_id,
            stage="duplicate_check",
            outcome=(
                "DUPLICATE"
                if result_status is IngestStatus.DUPLICATE
                else f"DUPLICATE_{existing_status.value}"
            ),
            input_ids=(raw_artifact.artifact_id,),
            details={"existing_status": existing_status.value},
        )
        receipt_ids.append(duplicate.receipt_id)
        normalized = existing.get("normalized_artifact")
        normalized_artifact = None
        if normalized is not None:
            from .model import Artifact
            normalized_artifact = Artifact(**normalized)
        if result_status is not IngestStatus.DUPLICATE:
            warnings.append("duplicate_existing_record")
        return IngestResult(
            ingest_id,
            result_status,
            source=acquisition.source,
            raw_artifact=raw_artifact,
            normalized_artifact=normalized_artifact,
            receipt_ids=tuple(receipt_ids),
            warnings=tuple(warnings),
            error=existing.get("error"),
        )

    @staticmethod
    def _record_semantics(value: dict) -> dict:
        source = value.get("source") or {}
        return {
            "schema": value.get("schema"),
            "ingest_id": value.get("ingest_id"),
            "source": {
                "scheme": source.get("scheme"),
                "locator": source.get("locator"),
                "adapter": source.get("adapter"),
                "adapter_version": source.get("adapter_version"),
                "source_identity": source.get("source_identity"),
            },
            "raw_artifact": value.get("raw_artifact"),
            "normalized_artifact": value.get("normalized_artifact"),
            "status": value.get("status"),
            "evidence_class": value.get("evidence_class"),
            "normalizer_version": value.get("normalizer_version"),
            "policy_id": value.get("policy_id"),
            "derivation_ids": value.get("derivation_ids"),
            "warnings": value.get("warnings"),
            "error": value.get("error"),
        }

    def _put_record_or_existing(self, record: IngestRecord):
        candidate = record.to_dict()
        try:
            created = self.store.put_record(record.ingest_id, candidate)
        except StoreConflict:
            existing = self.store.get_record(record.ingest_id)
            if self._record_semantics(existing) != self._record_semantics(candidate):
                raise
            return existing
        if created:
            return None
        existing = self.store.get_record(record.ingest_id)
        if self._record_semantics(existing) != self._record_semantics(candidate):
            raise StoreConflict(
                f"record at ingest_id={record.ingest_id} has conflicting semantics"
            )
        return existing

    def ingest(self, source, policy: IngestPolicy | None = None) -> IngestResult:
        policy = policy or IngestPolicy()
        policy.validate()
        receipt_ids: list[str] = []
        warnings: list[str] = []
        try:
            adapter = self._adapter(source)
            acquisition = adapter.acquire(source, policy)
        except PolicyRejected as exc:
            return IngestResult(None, IngestStatus.REJECTED, error=str(exc))
        except AcquisitionFailed as exc:
            return IngestResult(None, IngestStatus.FAILED, error=str(exc))

        acquire_receipt = self._receipt(
            ingest_id=None,
            stage="acquire",
            outcome="PASS",
            details={"source": acquisition.source.to_dict(), "size_bytes": len(acquisition.data)},
        )
        receipt_ids.append(acquire_receipt.receipt_id)

        if len(acquisition.data) > policy.max_bytes:
            receipt = self._receipt(
                ingest_id=None,
                stage="bounds",
                outcome="REJECTED",
                details={"max_bytes": policy.max_bytes, "observed_bytes": len(acquisition.data)},
            )
            receipt_ids.append(receipt.receipt_id)
            return IngestResult(
                None,
                IngestStatus.REJECTED,
                source=acquisition.source,
                receipt_ids=tuple(receipt_ids),
                error=f"payload exceeds max_bytes={policy.max_bytes}",
            )

        sniffed = sniff_media_type(acquisition.data)
        claimed = (
            acquisition.claimed_media_type.split(";", 1)[0].strip().lower()
            if acquisition.claimed_media_type
            else None
        )
        if claimed and claimed != sniffed:
            warnings.append(f"media_type_mismatch: claimed={claimed} sniffed={sniffed}")
        raw_media = sniffed
        raw_artifact, created = self.store.put_blob(
            acquisition.data, media_type=raw_media, kind="raw"
        )
        raw_receipt = self._receipt(
            ingest_id=None,
            stage="persist_raw",
            outcome="CREATED" if created else "EXISTS",
            output_ids=(raw_artifact.artifact_id,),
            details={"media_type": raw_media, "claimed_media_type": claimed},
        )
        receipt_ids.append(raw_receipt.receipt_id)

        identity = {
            "schema": "INGEST_IDENTITY_V1",
            "source": acquisition.source.identity_material(),
            "raw_sha256": raw_artifact.sha256,
            "claimed_media_type": claimed,
            "normalizer_version": NORMALIZER_VERSION,
            "policy_id": policy.policy_id,
        }
        ingest_id = canonical_digest(identity)

        if self.store.has_record(ingest_id):
            return self._result_from_existing(
                ingest_id=ingest_id,
                acquisition=acquisition,
                raw_artifact=raw_artifact,
                receipt_ids=receipt_ids,
                warnings=warnings,
                existing=self.store.get_record(ingest_id),
            )

        effective_media = claimed or sniffed
        if claimed in {"application/json", "text/json"} and sniffed != "application/json":
            error = "claimed structured JSON media type does not match parseable JSON content"
            receipt = self._receipt(
                ingest_id=ingest_id,
                stage="normalize",
                outcome="QUARANTINED",
                input_ids=(raw_artifact.artifact_id,),
                details={"error": error},
            )
            receipt_ids.append(receipt.receipt_id)
            record = IngestRecord(
                ingest_id=ingest_id,
                source=acquisition.source,
                raw_artifact=raw_artifact,
                normalized_artifact=None,
                status=IngestStatus.QUARANTINED,
                evidence_class=EvidenceClass.DIRECT_SOURCE,
                normalizer_version=NORMALIZER_VERSION,
                policy_id=policy.policy_id,
                receipt_ids=tuple(receipt_ids),
                warnings=tuple(warnings),
                error=error,
            )
            existing = self._put_record_or_existing(record)
            if existing is not None:
                return self._result_from_existing(
                    ingest_id=ingest_id,
                    acquisition=acquisition,
                    raw_artifact=raw_artifact,
                    receipt_ids=receipt_ids,
                    warnings=warnings,
                    existing=existing,
                )
            return IngestResult(
                ingest_id,
                IngestStatus.QUARANTINED,
                source=acquisition.source,
                raw_artifact=raw_artifact,
                receipt_ids=tuple(receipt_ids),
                warnings=tuple(warnings),
                error=error,
            )

        try:
            normalized_bytes = normalize_bytes(acquisition.data, effective_media)
        except NormalizationError as exc:
            receipt = self._receipt(
                ingest_id=ingest_id,
                stage="normalize",
                outcome="QUARANTINED",
                input_ids=(raw_artifact.artifact_id,),
                details={"error": str(exc)},
            )
            receipt_ids.append(receipt.receipt_id)
            record = IngestRecord(
                ingest_id=ingest_id,
                source=acquisition.source,
                raw_artifact=raw_artifact,
                normalized_artifact=None,
                status=IngestStatus.QUARANTINED,
                evidence_class=EvidenceClass.DIRECT_SOURCE,
                normalizer_version=NORMALIZER_VERSION,
                policy_id=policy.policy_id,
                receipt_ids=tuple(receipt_ids),
                warnings=tuple(warnings),
                error=str(exc),
            )
            existing = self._put_record_or_existing(record)
            if existing is not None:
                return self._result_from_existing(
                    ingest_id=ingest_id,
                    acquisition=acquisition,
                    raw_artifact=raw_artifact,
                    receipt_ids=receipt_ids,
                    warnings=warnings,
                    existing=existing,
                )
            return IngestResult(
                ingest_id,
                IngestStatus.QUARANTINED,
                source=acquisition.source,
                raw_artifact=raw_artifact,
                receipt_ids=tuple(receipt_ids),
                warnings=tuple(warnings),
                error=str(exc),
            )

        normalized_artifact = None
        derivation_ids: list[str] = []
        if normalized_bytes is not None:
            normalized_artifact, _ = self.store.put_blob(
                normalized_bytes, media_type=effective_media, kind="normalized"
            )
            receipt = self._receipt(
                ingest_id=ingest_id,
                stage="normalize",
                outcome="PASS",
                input_ids=(raw_artifact.artifact_id,),
                output_ids=(normalized_artifact.artifact_id,),
                details={"normalizer_version": NORMALIZER_VERSION, "media_type": effective_media},
            )
            receipt_ids.append(receipt.receipt_id)
            if normalized_artifact.artifact_id != raw_artifact.artifact_id:
                derivation_id = canonical_digest(
                    {
                        "relation": "NORMALIZED_FROM",
                        "parent": raw_artifact.artifact_id,
                        "child": normalized_artifact.artifact_id,
                        "normalizer_version": NORMALIZER_VERSION,
                    }
                )
                derivation = Derivation(
                    derivation_id=derivation_id,
                    relation="NORMALIZED_FROM",
                    parent_artifact_id=raw_artifact.artifact_id,
                    child_artifact_id=normalized_artifact.artifact_id,
                    receipt_id=receipt.receipt_id,
                )
                try:
                    self.store.put_derivation(derivation_id, derivation.to_dict())
                except StoreConflict:
                    existing_derivation = self.store.get_derivation(derivation_id)
                    if (
                        existing_derivation.get("relation") != derivation.relation
                        or existing_derivation.get("parent_artifact_id")
                        != derivation.parent_artifact_id
                        or existing_derivation.get("child_artifact_id")
                        != derivation.child_artifact_id
                    ):
                        raise
                derivation_ids.append(derivation_id)
        else:
            receipt = self._receipt(
                ingest_id=ingest_id,
                stage="normalize",
                outcome="SKIPPED_OPAQUE",
                input_ids=(raw_artifact.artifact_id,),
                details={"media_type": effective_media},
            )
            receipt_ids.append(receipt.receipt_id)

        record_ready = self._receipt(
            ingest_id=ingest_id,
            stage="record",
            outcome="READY",
            input_ids=(raw_artifact.artifact_id,),
            output_ids=(() if normalized_artifact is None else (normalized_artifact.artifact_id,)),
            details={
                "policy_id": policy.policy_id,
                "commit_semantics": "record_presence_commits_acceptance",
            },
        )
        receipt_ids.append(record_ready.receipt_id)
        record = IngestRecord(
            ingest_id=ingest_id,
            source=acquisition.source,
            raw_artifact=raw_artifact,
            normalized_artifact=normalized_artifact,
            status=IngestStatus.ACCEPTED,
            evidence_class=EvidenceClass.DIRECT_SOURCE,
            normalizer_version=NORMALIZER_VERSION,
            policy_id=policy.policy_id,
            receipt_ids=tuple(receipt_ids),
            derivation_ids=tuple(derivation_ids),
            warnings=tuple(warnings),
        )
        existing = self._put_record_or_existing(record)
        if existing is not None:
            return self._result_from_existing(
                ingest_id=ingest_id,
                acquisition=acquisition,
                raw_artifact=raw_artifact,
                receipt_ids=receipt_ids,
                warnings=warnings,
                existing=existing,
            )
        return IngestResult(
            ingest_id,
            IngestStatus.ACCEPTED,
            source=acquisition.source,
            raw_artifact=raw_artifact,
            normalized_artifact=normalized_artifact,
            receipt_ids=tuple(receipt_ids),
            derivation_ids=tuple(derivation_ids),
            warnings=tuple(warnings),
        )

    def ingest_many(self, sources, policy: IngestPolicy | None = None) -> list[IngestResult]:
        return [self.ingest(source, policy=policy) for source in sources]
