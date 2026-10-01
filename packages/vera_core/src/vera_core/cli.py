from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .qualified_runtime import QualifiedVeraRuntime
from .state import VeraStateDirectory
from .terminal_chat import (
    OpenAICompatibleBackend,
    TerminalChatSession,
    run_terminal_repl,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vera-mono",
        description=(
            "Inspect vera-mono runtime state or open the Vera Mono terminal "
            "interaction surface. This CLI does not deploy, install providers, "
            "or grant authority."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser(
        "status",
        help="verify and print the reconstructed local runtime context",
    )
    status.add_argument(
        "--state-root",
        required=True,
        help="existing vera-mono persistent state root",
    )
    status.add_argument(
        "--project-id",
        required=True,
        help="exact governed project identifier",
    )
    status.add_argument(
        "--identity-id",
        required=True,
        help="exact governed identity identifier",
    )
    status.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print JSON instead of canonical compact JSON",
    )

    chat = subparsers.add_parser(
        "chat",
        help="talk to Vera Mono through a host-selected text-generation backend",
    )
    chat.add_argument(
        "prompt",
        nargs="?",
        help="optional one-shot prompt; omit for an interactive REPL",
    )
    chat.add_argument(
        "--base-url",
        default=os.environ.get("VERA_MODEL_BASE_URL"),
        help=(
            "OpenAI-compatible API base URL, for example "
            "http://localhost:1234/v1; may also use VERA_MODEL_BASE_URL"
        ),
    )
    chat.add_argument(
        "--model",
        default=os.environ.get("VERA_MODEL_NAME"),
        help="backend model name; may also use VERA_MODEL_NAME",
    )
    chat.add_argument(
        "--api-key-env",
        default="VERA_MODEL_API_KEY",
        help=(
            "environment variable containing the backend API key; "
            "defaults to VERA_MODEL_API_KEY"
        ),
    )
    chat.add_argument(
        "--temperature",
        type=float,
        default=0.4,
        help="backend sampling temperature, default 0.4",
    )
    chat.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP request timeout in seconds, default 120",
    )
    chat.add_argument(
        "--state-root",
        help=(
            "optional existing VeraStateDirectory root; requires --project-id "
            "and --identity-id and enables QUALIFIED_STATE_BOUND mode"
        ),
    )
    chat.add_argument(
        "--project-id",
        help="exact governed project identifier for state-bound mode",
    )
    chat.add_argument(
        "--identity-id",
        help="exact governed identity identifier for state-bound mode",
    )
    chat.add_argument(
        "--runtime-context-limit",
        type=int,
        default=120_000,
        help=(
            "maximum serialized runtime-context characters admitted to the "
            "system prompt, default 120000"
        ),
    )
    return parser


def _status(args: argparse.Namespace) -> int:
    root = Path(args.state_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(
            "status requires an existing state-root directory; "
            "it will not infer or silently choose one"
        )
    state = VeraStateDirectory(
        root,
        project_id=args.project_id,
        identity_id=args.identity_id,
    )
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    context = runtime.resume_context()
    payload = {
        "schema": "VERA_MONO_CLI_STATUS_V1",
        "state_root": str(root),
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


def _chat(args: argparse.Namespace) -> int:
    if type(args.base_url) is not str or not args.base_url.strip():
        raise ValueError(
            "chat requires --base-url or VERA_MODEL_BASE_URL"
        )
    if type(args.model) is not str or not args.model.strip():
        raise ValueError("chat requires --model or VERA_MODEL_NAME")
    if type(args.api_key_env) is not str or not args.api_key_env.strip():
        raise ValueError("--api-key-env must be a non-empty environment variable name")

    api_key = os.environ.get(args.api_key_env)
    backend = OpenAICompatibleBackend(
        base_url=args.base_url,
        model=args.model,
        api_key=api_key,
        timeout_seconds=args.timeout,
        temperature=args.temperature,
    )

    state_values = (
        args.state_root,
        args.project_id,
        args.identity_id,
    )
    if any(value is not None for value in state_values) and not all(
        value is not None for value in state_values
    ):
        raise ValueError(
            "state-bound chat requires --state-root, --project-id, "
            "and --identity-id together"
        )

    if all(value is not None for value in state_values):
        session = TerminalChatSession.state_bound(
            backend,
            state_root=args.state_root,
            project_id=args.project_id,
            identity_id=args.identity_id,
            runtime_context_limit=args.runtime_context_limit,
        )
    else:
        session = TerminalChatSession.source_only(backend)

    if args.prompt is not None:
        sys.stdout.write(session.ask(args.prompt) + "\n")
        return 0

    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if not piped:
            raise ValueError("stdin did not contain a prompt")
        sys.stdout.write(session.ask(piped) + "\n")
        return 0

    return run_terminal_repl(session)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return _status(args)
        if args.command == "chat":
            return _chat(args)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"vera-mono: {exc}\n")
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
