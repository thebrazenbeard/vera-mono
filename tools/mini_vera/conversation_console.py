"""Usable opt-in local Mini-Vera console; reuses existing composer and shell.

This wrapper never starts/stops Ollama, downloads weights, imports memory,
installs services, invokes tools, or persists conversations. Preflight is a
bounded observation, not an exclusive host lease or weight attestation.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import local_session, loopback, ollama_preflight


def main(argv: list[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    if not args.check and not args.confirm_host_idle:
        print("Refused: real inference needs --confirm-host-idle after a fresh "
              "workload check.", file=sys.stderr)
        return 2
    try:
        receipt = ollama_preflight.probe(
            endpoint=args.endpoint, model=args.model,
            expected_tag_digest=args.expected_tag_digest,
            allow_cold_load=args.allow_cold_load,
        )
    except (ollama_preflight.PreflightRefused,
            loopback.LoopbackRejected, OSError, ValueError) as exc:
        print(f"Mini-Vera preflight refused: {exc}", file=sys.stderr)
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
    print("Mini-Vera local session: neural model not weight-attested; "
          "memory is volatile and tools remain disabled. "
          "Type /quit to leave.", file=sys.stderr)
    return local_session.main(options)


if __name__ == "__main__":
    raise SystemExit(main())
