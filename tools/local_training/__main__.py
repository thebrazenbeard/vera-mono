"""Safe explicit CLI; does not invoke a trainer or connect to the network."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapter_prep import build_plan, write_private_splits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare local-private Vera adapter examples without training")
    parser.add_argument("action", choices=("plan", "prepare"))
    parser.add_argument("manifest", type=Path, help="Absolute path to private operator-reviewed manifest")
    parser.add_argument("output", nargs="?", type=Path, help="New private output directory (prepare only)")
    args = parser.parse_args(argv)
    if (args.action == "prepare") != (args.output is not None):
        parser.error("prepare requires an output directory; plan forbids one")
    try:
        plan = write_private_splits(args.manifest, args.output) if args.output else build_plan(args.manifest)
    except (ValueError, OSError) as exc:
        print(f"PREPARATION_HOLD: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": "PREPARED_ONLY_NOT_TRAINED_OR_QUALIFIED",
        "manifest_sha256": plan.manifest_sha256,
        "base_model_binding_sha256": plan.base_model_binding_sha256,
        "corpus_sha256": plan.corpus_sha256,
        "training_count": plan.training_count,
        "evaluation_count": plan.evaluation_count,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
