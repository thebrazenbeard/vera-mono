"""Usable opt-in local Mini-Vera console; reuses existing composer and shell.

This wrapper never starts/stops Ollama, downloads weights, imports memory,
installs services, invokes tools, or persists conversations. Preflight is a
bounded observation, not an exclusive host lease or weight attestation.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from . import local_session, loopback, ollama_preflight


def main(argv: list[str] | None = None, *,
         live_public_provider: Callable[[], tuple[dict[str, Any], bytes, int]] | None = None,
         host_exact_record_id: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--model", default="qwen3.5:0.8b")
    parser.add_argument("--expected-tag-digest")
    parser.add_argument("--check", action="store_true",
                        help="Read-only Ollama and memory preflight; no model inference")
    parser.add_argument("--confirm-host-idle", action="store_true",
                        help="Explicit approval after checking current host workloads")
    parser.add_argument("--allow-cold-load", action="store_true",
                        help="Explicit approval to load the selected local model")
    parser.add_argument("--max-output-tokens", type=int, choices=(128, 256),
                        default=256)
    parser.add_argument("--timeout-seconds", type=int, choices=(30, 60),
                        default=60)
    parser.add_argument("--prompt",
                        help="Optional single-turn smoke; omit for interactive chat")
    parser.add_argument("--compact-dialogue", action="store_true",
                        help="Opt-in tested compact local conversation prompt; no persistent memory")
    parser.add_argument("--candidate-4b", action="store_true",
                        help="Experimental 2-3 GiB candidate with stronger RAM guard and explicit tag digest")
    args = parser.parse_args(argv)
    if host_exact_record_id is not None:
        # This opt-in is a trusted host PYTHON kwarg, not a CLI flag. A model
        # cannot choose a record or approve a ledger grant. The source-only
        # path must not probe, contact, start, or load an inference server.
        if (live_public_provider is None
                or args.prompt != host_exact_record_id
                or args.check or args.confirm_host_idle or args.allow_cold_load
                or args.compact_dialogue or args.candidate_4b
                or args.expected_tag_digest is not None
                or args.model != "qwen3.5:0.8b"):
            parser.error("embedded exact-source lookup requires matching "
                         "host record ID/provider and no model options")
        return local_session.main(
            ["--endpoint", args.endpoint, "--structured-output",
             "--prompt", host_exact_record_id],
            live_public_provider=live_public_provider,
            host_exact_record_id=host_exact_record_id)
    if live_public_provider is not None:
        parser.error("embedded live provider requires a host exact record ID")

    if args.candidate_4b and args.expected_tag_digest is None:
        print("Refused: candidate 4B requires --expected-tag-digest.", file=sys.stderr)
        return 2
    if args.candidate_4b and args.max_output_tokens != 128:
        print("Refused: candidate 4B caps --max-output-tokens at 128.", file=sys.stderr)
        return 2
    if not args.check and not args.confirm_host_idle:
        print("Refused: real inference needs --confirm-host-idle after a fresh "
              "workload check.", file=sys.stderr)
        return 2
    probe_options = dict(endpoint=args.endpoint, model=args.model,
                         expected_tag_digest=args.expected_tag_digest,
                         allow_cold_load=args.allow_cold_load)
    if args.candidate_4b:
        probe_options["allow_4b_candidate"] = True
    try:
        receipt = ollama_preflight.probe(**probe_options)
    except (ollama_preflight.PreflightRefused,
            loopback.LoopbackRejected, OSError, ValueError) as exc:
        print(f"Mini-Vera preflight refused: {exc}", file=sys.stderr)
        return 2
    if args.candidate_4b and (
            receipt.get("schema") != "MINI_VERA_CANDIDATE4B_PREFLIGHT_V1"
            or receipt.get("model_class") != "CANDIDATE_4B_UNQUALIFIED"
            or type(receipt.get("model_size_bytes")) is not int
            or not (ollama_preflight.MAX_08B_MODEL_BYTES
                    < receipt["model_size_bytes"]
                    <= ollama_preflight.MAX_CANDIDATE4B_MODEL_BYTES)
            or receipt.get("ollama_tag_digest") != args.expected_tag_digest):
        print("Refused: candidate 4B preflight classification mismatch.", file=sys.stderr)
        return 2
    if args.check:
        print(json.dumps(receipt, sort_keys=True))
        return 0
    if (receipt.get("status") != "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE"
            or receipt.get("model") != args.model
            or not isinstance(receipt.get("ollama_tag_digest"), str)
            or loopback.HEX64.fullmatch(receipt["ollama_tag_digest"]) is None):
        print("Refused: model was not approved for local inference "
              "at the current resource snapshot.", file=sys.stderr)
        return 2

    # Retain the existing source-pinned, RAM-only two-exchange conversation
    # history in local_session. Do not invent another memory implementation.
    options = [
        "--endpoint", args.endpoint, "--model", args.model,
        "--model-digest", receipt["ollama_tag_digest"],
        "--execute", "--host-idle-confirmed", "--ollama-disable-thinking",
        "--max-output-tokens", str(args.max_output_tokens),
        "--timeout-seconds", str(args.timeout_seconds),
    ]
    if args.prompt is not None:
        options += ["--prompt", args.prompt]
    if args.compact_dialogue:
        options.append("--compact-dialogue")
    if args.candidate_4b:
        # Second bounded GET inventory and RAM probe immediately before handoff.
        # This is TOCTOU mitigation, NOT an exclusive lease or tensor proof.
        try:
            final = ollama_preflight.probe(**probe_options)
        except (ollama_preflight.PreflightRefused,
                loopback.LoopbackRejected, OSError, ValueError) as exc:
            print(f"Refused: candidate 4B pre-handoff recheck: {exc}", file=sys.stderr)
            return 2
        if (final.get("status") != "RESOURCE_PREFLIGHT_PASSED_NOT_A_LEASE"
                or final.get("schema") != receipt["schema"]
                or final.get("model_class") != receipt["model_class"]
                or final.get("model") != receipt["model"]
                or final.get("model_size_bytes") != receipt["model_size_bytes"]
                or final.get("ollama_tag_digest") != receipt["ollama_tag_digest"]):
            print("Refused: candidate 4B residency or digest changed before handoff.",
                  file=sys.stderr)
            return 2
    print("Mini-Vera local session: neural model not weight-attested; "
          "memory is volatile and tools remain disabled. "
          "Type /quit to leave.", file=sys.stderr)
    return local_session.main(options)


if __name__ == "__main__":
    raise SystemExit(main())
