from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .qualified_runtime import QualifiedVeraRuntime
from .state import VeraStateDirectory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vera-mono",
        description=(
            "Inspect the persistent local vera-mono runtime state. "
            "This CLI does not deploy, install providers, or grant authority."
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


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return _status(args)
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"vera-mono: {exc}\n")
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
