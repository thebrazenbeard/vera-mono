"""Separate read-only historical export inventory entry point.

This stays outside the immutable absorbed-donor CLI source-closure contract.
It does not construct an ingestion store or grant publication rights.
"""

from __future__ import annotations

import argparse
import json

from .export_inventory import inventory_exports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only local historical export inventory")
    parser.add_argument("directory")
    parser.add_argument("--max-files", type=int, default=500)
    parser.add_argument("--max-depth", type=int, default=1)
    parser.add_argument("--max-read-bytes", type=int, default=1024 * 1024)
    parser.add_argument("--hash-local", action="store_true", help="opt in to bounded local reads")
    parser.add_argument("--inspect-zip-local", action="store_true", help="opt in to bounded ZIP metadata reads")
    parser.add_argument("--include-names", action="store_true", help="include private relative paths locally")
    args = parser.parse_args(argv)
    try:
        payload = inventory_exports(
            args.directory,
            max_files=args.max_files,
            max_depth=args.max_depth,
            max_read_bytes=args.max_read_bytes,
            hash_local=args.hash_local,
            inspect_zip_local=args.inspect_zip_local,
            include_names=args.include_names,
        )
    except (ValueError, OSError) as exc:
        print(json.dumps({
            "schema": "VERA_EXPORT_INVENTORY_V1",
            "status": "REJECTED",
            "error": type(exc).__name__,
        }, sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
