from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from runtime_cohesion import ContextAssemblyReceipt, ContextItem
from vera_memory import LatentBlock, LossClass, Resolution


@dataclass(frozen=True, slots=True)
class LatentAssuranceFinding:
    code: str
    severity: str
    subject_id: str
    message: str


@dataclass(frozen=True, slots=True)
class LatentAssuranceReport:
    valid: bool
    findings: tuple[LatentAssuranceFinding, ...]
    checked_blocks: int
    claim_ceiling: str = "INTERNAL_ASSURANCE_NOT_INDEPENDENT_REVIEW"


def _finding(
    code: str,
    subject_id: str,
    message: str,
    *,
    severity: str = "ERROR",
) -> LatentAssuranceFinding:
    return LatentAssuranceFinding(
        code=code,
        severity=severity,
        subject_id=subject_id,
        message=message,
    )


def audit_latent_blocks(
    blocks: tuple[LatentBlock, ...],
) -> LatentAssuranceReport:
    findings: list[LatentAssuranceFinding] = []
    if type(blocks) is not tuple:
        return LatentAssuranceReport(
            valid=False,
            findings=(
                _finding(
                    "INVALID_BLOCK_COLLECTION",
                    "latent-blocks",
                    "blocks must be an exact tuple",
                ),
            ),
            checked_blocks=0,
        )

    seen: set[str] = set()
    for index, block in enumerate(blocks):
        subject = getattr(block, "block_id", f"index:{index}")
        if type(block) is not LatentBlock:
            findings.append(
                _finding(
                    "INVALID_BLOCK_TYPE",
                    str(subject),
                    "collection contains a non-LatentBlock value",
                )
            )
            continue

        if not block.source_refs:
            findings.append(
                _finding(
                    "SOURCE_DETACHED",
                    block.block_id,
                    "latent block has no bound source reference",
                )
            )
        else:
            try:
                block.validate()
            except ValueError as error:
                findings.append(
                    _finding(
                        "INVALID_BLOCK_INTEGRITY",
                        block.block_id,
                        str(error),
                    )
                )

        if block.block_id in seen:
            findings.append(
                _finding(
                    "DUPLICATE_BLOCK_ID",
                    block.block_id,
                    "latent block identity appears more than once",
                )
            )
        seen.add(block.block_id)

        if (
            block.resolution is Resolution.L0_EXACT
            and block.loss_class is LossClass.LOSSY
        ):
            findings.append(
                _finding(
                    "LOSSY_DECLARED_EXACT",
                    block.block_id,
                    "lossy representation cannot be declared at exact resolution",
                )
            )

        if (
            block.resolution is Resolution.L0_EXACT
            and block.loss_class is LossClass.LOSSLESS
            and block.representation_digest != block.source_digest
        ):
            findings.append(
                _finding(
                    "EXACT_SOURCE_MISMATCH",
                    block.block_id,
                    "L0 lossless representation does not match bound source digest",
                )
            )

    return LatentAssuranceReport(
        valid=not findings,
        findings=tuple(findings),
        checked_blocks=len(blocks),
    )


def _audit_item(
    item: ContextItem,
    block: LatentBlock | None,
) -> tuple[LatentAssuranceFinding, ...]:
    findings: list[LatentAssuranceFinding] = []
    if type(item.content) is not bytes:
        findings.append(
            _finding(
                "INVALID_CONTEXT_BYTES",
                item.block_id,
                "context item content is not exact bytes",
            )
        )
        return tuple(findings)

    observed_digest = sha256(item.content).hexdigest()
    if observed_digest != item.content_digest:
        findings.append(
            _finding(
                "CONTEXT_DIGEST_MISMATCH",
                item.block_id,
                "context item digest does not bind its content",
            )
        )
    if item.bytes_used != len(item.content):
        findings.append(
            _finding(
                "ITEM_BYTE_MISMATCH",
                item.block_id,
                "context item byte count does not match content length",
            )
        )
    if block is None:
        findings.append(
            _finding(
                "UNKNOWN_BLOCK",
                item.block_id,
                "context item does not bind a supplied latent block",
            )
        )
        return tuple(findings)

    if item.source_ref not in block.source_refs:
        findings.append(
            _finding(
                "SOURCE_REF_MISMATCH",
                item.block_id,
                "context item source reference is not bound by its latent block",
            )
        )

    if item.exact:
        if item.resolution is not Resolution.L0_EXACT:
            findings.append(
                _finding(
                    "EXACTNESS_LAUNDERING",
                    item.block_id,
                    "context item claims exactness outside L0_EXACT",
                )
            )
        if observed_digest != block.source_digest:
            findings.append(
                _finding(
                    "EXACT_SOURCE_MISMATCH",
                    item.block_id,
                    "exact context bytes do not match the bound source digest",
                )
            )

    return tuple(findings)


def audit_context_receipt(
    receipt: ContextAssemblyReceipt,
    blocks: tuple[LatentBlock, ...],
) -> LatentAssuranceReport:
    block_report = audit_latent_blocks(blocks)
    findings = list(block_report.findings)
    by_id = {
        block.block_id: block
        for block in blocks
        if type(block) is LatentBlock
    }

    if type(receipt) is not ContextAssemblyReceipt:
        findings.append(
            _finding(
                "INVALID_CONTEXT_RECEIPT",
                "context-receipt",
                "receipt must be an exact ContextAssemblyReceipt",
            )
        )
        return LatentAssuranceReport(
            valid=False,
            findings=tuple(findings),
            checked_blocks=block_report.checked_blocks,
        )

    active_sum = 0
    exact_items = 0
    for item in receipt.items:
        if type(item) is not ContextItem:
            findings.append(
                _finding(
                    "INVALID_CONTEXT_ITEM",
                    "context-receipt",
                    "receipt contains a non-ContextItem value",
                )
            )
            continue
        active_sum += item.bytes_used
        if item.exact:
            exact_items += 1
        findings.extend(_audit_item(item, by_id.get(item.block_id)))

    if active_sum != receipt.active_bytes:
        findings.append(
            _finding(
                "ACTIVE_BYTE_MISMATCH",
                "context-receipt",
                "active_bytes does not equal selected item bytes",
            )
        )
    if receipt.active_bytes > receipt.active_budget_bytes:
        findings.append(
            _finding(
                "ACTIVE_BUDGET_EXCEEDED",
                "context-receipt",
                "receipt exceeds its declared active budget",
            )
        )
    if receipt.rehydration_bytes > receipt.active_bytes:
        findings.append(
            _finding(
                "REHYDRATION_BYTE_MISMATCH",
                "context-receipt",
                "rehydration bytes exceed active bytes",
            )
        )
    if receipt.rehydration_count > exact_items:
        findings.append(
            _finding(
                "REHYDRATION_COUNT_MISMATCH",
                "context-receipt",
                "rehydration count exceeds exact context items",
            )
        )

    selected_ids = {item.block_id for item in receipt.items}
    omitted_ids = set(receipt.omitted_block_ids)
    if selected_ids.intersection(omitted_ids):
        findings.append(
            _finding(
                "SELECTED_OMITTED_OVERLAP",
                "context-receipt",
                "a block cannot be both selected and omitted",
            )
        )

    return LatentAssuranceReport(
        valid=not findings,
        findings=tuple(findings),
        checked_blocks=block_report.checked_blocks,
    )
