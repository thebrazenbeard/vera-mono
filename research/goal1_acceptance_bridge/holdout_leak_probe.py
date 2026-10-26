"""Read-only negative control for PUBLIC holdout answers in evaluator source.

Scanning one Python file cannot prove independent private-label custody. This
probe deliberately never returns a positive qualification, even when no
literal leak is found. It never contacts a private evaluator or a model.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

_LITERALS = frozenset(("A", "B"))
PUBLIC_FIXTURE_LABELS = frozenset(("HOLDOUT", "HOLDOUT_LABELS", "TEST_LABELS"))


def inspect_public_trial_source(source: str) -> dict:
    tree = ast.parse(source)
    visible = 0
    uncertain = False
    declarations = 0
    # This AST check intentionally handles only simple module-level literals:
    # dynamic imports, aliases or generated truth can evade static scanning.
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id in PUBLIC_FIXTURE_LABELS
                   for t in targets):
            continue
        declarations += 1
        try:
            payload = ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError, MemoryError):
            uncertain = True
            continue
        if not isinstance(payload, (list, tuple)):
            uncertain = True
            continue
        for item in payload:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                uncertain = True
                continue
            _, label = item
            if type(label) is str and label in _LITERALS:
                visible += 1
            else:
                uncertain = True
    leaked = visible > 0
    return {
        "schema": "GOAL1_PUBLIC_HOLDOUT_LEAK_SCAN_V1",
        "public_inline_holdout_labels": visible,
        "public_source_oracle_accuracy": (
            1.0 if leaked and not uncertain else None
        ),
        "observed_literal_declarations": declarations,
        "classification": (
            "PUBLIC_FIXTURE_LEAKED_NOT_PRIVATE_HOLDOUT" if leaked
            else "NO_INLINE_LEAK_OBSERVED_CUSTODY_UNKNOWN"
        ),
        "private_holdout_verified": False,
        "learning_qualified": False,
        "non_literal_source_not_fully_excluded": True,
        "reason": (
            "The public source discloses answers; source lookup can imitate learning"
            if leaked else
            "No matching inline labels observed; private custody is not established"
        ),
    }


def private_holdout_exit_code(report: dict) -> int:
    """This source-only scanner has no custody proof; always fail closed."""
    return 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--expected-sha256",
                        help="optional exact source-byte identity guard")
    parser.add_argument("--require-private-holdout", action="store_true")
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    if args.expected_sha256 is not None and digest != args.expected_sha256:
        raise ValueError("evaluator source bytes mismatch; refreeze exact source")
    scan = inspect_public_trial_source(source_bytes.decode("utf-8"))
    scan["source_sha256"] = digest
    print(json.dumps(scan, sort_keys=True))
    if args.require_private_holdout:
        print("GOAL1_PRIVATE_HOLDOUT_GATE=BLOCKED_SOURCE_ONLY", file=sys.stderr)
        raise SystemExit(private_holdout_exit_code(scan))


if __name__ == "__main__":
    main()
