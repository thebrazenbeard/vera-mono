from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "vera_runtime" / "src"))

from runtime_cohesion.local_bindings import (  # noqa: E402
    MONOREPO_REPOSITORY,
    PACKAGED_PROVENANCE_SCHEMA,
    git_blob_sha,
    packaged_provenance_required_paths,
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build_manifest() -> dict[str, object]:
    head = _git("rev-parse", "HEAD")
    if len(head) != 40:
        raise SystemExit("cannot resolve exact vera-mono HEAD")
    files: dict[str, str] = {}
    for repo_path in sorted(packaged_provenance_required_paths()):
        live = ROOT / repo_path
        if not live.is_file():
            raise SystemExit(f"required packaged-provenance file is missing: {repo_path}")
        live_blob = git_blob_sha(live.read_bytes())
        committed_blob = _git("rev-parse", f"{head}:{repo_path}")
        if committed_blob != live_blob:
            raise SystemExit(
                f"working tree bytes differ from HEAD for packaged provenance: {repo_path}"
            )
        files[repo_path] = live_blob
    return {
        "schema": PACKAGED_PROVENANCE_SCHEMA,
        "repository": MONOREPO_REPOSITORY,
        "source_commit": head,
        "source_commit_verification": "LOCAL_GIT_OBJECTS_AT_GENERATION",
        "protected_effect_authority": False,
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    payload = build_manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "VERA_MONO_PACKAGED_PROVENANCE_PASS "
        f"source_commit={payload['source_commit']} "
        f"files={len(payload['files'])} "
        "protected_effect_authority=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
