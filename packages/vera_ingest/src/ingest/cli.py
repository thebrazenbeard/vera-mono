from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .model import (
    BytesSource,
    FileSource,
    GitHubFileSource,
    IngestResult,
    IngestStatus,
    MessageSource,
    TextSource,
    UrlSource,
)
from .pipeline import Ingestor
from .policy import IngestPolicy
from .storage import FileSystemStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest")
    parser.add_argument("--store", default=".ingest", help="filesystem store root")
    parser.add_argument("--human", action="store_true", help="emit compact human-readable output")
    parser.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--allow-http", action="store_true")
    parser.add_argument("--allow-private-network", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    text = sub.add_parser("text", help="ingest inline UTF-8 text")
    text.add_argument("text")
    text.add_argument("--locator", default="cli:text")

    file_cmd = sub.add_parser("file", help="ingest a local file")
    file_cmd.add_argument("path")
    file_cmd.add_argument("--root", action="append", default=[])
    file_cmd.add_argument("--follow-symlinks", action="store_true")

    url = sub.add_parser("url", help="ingest an HTTP(S) resource")
    url.add_argument("url")

    gh = sub.add_parser("github", help="ingest a GitHub repository file")
    gh.add_argument("owner")
    gh.add_argument("repository")
    gh.add_argument("ref")
    gh.add_argument("path")

    json_cmd = sub.add_parser("json", help="ingest JSON from a file or stdin (-)")
    json_cmd.add_argument("path")
    json_cmd.add_argument("--locator")

    msg = sub.add_parser("message", help="ingest a JSON message/event envelope")
    msg.add_argument("path", help="JSON file or - for stdin")
    msg.add_argument("--id", required=True, dest="message_id")
    msg.add_argument("--source", default="message")
    msg.add_argument("--event-time")

    inspect = sub.add_parser("inspect", help="read a stored ingest record")
    inspect.add_argument("ingest_id")
    return parser


def _read_bytes(path: str, max_bytes: int) -> bytes:
    if path == "-":
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        value = stream.read(max_bytes + 1)
        data = value.encode("utf-8") if isinstance(value, str) else value
    else:
        input_path = Path(path)
        if input_path.stat().st_size > max_bytes:
            raise ValueError(f"input exceeds max_bytes={max_bytes}")
        with input_path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"input exceeds max_bytes={max_bytes}")
    return data


def _human_result(payload: dict) -> str:
    if payload.get("schema") == "INGEST_RECORD_V1":
        return f"{payload['status']} {payload['ingest_id']} raw={payload['raw_artifact']['sha256']}"
    ingest_id = payload.get("ingest_id") or "-"
    raw = payload.get("raw_artifact") or {}
    digest = raw.get("sha256", "-")
    suffix = f" error={payload['error']}" if payload.get("error") else ""
    return f"{payload['status']} {ingest_id} raw={digest}{suffix}"


def _emit_result(result: IngestResult, human: bool) -> int:
    payload = result.to_dict()
    print(
        _human_result(payload)
        if human
        else json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return 0 if result.status in {IngestStatus.ACCEPTED, IngestStatus.DUPLICATE} else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = FileSystemStore(args.store)

    if args.command == "inspect":
        try:
            payload = store.get_record(args.ingest_id)
        except FileNotFoundError:
            payload = {"schema": "INGEST_INSPECT_V1", "status": "NOT_FOUND", "ingest_id": args.ingest_id}
            print(_human_result(payload) if args.human else json.dumps(payload, sort_keys=True, separators=(",", ":")))
            return 2
        print(_human_result(payload) if args.human else json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0

    allowed_roots = tuple(
        str(Path(root).expanduser().resolve())
        for root in (getattr(args, "root", ()) or ())
    )
    policy = IngestPolicy(
        max_bytes=args.max_bytes,
        allow_http=args.allow_http,
        deny_private_networks=not args.allow_private_network,
        allowed_roots=allowed_roots,
        follow_symlinks=bool(getattr(args, "follow_symlinks", False)),
    )

    if args.command == "text":
        source = TextSource(args.text, locator=args.locator)
    elif args.command == "file":
        source = FileSource(args.path)
    elif args.command == "url":
        source = UrlSource(args.url)
    elif args.command == "github":
        source = GitHubFileSource(args.owner, args.repository, args.ref, args.path)
    elif args.command == "json":
        try:
            data = _read_bytes(args.path, args.max_bytes)
        except ValueError as exc:
            return _emit_result(IngestResult(None, IngestStatus.REJECTED, error=str(exc)), args.human)
        except OSError as exc:
            error = exc.strerror or type(exc).__name__
            return _emit_result(IngestResult(None, IngestStatus.FAILED, error=f"input read failed: {error}"), args.human)
        locator = args.locator or ("stdin:json" if args.path == "-" else str(Path(args.path).resolve()))
        source = BytesSource(data, locator=locator, media_type="application/json")
    elif args.command == "message":
        try:
            data = _read_bytes(args.path, args.max_bytes)
        except ValueError as exc:
            return _emit_result(IngestResult(None, IngestStatus.REJECTED, error=str(exc)), args.human)
        except OSError as exc:
            error = exc.strerror or type(exc).__name__
            return _emit_result(IngestResult(None, IngestStatus.FAILED, error=f"input read failed: {error}"), args.human)
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _emit_result(
                IngestResult(None, IngestStatus.REJECTED, error="message input is not valid JSON"),
                args.human,
            )
        if not isinstance(payload, dict):
            return _emit_result(
                IngestResult(None, IngestStatus.REJECTED, error="message JSON must be an object"),
                args.human,
            )
        source = MessageSource(args.message_id, payload, source=args.source, event_time=args.event_time)
    else:  # pragma: no cover
        raise AssertionError(args.command)

    return _emit_result(Ingestor(store).ingest(source, policy=policy), args.human)


if __name__ == "__main__":
    raise SystemExit(main())
