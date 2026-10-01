from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from vera_model import BPETokenizer, load_bootstrap
from vera_model.checkpoint import inspect_checkpoint, load_checkpoint

from .qualified_runtime import QualifiedVeraRuntime
from .state import VeraStateDirectory
from .terminal_chat import TerminalChatSession, run_terminal_repl


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vera-mono",
        description=(
            "Inspect Vera Mono state, train or inspect its native language model, "
            "or talk to Vera through the repository's own checkpoint."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="verify and print reconstructed local runtime context")
    status.add_argument("--state-root", required=True, help="existing vera-mono persistent state root")
    status.add_argument("--project-id", required=True, help="exact governed project identifier")
    status.add_argument("--identity-id", required=True, help="exact governed identity identifier")
    status.add_argument("--pretty", action="store_true", help="pretty-print JSON")

    chat = subparsers.add_parser("chat", help="talk through Vera Mono's native language model")
    chat.add_argument("prompt", nargs="?", help="optional one-shot prompt; omit for interactive REPL")
    chat.add_argument("--checkpoint", help="optional Vera-native .npz checkpoint; requires --tokenizer")
    chat.add_argument("--tokenizer", help="optional Vera-native tokenizer JSON; requires --checkpoint")
    chat.add_argument("--temperature", type=float, default=0.8, help="sampling temperature; 0 is greedy")
    chat.add_argument("--top-k", type=int, default=50, help="top-k sampling cutoff")
    chat.add_argument("--max-new-tokens", type=int, default=128, help="maximum generated tokens per reply")
    chat.add_argument("--seed", type=int, help="optional deterministic sampling seed")
    chat.add_argument("--state-root", help="optional existing VeraStateDirectory root")
    chat.add_argument("--project-id", help="exact governed project identifier for state-bound mode")
    chat.add_argument("--identity-id", help="exact governed identity identifier for state-bound mode")
    chat.add_argument("--runtime-context-limit", type=int, default=120_000, help="maximum serialized runtime metadata characters")

    model = subparsers.add_parser("model", help="train or inspect Vera-native model artifacts")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    inspect = model_sub.add_parser("inspect", help="inspect a native checkpoint")
    inspect.add_argument("--checkpoint", help="checkpoint path; omit to inspect packaged bootstrap")
    inspect.add_argument("--pretty", action="store_true")
    train = model_sub.add_parser("train", help="train Vera-native weights from text corpora")
    train.add_argument("--corpus", action="append", required=True, help="UTF-8 corpus path; repeat for multiple files")
    train.add_argument("--out-dir", required=True)
    train.add_argument("--vocab-size", type=int, default=512)
    train.add_argument("--context-length", type=int, default=128)
    train.add_argument("--layers", type=int, default=2)
    train.add_argument("--heads", type=int, default=2)
    train.add_argument("--embedding", type=int, default=64)
    train.add_argument("--steps", type=int, default=100)
    train.add_argument("--batch-size", type=int, default=8)
    train.add_argument("--learning-rate", type=float, default=3e-4)
    train.add_argument("--seed", type=int, default=0)
    return parser


def _status(args: argparse.Namespace) -> int:
    root = Path(args.state_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("status requires an existing state-root directory; it will not infer one")
    state = VeraStateDirectory(root, project_id=args.project_id, identity_id=args.identity_id)
    runtime = QualifiedVeraRuntime.from_state_directory(state)
    context = runtime.resume_context()
    payload = {
        "schema": "VERA_MONO_CLI_STATUS_V1",
        "state_root": str(root),
        "project_id": args.project_id,
        "identity_id": args.identity_id,
        "runtime_context": context,
        "claim_ceiling": "LOCAL_STATE_INSPECTION_NOT_DEPLOYMENT_NOT_INSTALLATION_NOT_PROVIDER_ACTIVATION_NOT_PROTECTED_EFFECT_AUTHORITY",
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":")) + "\n")
    return 0


def _load_chat_artifacts(args: argparse.Namespace):
    supplied = (args.checkpoint is not None, args.tokenizer is not None)
    if any(supplied) and not all(supplied):
        raise ValueError("--checkpoint and --tokenizer must be supplied together")
    if all(supplied):
        return load_checkpoint(Path(args.checkpoint)), BPETokenizer.load(Path(args.tokenizer))
    return load_bootstrap()


def _chat(args: argparse.Namespace) -> int:
    model, tokenizer = _load_chat_artifacts(args)
    state_values = (args.state_root, args.project_id, args.identity_id)
    if any(value is not None for value in state_values) and not all(value is not None for value in state_values):
        raise ValueError("state-bound chat requires --state-root, --project-id, and --identity-id together")
    generation = {
        "temperature": args.temperature,
        "top_k": args.top_k,
        "max_new_tokens": args.max_new_tokens,
        "seed": args.seed,
    }
    if all(value is not None for value in state_values):
        session = TerminalChatSession.state_bound(
            model,
            tokenizer,
            state_root=args.state_root,
            project_id=args.project_id,
            identity_id=args.identity_id,
            runtime_context_limit=args.runtime_context_limit,
            **generation,
        )
    else:
        session = TerminalChatSession.source_only(model, tokenizer, **generation)

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


def _model(args: argparse.Namespace) -> int:
    if args.model_command == "inspect":
        if args.checkpoint:
            payload = inspect_checkpoint(Path(args.checkpoint))
            payload["artifact"] = str(Path(args.checkpoint))
        else:
            model, _ = load_bootstrap()
            payload = {
                "schema": "VERA_NATIVE_TRANSFORMER_CHECKPOINT_V1",
                "artifact": "PACKAGED_BOOTSTRAP_SMOKE_CHECKPOINT",
                "config": model.config.as_dict(),
                "parameter_count": sum(int(value.size) for value in model.weights.values()),
                "claim_ceiling": "SMOKE_CHECKPOINT_NOT_USEFUL_LANGUAGE_COMPETENCE",
            }
        sys.stdout.write(json.dumps(payload, sort_keys=True, indent=2 if args.pretty else None, separators=None if args.pretty else (",", ":")) + "\n")
        return 0

    if args.model_command == "train":
        from vera_model.training import train_text_model
        texts = []
        for raw_path in args.corpus:
            path = Path(raw_path).expanduser().resolve()
            if not path.is_file():
                raise ValueError(f"corpus does not exist: {path}")
            texts.append(path.read_text(encoding="utf-8"))
        artifacts = train_text_model(
            "\n".join(texts),
            Path(args.out_dir).expanduser().resolve(),
            vocab_size=args.vocab_size,
            context_length=args.context_length,
            n_layer=args.layers,
            n_head=args.heads,
            n_embd=args.embedding,
            steps=args.steps,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            seed=args.seed,
        )
        payload = {
            "schema": "VERA_NATIVE_TRAINING_RESULT_V1",
            "checkpoint": str(artifacts.checkpoint_path),
            "tokenizer": str(artifacts.tokenizer_path),
            "steps": artifacts.steps,
            "final_loss": artifacts.final_loss,
        }
        sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
        return 0
    raise ValueError("unsupported model command")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return _status(args)
        if args.command == "chat":
            return _chat(args)
        if args.command == "model":
            return _model(args)
    except (KeyError, OSError, TypeError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"vera-mono: {exc}\n")
    parser.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
