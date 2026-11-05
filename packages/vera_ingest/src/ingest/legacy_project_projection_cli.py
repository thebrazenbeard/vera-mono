"""Read-only historical Project projection verifier. Never installs controls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from .legacy_project_projection import (
    LegacyProjectionError,
    audit_legacy_project_projection,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-directory", required=True, type=Path)
    parser.add_argument("--expected-branch", required=True)
    args = parser.parse_args(argv)
    try:
        result = audit_legacy_project_projection(
            args.project_directory, expected_branch_id=args.expected_branch
        )
    except (LegacyProjectionError, ValueError, TypeError) as exc:
        print(json.dumps({
            "ok": False,
            "status": "HISTORICAL_PROJECTION_UNVERIFIED",
            "reason": str(exc),
            "currentness_verified": False,
            "authority_effect": "NONE",
            "memory_admission_effect": "NONE",
        }, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
