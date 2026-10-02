from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Callable

from vera_memory import LatentBlock, LossClass, Resolution


class LatentContextError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RehydrationRequest:
    request_id: str
    block_id: str
    requested_resolution: Resolution
    exactness_required: bool
    reason: str
    requester: str
    resource_budget: int

    def validate(self) -> None:
        for value, label in (
            (self.request_id, "request_id"),
            (self.block_id, "block_id"),
            (self.reason, "reason"),
            (self.requester, "requester"),
        ):
            if type(value) is not str or not value:
                raise LatentContextError(f"{label} must be a non-empty exact string")
        if type(self.requested_resolution) is not Resolution:
            raise LatentContextError("requested_resolution must be an exact Resolution")
        if type(self.exactness_required) is not bool:
            raise LatentContextError("exactness_required must be an exact bool")
        if (
            type(self.resource_budget) is not int
            or isinstance(self.resource_budget, bool)
            or self.resource_budget < 0
        ):
            raise LatentContextError("resource_budget must be a non-negative exact int")


@dataclass(frozen=True, slots=True)
class RehydrationResult:
    request_id: str
    block_id: str
    source_ref: str
    resolution: Resolution
    content: bytes
    content_digest: str
    promoted_bytes: int
    exact: bool


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    block: LatentBlock
    task_relevance: int
    exactness_required: bool
    live_uncertainty: int = 0
    currentness_value: int = 0
    correction_value: int = 0

    def validate(self) -> None:
        if type(self.block) is not LatentBlock:
            raise LatentContextError("block must be an exact LatentBlock")
        self.block.validate()
        for value, label in (
            (self.task_relevance, "task_relevance"),
            (self.live_uncertainty, "live_uncertainty"),
            (self.currentness_value, "currentness_value"),
            (self.correction_value, "correction_value"),
        ):
            if type(value) is not int or isinstance(value, bool) or value < 0:
                raise LatentContextError(f"{label} must be a non-negative exact int")
        if type(self.exactness_required) is not bool:
            raise LatentContextError("exactness_required must be an exact bool")

    def sort_key(self) -> tuple[int, int, int, int, int, int, str]:
        self.validate()
        return (
            -int(self.exactness_required),
            -self.correction_value,
            -self.currentness_value,
            -self.task_relevance,
            -self.live_uncertainty,
            len(self.block.representation),
            self.block.block_id,
        )


@dataclass(frozen=True, slots=True)
class ContextItem:
    block_id: str
    source_ref: str
    resolution: Resolution
    content: bytes
    content_digest: str
    exact: bool
    bytes_used: int


@dataclass(frozen=True, slots=True)
class ContextAssemblyReceipt:
    items: tuple[ContextItem, ...]
    omitted_block_ids: tuple[str, ...]
    active_budget_bytes: int
    active_bytes: int
    rehydration_count: int
    rehydration_bytes: int
    claim_ceiling: str = "VERA_MANAGED_CONTEXT_ONLY_NOT_GPU_VRAM"


def _request_id(block: LatentBlock, remaining_budget: int) -> str:
    material = (
        f"{block.block_id}|{Resolution.L0_EXACT.value}|"
        f"{remaining_budget}|exact-context-promotion"
    ).encode("utf-8")
    return sha256(material).hexdigest()


def rehydrate_exact(
    block: LatentBlock,
    request: RehydrationRequest,
    *,
    backing_loader: Callable[[str], bytes],
) -> RehydrationResult:
    if type(block) is not LatentBlock:
        raise LatentContextError("block must be an exact LatentBlock")
    block.validate()
    if type(request) is not RehydrationRequest:
        raise LatentContextError("request must be an exact RehydrationRequest")
    request.validate()
    if request.block_id != block.block_id:
        raise LatentContextError("rehydration request block does not match latent block")
    if request.requested_resolution is not Resolution.L0_EXACT:
        raise LatentContextError("exact rehydration requires L0_EXACT")
    if not request.exactness_required:
        raise LatentContextError("exact rehydration requires exactness_required")
    if not block.exact_recoverable:
        raise LatentContextError("latent block has no verified exact recovery route")
    if not callable(backing_loader):
        raise LatentContextError("backing_loader must be callable")

    source_ref = block.source_refs[0]
    content = backing_loader(source_ref)
    if type(content) is not bytes:
        raise LatentContextError("backing loader must return exact bytes")
    digest = sha256(content).hexdigest()
    if digest != block.source_digest:
        raise LatentContextError("source digest mismatch during exact rehydration")
    if len(content) > request.resource_budget:
        raise LatentContextError("active budget exceeded during exact rehydration")

    return RehydrationResult(
        request_id=request.request_id,
        block_id=block.block_id,
        source_ref=source_ref,
        resolution=Resolution.L0_EXACT,
        content=content,
        content_digest=digest,
        promoted_bytes=len(content),
        exact=True,
    )


def _compact_item(block: LatentBlock) -> ContextItem:
    content = block.representation
    exact = (
        block.resolution is Resolution.L0_EXACT
        and block.loss_class is LossClass.LOSSLESS
        and block.representation_digest == block.source_digest
    )
    return ContextItem(
        block_id=block.block_id,
        source_ref=block.source_refs[0],
        resolution=block.resolution,
        content=content,
        content_digest=block.representation_digest,
        exact=exact,
        bytes_used=len(content),
    )


def assemble_context(
    candidates: tuple[ContextCandidate, ...],
    *,
    active_budget_bytes: int,
    backing_loader: Callable[[str], bytes],
) -> ContextAssemblyReceipt:
    if type(candidates) is not tuple:
        raise LatentContextError("candidates must be an exact tuple")
    if (
        type(active_budget_bytes) is not int
        or isinstance(active_budget_bytes, bool)
        or active_budget_bytes < 0
    ):
        raise LatentContextError("active_budget_bytes must be a non-negative exact int")
    if not callable(backing_loader):
        raise LatentContextError("backing_loader must be callable")

    for candidate in candidates:
        if type(candidate) is not ContextCandidate:
            raise LatentContextError("candidates must contain exact ContextCandidate values")
        candidate.validate()
    ids = [candidate.block.block_id for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise LatentContextError("candidate block ids must be unique")

    selected: list[ContextItem] = []
    omitted: list[str] = []
    active_bytes = 0
    rehydration_count = 0
    rehydration_bytes = 0

    for candidate in sorted(candidates, key=lambda item: item.sort_key()):
        block = candidate.block
        remaining = active_budget_bytes - active_bytes

        if candidate.exactness_required:
            request = RehydrationRequest(
                request_id=_request_id(block, remaining),
                block_id=block.block_id,
                requested_resolution=Resolution.L0_EXACT,
                exactness_required=True,
                reason="context candidate requires exact evidence",
                requester="runtime_cohesion.assemble_context",
                resource_budget=remaining,
            )
            result = rehydrate_exact(
                block,
                request,
                backing_loader=backing_loader,
            )
            item = ContextItem(
                block_id=block.block_id,
                source_ref=result.source_ref,
                resolution=result.resolution,
                content=result.content,
                content_digest=result.content_digest,
                exact=result.exact,
                bytes_used=result.promoted_bytes,
            )
            selected.append(item)
            active_bytes += item.bytes_used
            rehydration_count += 1
            rehydration_bytes += item.bytes_used
            continue

        item = _compact_item(block)
        if item.bytes_used > remaining:
            omitted.append(block.block_id)
            continue
        selected.append(item)
        active_bytes += item.bytes_used

    return ContextAssemblyReceipt(
        items=tuple(selected),
        omitted_block_ids=tuple(omitted),
        active_budget_bytes=active_budget_bytes,
        active_bytes=active_bytes,
        rehydration_count=rehydration_count,
        rehydration_bytes=rehydration_bytes,
    )
