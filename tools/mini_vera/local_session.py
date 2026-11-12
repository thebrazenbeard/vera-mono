"""Minimal local Vera conversation shell around the existing bounded composer.

This shell does not load model weights or start an inference server.  An
operator must separately qualify and start a local OpenAI-compatible server.
The process keeps only the last two exchange pairs in RAM.  It never archives
chat, admits memory, grants tool authority, or attests the server's weights.
"""

from __future__ import annotations

import argparse
import hmac
import json
from pathlib import Path
import secrets
import sys
from collections.abc import Callable
from typing import Any

from . import artifact_binding, compose, loopback

# Independently reviewed resource digests at the PR #201 source checkpoint.
# These are code-pinned expectations, NOT a signature or host installation
# attestation. Change them only with an explicitly reviewed source update.
PINNED_IDENTITY_SHA256 = "b7fdd42bfcea319c27b405339de580c2c37879e8a19d5c4642739ae855875e7f"
PINNED_BEHAVIOR_SHA256 = "ec1defa8fcf96371a427991d40695842ffe6794aeb2e3f26c69ef5f528ee7d6d"


def empty_public_state() -> tuple[dict[str, Any], bytes]:
    """A process-local empty state, not a substitute persistent memory store."""
    key = secrets.token_bytes(32)
    state = {"schema": "MINI_VERA_OPERATOR_STATE_V1", "revision": 0,
             "source_id": "local-ephemeral", "records": []}
    state["hmac_sha256"] = hmac.new(key, compose.canonical(state), "sha256").hexdigest()
    return state, key


def compose_local_turn(*, text: str, turn_id: str, history: list[dict[str, str]],
                       identity: dict[str, Any], identity_raw: bytes,
                       behavior: dict[str, Any], behavior_raw: bytes,
                       state: dict[str, Any], key: bytes, revision: int,
                       model: str | None = None, model_digest: str | None = None,
                       witness: Any | None = None,
                       num_predict: int = 128) -> dict[str, Any]:
    args = {
        "identity": identity, "identity_raw": identity_raw,
        "behavior": behavior, "behavior_raw": behavior_raw,
        "expected_identity_sha256": PINNED_IDENTITY_SHA256,
        "expected_behavior_sha256": PINNED_BEHAVIOR_SHA256,
        "state": state, "key": key, "expected_revision": revision,
        "turn": {"schema": "MINI_VERA_LOCAL_TURN_V1", "scope": "LOCAL_LOOPBACK_ONLY",
                 "turn_id": turn_id, "user_text": text},
        "session_history": history,
        "num_predict": num_predict,
    }
    if witness is not None:
        return artifact_binding.compose_from_witness(witness, **args)
    if model is None or model_digest is None:
        raise compose.CompositionRejected("model alias and declared digest required")
    return compose.compose(**args, model=model, model_digest=model_digest)


def main(argv: list[str] | None = None, *,
         live_public_provider: Callable[[], tuple[dict[str, Any], bytes, int]] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="Explicit numeric loopback /v1 endpoint")
    parser.add_argument("--model", help="Server model alias (operator-declared, not attested)")
    parser.add_argument("--model-digest", help="Operator-declared registry digest")
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--public-state", type=Path)
    parser.add_argument("--state-key-file", type=Path)
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--prompt", help="One local turn; omit for interactive --execute mode")
    parser.add_argument("--execute", action="store_true", help="Permit bounded local HTTP inference")
    parser.add_argument("--host-idle-confirmed", action="store_true",
                        help="Operator confirms host and model server resource qualification")
    parser.add_argument("--timeout-seconds", type=int, choices=(30, 60), default=30)
    parser.add_argument("--max-output-tokens", type=int, choices=(128, 256),
                        default=128, help="Bounded local generation budget")
    parser.add_argument("--ollama-disable-thinking", action="store_true",
                        help="Explicit Ollama-only /v1 reasoning_effort=none transport control")
    args = parser.parse_args(argv)

    # A validation-only invocation must never load a model through an HTTP call.
    loopback._endpoint(args.endpoint)
    if args.execute and not args.host_idle_confirmed:
        parser.error("--execute requires a fresh --host-idle-confirmed resource check")
    if not args.execute and args.prompt is None:
        parser.error("--prompt required for validation-only mode")
    use_manifest = any((args.model_root, args.manifest, args.manifest_sha256))
    if use_manifest:
        if (not all((args.model_root, args.manifest, args.manifest_sha256))
                or args.model or args.model_digest):
            parser.error("use one complete local manifest triple OR model and digest")
        witness = artifact_binding.open_local_witness(
            args.model_root, args.manifest, expected_manifest_sha256=args.manifest_sha256)
        model = digest = None
    else:
        if args.model is None or args.model_digest is None:
            parser.error("--model and --model-digest required without local manifest")
        model, digest, witness = args.model, args.model_digest, None
    if any((args.public_state, args.state_key_file, args.expected_revision is not None)):
        if live_public_provider is not None:
            parser.error("cannot mix a live public-memory provider with exported state files")
        if args.public_state is None or args.state_key_file is None or args.expected_revision is None:
            parser.error("public state requires key file and exact revision")
        state, _ = compose.read_object(args.public_state, compose.MAX_STATE_BYTES)
        key = args.state_key_file.read_bytes()
        revision = args.expected_revision
    else:
        state, key = empty_public_state()
        revision = 0
    if live_public_provider is None:
        compose.verify_state(state, key=key, expected_revision=revision)
    try:
        identity, identity_raw = compose.read_object(compose.IDENTITY_PATH, 16_384)
        behavior, behavior_raw = compose.read_object(compose.BEHAVIOR_PATH, 16_384)
        # Fail before any model HTTP request. Self-hashing the just-loaded files
        # would accept arbitrary identity drift as its own expected provenance.
        if compose.sha256(identity_raw) != PINNED_IDENTITY_SHA256:
            raise compose.CompositionRejected("identity source drift from reviewed code pin")
        if compose.sha256(behavior_raw) != PINNED_BEHAVIOR_SHA256:
            raise compose.CompositionRejected("behavior source drift from reviewed code pin")
    except compose.CompositionRejected as exc:
        print(f"Local request refused: {exc}", file=sys.stderr)
        return 2

    history: list[dict[str, str]] = []
    session_id = secrets.token_hex(4)
    counter = 0
    previous_state_sha: str | None = None
    while True:
        if args.prompt is not None:
            current = args.prompt
        else:
            try:
                current = input("You> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if current.strip().lower() in {"/quit", "/exit"}:
                return 0
            if not current.strip():
                continue
        counter += 1
        try:
            if live_public_provider is not None:
                # A trusted host must recheck current ledger CAS and approval on
                # EVERY turn. Never let a failed recheck reuse previous context.
                try:
                    state, key, revision = live_public_provider()
                    compose.verify_state(state, key=key, expected_revision=revision)
                except (compose.CompositionRejected, ValueError, KeyError) as exc:
                    history.clear()
                    previous_state_sha = None
                    raise compose.CompositionRejected(
                        f"live public-memory approval unavailable: {exc}") from exc
                except Exception as exc:
                    history.clear()
                    previous_state_sha = None
                    raise compose.CompositionRejected(
                        "live public-memory provider failed; execution refused") from exc
                current_state_sha = compose.sha256(compose.canonical(state))
                if previous_state_sha is not None and current_state_sha != previous_state_sha:
                    history.clear()
                    print("Public context changed; volatile conversation history cleared.",
                          file=sys.stderr)
                previous_state_sha = current_state_sha
            request = compose_local_turn(
                text=current, turn_id=f"local-{session_id}-{counter}", history=history,
                identity=identity, identity_raw=identity_raw,
                behavior=behavior, behavior_raw=behavior_raw,
                state=state, key=key, revision=revision,
                model=model, model_digest=digest, witness=witness,
                num_predict=args.max_output_tokens,
            )
            loopback.validate_candidate(request)
        except (compose.CompositionRejected, loopback.LoopbackRejected) as exc:
            print(f"Local request refused: {exc}", file=sys.stderr)
            if args.prompt is not None:
                return 2
            continue
        if not args.execute:
            print(json.dumps({"status": "VALIDATED_NOT_EXECUTED",
                              "request_sha256": request["request_sha256"],
                              "model_identity": "NOT_ATTESTED", "http_calls": 0}))
            return 0
        try:
            result = loopback.execute(request, endpoint=args.endpoint,
                                      timeout_seconds=args.timeout_seconds,
                                      ollama_disable_thinking=args.ollama_disable_thinking)
        except loopback.LoopbackRejected as exc:
            print(f"Local inference failed: {exc}", file=sys.stderr)
            return 2
        if live_public_provider is not None:
            # A revocation during the HTTP call cannot retract data already
            # sent to the local server. It CAN prevent the output being shown
            # or added to local history if current approval has since changed.
            try:
                after_state, after_key, after_revision = live_public_provider()
                compose.verify_state(after_state, key=after_key,
                                     expected_revision=after_revision)
                if compose.sha256(compose.canonical(after_state)) != previous_state_sha:
                    raise compose.CompositionRejected("approved public source changed")
            except Exception:
                history.clear()
                print("Local output withheld: post-inference public-memory approval "
                      "or source integrity changed; session stopped.", file=sys.stderr)
                return 2
        if result["status"] == "TRUNCATED_UNVERIFIED_OUTPUT":
            print("Vera [incomplete reply]> " + result["response"]["text"])
            history.clear()
            print("Session history cleared: model output was truncated. "
                  "No claim of a completed response or preserved continuity.", file=sys.stderr)
        else:
            print("Vera> " + result["response"]["text"])
            pair = (request["inference"]["messages"][-1],
                    {"role": "assistant", "content": result["response"]["text"]})
            if all(len(message["content"].encode("utf-8")) <= 8192 for message in pair):
                history.extend(pair)
                history = history[-4:]
            else:
                history.clear()
                print("Session history cleared: the last exchange exceeded the 8 KiB "
                      "per-message context limit. The reply was not truncated or persisted.",
                      file=sys.stderr)
        if args.prompt is not None:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
