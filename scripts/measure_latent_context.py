from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
for relative in (
    "packages/vera_core/src",
    "packages/vera_ingest/src",
    "packages/rezon/src",
    "packages/portfolio_runtime/src",
    "packages/vera_runtime/src",
    "packages/vera_identity/src",
    "packages/vera_coordination/src",
    "packages/vera_memory/src",
    "packages/vera_assurance/src",
    "packages/vera_pc_connection/src",
    "packages/vera_control/src",
    "packages/vera_recovery/src",
):
    sys.path.insert(0, str(ROOT / relative))

from runtime_cohesion import (
    ContextCandidate,
    LatentContextError,
    assemble_context,
)
from vera_memory import LatentBlock, LossClass, Resolution


SCHEMA = "VERA_MONO_LATENT_CONTEXT_MEASUREMENT_V1"
CLAIM_CEILING = "VERA_MANAGED_CONTEXT_ONLY_NOT_GPU_VRAM"


def _load_cases(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if type(payload) is not list or not payload:
        raise ValueError("measurement fixture must be a non-empty JSON list")
    if any(type(item) is not dict for item in payload):
        raise ValueError("measurement cases must be JSON objects")
    return payload


def _measure_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = case["case_id"]
    source = case["source"].encode("utf-8")
    representation = case["representation"].encode("utf-8")
    exactness_required = bool(case["exactness_required"])
    backing_available = bool(case["backing_available"])

    block = LatentBlock.create(
        source_refs=(f"fixture:{case_id}",),
        source_digest=sha256(source).hexdigest(),
        resolution=Resolution.L2_SEMANTIC_LATENT,
        codec_id="fixture-deterministic-compact",
        codec_version="1",
        representation=representation,
        loss_class=LossClass.LOSSY,
        exact_recoverable=True,
        provenance=("tests/fixtures/latent_context_cases.json",),
        created_at="2026-10-02T00:00:00Z",
    )

    def backing_loader(ref: str) -> bytes:
        if not backing_available:
            raise FileNotFoundError(f"backing unavailable for {ref}")
        return source

    try:
        receipt = assemble_context(
            (
                ContextCandidate(
                    block=block,
                    task_relevance=10,
                    exactness_required=exactness_required,
                ),
            ),
            active_budget_bytes=max(len(source), len(representation)) + 64,
            backing_loader=backing_loader,
        )
    except (LatentContextError, FileNotFoundError, KeyError) as error:
        if not exactness_required:
            raise
        return {
            "case_id": case_id,
            "status": "INSUFFICIENT_FIDELITY",
            "source_bytes": len(source),
            "representation_bytes": len(representation),
            "active_bytes": 0,
            "rehydration_count": 0,
            "rehydration_bytes": 0,
            "exact_recovered": False,
            "false_reconstruction": False,
            "reason": type(error).__name__,
        }

    if len(receipt.items) != 1:
        raise RuntimeError(f"fixture case {case_id!r} did not produce one context item")
    item = receipt.items[0]

    if exactness_required:
        exact_recovered = item.exact and item.content == source
        expected = case.get("expected_exact_fragment")
        if expected is not None:
            exact_recovered = exact_recovered and expected.encode("utf-8") in item.content
        status = "EXACT_REHYDRATED" if exact_recovered else "EXACT_RECOVERY_MISMATCH"
        false_reconstruction = not exact_recovered
    else:
        exact_recovered = False
        status = "COMPACT"
        false_reconstruction = False

    return {
        "case_id": case_id,
        "status": status,
        "source_bytes": len(source),
        "representation_bytes": len(representation),
        "active_bytes": receipt.active_bytes,
        "rehydration_count": receipt.rehydration_count,
        "rehydration_bytes": receipt.rehydration_bytes,
        "exact_recovered": exact_recovered,
        "false_reconstruction": false_reconstruction,
        "reason": None,
    }


def measure_cases(path: str | Path) -> dict[str, Any]:
    measured = [_measure_case(case) for case in _load_cases(path)]
    successful = [
        item
        for item in measured
        if item["status"] != "INSUFFICIENT_FIDELITY"
    ]
    failed_exact = [
        item
        for item in measured
        if item["status"] == "INSUFFICIENT_FIDELITY"
    ]
    source_bytes = sum(item["source_bytes"] for item in successful)
    active_bytes = sum(item["active_bytes"] for item in successful)
    return {
        "schema": SCHEMA,
        "claim_ceiling": CLAIM_CEILING,
        "case_count": len(measured),
        "successful_case_count": len(successful),
        "failed_exact_case_count": len(failed_exact),
        "false_reconstruction_count": sum(
            1 for item in measured if item["false_reconstruction"]
        ),
        "successful_source_bytes": source_bytes,
        "successful_active_bytes": active_bytes,
        "successful_context_reduction_ratio": (
            round(source_bytes / active_bytes, 6)
            if active_bytes
            else None
        ),
        "cases": measured,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure Vera-managed multi-resolution context behavior."
    )
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = measure_cases(args.fixture)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(text, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
