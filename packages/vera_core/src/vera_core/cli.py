from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from .console import VeraConsole, run_console_repl
from .local_model_advisory import MAX_PROMPT_CHARS, advise_local_model
from .qualified_runtime import QualifiedVeraRuntime
from .state import VeraStateDirectory


def _add_state_binding(parser: argparse.ArgumentParser, *, required: bool) -> None:
    parser.add_argument(
        "--state-root",
        required=required,
        help="existing vera-mono persistent state root",
    )
    parser.add_argument(
        "--project-id",
        required=required,
        help="exact governed project identifier",
    )
    parser.add_argument(
        "--identity-id",
        required=required,
        help="exact governed identity identifier",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vera-mono",
        description=(
            "Interact with Vera Mono or inspect persistent local runtime state. "
            "The CLI does not grant protected-effect authority."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser(
        "status",
        help="verify and print the reconstructed local runtime context",
    )
    _add_state_binding(status, required=True)
    status.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print JSON instead of canonical compact JSON",
    )

    shell = subparsers.add_parser(
        "shell",
        aliases=["console"],
        help=(
            "open Vera Mono's semantic/pragmatic repository console; "
            "no external LLM is required"
        ),
    )
    shell.add_argument(
        "prompt",
        nargs="?",
        help="optional one-shot input; omit for interactive mode",
    )
    _add_state_binding(shell, required=False)

    advise = subparsers.add_parser(
        "advise",
        help=(
            "ask an explicitly selected loopback model for unverified, "
            "read-only advisory text; no Vera state, tools, or effects"
        ),
    )
    advise.add_argument("prompt", help="one-shot prompt sent only to the local model")
    advise.add_argument("--endpoint", required=True, help="exact HTTP loopback /v1 endpoint")
    advise.add_argument("--model", required=True, help="exact local model alias")
    advise.add_argument("--api-key-env", help="optional environment variable containing a local API key")
    advise.add_argument("--max-tokens", type=int, default=180)
    advise.add_argument("--timeout-seconds", type=int, default=60)
    advise.add_argument("--json", action="store_true", help="emit the full provenance envelope")

    chat = subparsers.add_parser(
        "chat",
        help=(
            "send one prompt to an explicit loopback model with minimal "
            "reconstructed Vera lifecycle metadata; no tools or memory admission"
        ),
    )
    chat.add_argument("prompt", help="one-shot user prompt")
    _add_state_binding(chat, required=True)
    chat.add_argument("--endpoint", required=True, help="exact HTTP loopback /v1 endpoint")
    chat.add_argument("--model", required=True, help="exact local model alias")
    chat.add_argument("--api-key-env", help="optional local API-key environment variable")
    chat.add_argument("--max-tokens", type=int, default=180)
    chat.add_argument("--timeout-seconds", type=int, default=60)
    chat.add_argument("--json", action="store_true", help="emit bounded source and model evidence")
    return parser


def _bound_state(args: argparse.Namespace) -> VeraStateDirectory:
    root = Path(args.state_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(
            "state binding requires an existing state-root directory; "
            "it will not infer or silently choose one"
        )
    return VeraStateDirectory(
        root,
        project_id=args.project_id,
        identity_id=args.identity_id,
    )


def _status(args: argparse.Namespace) -> int:
    state = _bound_state(args)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    context = runtime.resume_context()
    payload = {
        "schema": "VERA_MONO_CLI_STATUS_V1",
        "state_root": str(state.paths.root),
        "project_id": args.project_id,
        "identity_id": args.identity_id,
        "runtime_context": context,
        "claim_ceiling": (
            "LOCAL_STATE_INSPECTION_NOT_DEPLOYMENT_NOT_INSTALLATION_"
            "NOT_PROVIDER_ACTIVATION_NOT_PROTECTED_EFFECT_AUTHORITY"
        ),
    }
    if args.pretty:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
    else:
        rendered = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    sys.stdout.write(rendered + "\n")
    return 0


def _shell(args: argparse.Namespace) -> int:
    state_values = (args.state_root, args.project_id, args.identity_id)
    if any(value is not None for value in state_values) and not all(
        value is not None for value in state_values
    ):
        raise ValueError(
            "state-bound shell requires --state-root, --project-id, "
            "and --identity-id together"
        )

    if all(value is not None for value in state_values):
        state = _bound_state(args)

        def context_provider() -> dict:
            runtime = QualifiedVeraRuntime.from_state_directory(state)
            return runtime.resume_context()

        console = VeraConsole.runtime_bound(context_provider)
    else:
        console = VeraConsole.source_only()

    if args.prompt is not None:
        response = console.dispatch(args.prompt)
        sys.stdout.write(response.text + "\n")
        return 0

    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if not raw:
            raise ValueError("stdin did not contain console input")
        response = console.dispatch(raw)
        sys.stdout.write(response.text + "\n")
        return 0

    return run_console_repl(console)


def _advise(args: argparse.Namespace) -> int:
    result = advise_local_model(
        args.prompt,
        endpoint=args.endpoint,
        model_id=args.model,
        api_key_env=args.api_key_env,
        max_tokens=args.max_tokens,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        sys.stdout.write(
            json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False, sort_keys=True)
            + "\n"
        )
    else:
        sys.stdout.write(
            f"UNVERIFIED_MODEL_OUTPUT — model={result.model_id} "
            f"endpoint={result.endpoint}; no Vera memory or effect authority\n"
            + result.text
            + "\n"
        )
    return 0


_CHAT_STATUSES = frozenset({
    "EMPTY",
    "BLOCKED_CANDIDATE",
    "INTERRUPTED_CANDIDATE",
    "CONTROL_SOURCE_DRIFT",
    "MEMORY_AHEAD_OF_CURRENTNESS",
    "ACCEPTED_RECONCILED",
    "ACCEPTED_CURRENT",
})


def _chat(args: argparse.Namespace) -> int:
    """Convey only allowlisted QVR state to a bounded, effectless model adapter."""
    state = _bound_state(args)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    reconstruction = runtime.lifecycle.reconstruct()
    if reconstruction.status not in _CHAT_STATUSES:
        raise ValueError("unknown reconstructed lifecycle status")
    runtime_id = reconstruction.accepted_runtime_id
    if runtime_id is not None and type(runtime_id) is not str:
        raise ValueError("invalid accepted runtime identity")
    context = {
        "schema": "VERA_MONO_LOCAL_CHAT_CONTEXT_V1",
        "status": reconstruction.status,
        "accepted_runtime_id_sha256": (
            None if runtime_id is None else sha256(runtime_id.encode("utf-8")).hexdigest()
        ),
    }
    context_json = json.dumps(context, ensure_ascii=False, allow_nan=False, sort_keys=True,
                              separators=(",", ":"))
    context_digest = sha256(context_json.encode("utf-8")).hexdigest()
    bound_prompt = (
        "Locally reconstructed Vera lifecycle status (unverified; not authority):\n"
        + context_json
        + "\n\nUser prompt:\n"
        + args.prompt
    )
    if len(bound_prompt) > MAX_PROMPT_CHARS:
        raise ValueError("chat prompt and bounded context exceed the local model size limit")
    result = advise_local_model(
        bound_prompt,
        endpoint=args.endpoint,
        model_id=args.model,
        api_key_env=args.api_key_env,
        max_tokens=args.max_tokens,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        payload = {
            "schema": "VERA_MONO_LOCAL_CHAT_RESULT_V1",
            "context": context,
            "context_sha256": context_digest,
            "result": result.to_dict(),
            "claim_ceiling": "UNVERIFIED_MODEL_OUTPUT_NOT_CURRENTNESS_NOT_EFFECT_AUTHORITY",
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                    sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            f"UNVERIFIED_MODEL_OUTPUT — QVR status={context['status']} "
            f"context_sha256={context_digest}; memory_admission=NONE "
            "authority=NONE tool_execution=NONE\n"
            + result.text
            + "\n"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return _status(args)
        if args.command in {"shell", "console"}:
            return _shell(args)
        if args.command == "advise":
            return _advise(args)
        if args.command == "chat":
            return _chat(args)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"vera-mono: {exc}\n")
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
