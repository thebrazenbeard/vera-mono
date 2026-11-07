"""One-file offline Mini-Vera command-line entry point."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile

from .memory import MemoryError, MemoryJournal
from .runtime import MiniVera
from .learning import IntentLearner, LABELS


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="mini-vera",
        description="Original offline Mini-Vera: created from code, not trained weights.",
    )
    root.add_argument("--version", action="version", version="mini-vera 0.2.0")
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("ask", "chat"):
        entry = commands.add_parser(command,
            help="Answer a question" if command == "ask" else "Start a local terminal conversation")
        if command == "ask":
            entry.add_argument("question", help="Question to answer")
        entry.add_argument("--docs", action="append", default=[], metavar="ABSOLUTE_DIR",
                           help="Explicitly authorized local document directory (repeatable)")
        entry.add_argument("--memory", metavar="FILE",
                           help="Existing local memory journal; never loaded without --with-memory")
        entry.add_argument("--with-memory", action="store_true",
                           help="Explicitly opt into consulting the local memory journal")
        entry.add_argument("--policy", metavar="FILE",
                           help="Use an explicitly supplied local learned-policy checkpoint")
        entry.add_argument("--no-learning", action="store_true",
                           help="Run original rule-based baseline without learned policy")
        entry.add_argument("--json", action="store_true", help="Output answer with evidence as JSON")

    training = commands.add_parser("train-policy",
        help="Explicitly train local dialogue routing weights from approved labeled JSONL")
    training.add_argument("--data", required=True, metavar="JSONL")
    training.add_argument("--output", required=True, metavar="CHECKPOINT")
    training.add_argument("--consent", action="store_true",
                          help="Confirm source rights and intentional local checkpoint write")
    training.add_argument("--overwrite", action="store_true",
                          help="Explicitly replace a previously saved checkpoint")
    training.add_argument("--epochs", type=int, default=50)

    remember = commands.add_parser("remember", help="Store exactly one user-supplied memory")
    remember.add_argument("text")
    remember.add_argument("--memory", required=True, metavar="FILE")
    remember.add_argument("--scope", default="personal", choices=("personal", "preference", "project"))
    remember.add_argument("--consent", action="store_true", help="Confirm intentional persistent write")

    memories = commands.add_parser("memories", help="Read explicitly selected local memory journal")
    memories.add_argument("--memory", required=True, metavar="FILE")
    memories.add_argument("--json", action="store_true")

    forget = commands.add_parser("forget", help="Append a tombstone for one memory record")
    forget.add_argument("seq", type=int)
    forget.add_argument("--memory", required=True, metavar="FILE")
    forget.add_argument("--consent", action="store_true", help="Confirm intentional persistent write")

    verify = commands.add_parser("verify-memory", help="Validate journal structure and hash chain")
    verify.add_argument("--memory", required=True, metavar="FILE")
    return root


def _display(output: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(output, sort_keys=True, ensure_ascii=False))
    else:
        print(output["reply"])
        for evidence in output["evidence"]:
            print(f"  [source: {evidence['citation'] or evidence['source']}] ")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command in ("ask", "chat"):
            assistant = MiniVera(docs=args.docs, memory_file=args.memory,
                                 use_memory=args.with_memory,
                                 policy_file=args.policy,
                                 use_learning=not args.no_learning)
            if args.command == "ask":
                _display(assistant.ask(args.question), as_json=args.json)
                return 0
            print("Mini-Vera local. Commands: /exit, /quit. No automatic memory writes.")
            while True:
                try:
                    question = input("you> ")
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if question.strip().lower() in ("/exit", "/quit"):
                    break
                _display(assistant.ask(question), as_json=args.json)
            return 0
        if args.command == "train-policy":
            if not args.consent:
                raise PermissionError("train-policy requires --consent for approved data")
            from pathlib import Path
            corpus = Path(args.data)
            if corpus.is_symlink() or not corpus.is_file() or corpus.stat().st_size > 1_000_000:
                raise ValueError("approved JSONL source absent or exceeds 1 MB")
            output = Path(args.output)
            if output.suffix.lower() != ".json" or not output.parent.is_dir():
                raise ValueError("checkpoint output must be a JSON file in an existing directory")
            manifest_path = output.with_name(output.name + ".manifest.json")
            if output.is_symlink() or manifest_path.is_symlink():
                raise ValueError("checkpoint and manifest must not be symbolic links")
            if (output.exists() or manifest_path.exists()) and not args.overwrite:
                raise ValueError("checkpoint or manifest already exists; use --overwrite deliberately")
            samples = []
            for line in corpus.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict) or type(record.get("text")) is not str \
                        or record.get("label") not in LABELS:
                    raise ValueError("each JSONL row requires text and one known label")
                samples.append((record["text"], record["label"]))
            model = IntentLearner()
            report = model.fit(samples, epochs=args.epochs)
            model.save(output)
            # The manifest records user-declared consent and detects accidental
            # modification, but is not a trusted digital signature. Both files
            # must be kept together and reviewed as one explicit sidecar input.
            manifest = {
                "schema": "mini-vera-policy-manifest-v1",
                "checkpoint": output.name,
                "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "consent": True,
                "created_by": "mini-vera train-policy",
            }
            fd, temporary = tempfile.mkstemp(prefix=".mini-vera-manifest-", suffix=".tmp", dir=output.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(manifest, stream, sort_keys=True, separators=(",", ":"))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, manifest_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            print(json.dumps({"training": report, "checkpoint": str(output),
                              "manifest": str(manifest_path),
                              "claims": "intent routing only, no generative-language learning"},
                             sort_keys=True))
            return 0
        if args.command == "remember":
            event = MemoryJournal(args.memory).append(
                args.text, consent=args.consent, scope=args.scope)
            print(f"Stored memory {event['seq']} (sha256:{event['sha256'][:12]}).")
            return 0
        if args.command == "memories":
            records = MemoryJournal(args.memory).read()
            if args.json:
                print(json.dumps(records, ensure_ascii=False, sort_keys=True))
            else:
                for item in records:
                    print(f"[{item['seq']}] {item['content']}")
            return 0
        if args.command == "forget":
            event = MemoryJournal(args.memory).forget(args.seq, consent=args.consent)
            print(f"Forgot memory {args.seq}; tombstone event {event['seq']}.")
            return 0
        if args.command == "verify-memory":
            MemoryJournal(args.memory).verify()
            print("Journal hash chain valid (local integrity only).")
            return 0
    except (ValueError, PermissionError, MemoryError, OSError) as error:
        print(f"mini-vera: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
