"""Preserve raw sequence order while making acquisition defects explicit."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class SequenceFlag(str, Enum):
    GAP = "GAP"
    DUPLICATE = "DUPLICATE"
    REORDERED = "REORDERED"
    OVERRUN = "OVERRUN"


@dataclass(frozen=True)
class SequenceSample:
    sequence: int
    overrun: bool = False

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("sequence must be a non-negative integer")


@dataclass(frozen=True)
class SequenceAssessment:
    raw_arrival_order: tuple[int, ...]
    flags: frozenset[SequenceFlag]
    continuity_segments: tuple[tuple[int, ...], ...]


def assess_sequence(samples: Iterable[SequenceSample]) -> SequenceAssessment:
    raw_order: list[int] = []
    flags: set[SequenceFlag] = set()
    segments: list[tuple[int, ...]] = []
    current_segment: list[int] = []
    seen: set[int] = set()
    high_water: int | None = None

    for sample in samples:
        if not isinstance(sample, SequenceSample):
            raise TypeError("samples must contain SequenceSample values")

        sequence = sample.sequence
        raw_order.append(sequence)
        break_before = False

        if sample.overrun:
            flags.add(SequenceFlag.OVERRUN)
            break_before = True

        if high_water is not None:
            if sequence in seen:
                flags.add(SequenceFlag.DUPLICATE)
                break_before = True
            elif sequence < high_water:
                flags.add(SequenceFlag.REORDERED)
                break_before = True
            elif sequence > high_water + 1:
                flags.add(SequenceFlag.GAP)
                break_before = True

        if break_before and current_segment:
            segments.append(tuple(current_segment))
            current_segment = []
        current_segment.append(sequence)

        seen.add(sequence)
        if high_water is None or sequence > high_water:
            high_water = sequence

    if current_segment:
        segments.append(tuple(current_segment))

    return SequenceAssessment(
        raw_arrival_order=tuple(raw_order),
        flags=frozenset(flags),
        continuity_segments=tuple(segments),
    )

