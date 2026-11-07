"""Read-only Windows Mini-Vera launch readiness display; never starts a model.

This operational view distinguishes a point-in-time resource estimate from a
host-owned exclusive lease. There is no production lease provider in this CLI.
Use the separate opt-in `ollama_preflight` entry point for actual inference.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from . import loopback, ollama_preflight


SCHEMA = "MINI_VERA_WINDOWS_READINESS_V1"


def assess(*, endpoint: str = ollama_preflight.DEFAULT_ENDPOINT,
           model: str = ollama_preflight.DEFAULT_MODEL,
           expected_tag_digest: str | None = None,
           probe: Callable[..., dict[str, Any]] = ollama_preflight.probe) -> dict[str, Any]:
    """Observe host resources; unconditionally refuse launch authority."""
    try:
        sample = probe(endpoint=endpoint, model=model,
                       expected_tag_digest=expected_tag_digest,
                       allow_cold_load=False)
    except (ollama_preflight.PreflightRefused, loopback.LoopbackRejected) as exc:
        return {
            "schema": SCHEMA, "status": "RESOURCE_REFUSED", "reason": str(exc),
            "model": model, "host_lease": "NOT_BOUND", "launch_allowed": False,
            "model_inference_calls": 0,
            "cpu_disk_workload_qualification": "NOT_PERFORMED",
        }
    resource_state = sample["status"]
    if resource_state == "COLD_MODEL_NOT_AUTHORIZED_TO_LOAD":
        status = "COLD_MODEL_NOT_AUTHORIZED"
    elif resource_state == "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE":
        status = "RESOURCE_OBSERVED_NO_HOST_LEASE"
    else:
        return {
            "schema": SCHEMA, "status": "UNKNOWN_PREFLIGHT_STATUS",
            "model": model, "host_lease": "NOT_BOUND", "launch_allowed": False,
            "model_inference_calls": 0,
            "cpu_disk_workload_qualification": "NOT_PERFORMED",
        }
    return {
        "schema": SCHEMA, "status": status, "model": model,
        "model_resident": sample["model_resident"],
        "model_size_bytes": sample["model_size_bytes"],
        "available_physical_ram_bytes": sample["available_physical_ram_bytes"],
        "required_physical_ram_bytes": sample["required_physical_ram_bytes"],
        "ollama_tag_digest": sample["ollama_tag_digest"],
        "model_digest_evidence": "SERVER_DECLARED_NOT_WEIGHT_ATTESTATION",
        "identity_provenance": sample["identity_provenance"],
        "host_lease": "NOT_BOUND", "launch_allowed": False,
        "model_inference_calls": 0,
        "cpu_disk_workload_qualification": "NOT_PERFORMED",
    }


def main(argv: list[str] | None = None, *,
         probe: Callable[..., dict[str, Any]] = ollama_preflight.probe) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=ollama_preflight.DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=ollama_preflight.DEFAULT_MODEL)
    parser.add_argument("--expected-tag-digest")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = assess(endpoint=args.endpoint, model=args.model,
                    expected_tag_digest=args.expected_tag_digest, probe=probe)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"Mini-Vera Windows readiness: {result['status']}")
        if "reason" in result:
            print(f"Refusal: {result['reason']}")
        elif "available_physical_ram_bytes" in result:
            free = result["available_physical_ram_bytes"] / ollama_preflight.GIB
            needed = result["required_physical_ram_bytes"] / ollama_preflight.GIB
            print(f"Observed RAM: {free:.2f} GiB free; estimated minimum {needed:.2f} GiB")
            print(f"Selected Ollama model resident: {result['model_resident']}")
        print("Host-owned exclusive lease: NOT BOUND")
        print("CPU/disk workload qualification: NOT PERFORMED")
        print("Launch authority: NONE; this display never runs inference")
    return 2 if result["status"] in {"RESOURCE_REFUSED", "UNKNOWN_PREFLIGHT_STATUS"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
