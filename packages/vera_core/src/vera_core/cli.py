from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .console import VeraConsole, run_console_repl
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return _status(args)
        if args.command in {"shell", "console"}:
            return _shell(args)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"vera-mono: {exc}\n")
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
