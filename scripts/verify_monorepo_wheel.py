from __future__ import annotations

import hashlib
from email.parser import Parser
from email.policy import default
from pathlib import Path
import sys
from zipfile import ZipFile


REQUIRED_FILES = {
    "vera_core/__init__.py",
    "vera_core/__main__.py",
    "vera_core/cli.py",
    "ingest/__init__.py",
    "ingest/resources/schemas/ingest-record-v1.schema.json",
    "rezon/__init__.py",
    "portfolio_runtime/__init__.py",
    "protocol/__init__.py",
    "runtime_cohesion/__init__.py",
    "tul_fixture/__init__.py",
    "vera_identity/__init__.py",
    "coordination_bus/__init__.py",
    "vera_memory/__init__.py",
    "vera_assurance/__init__.py",
    "pc_connection/__init__.py",
    "vera_control/__init__.py",
    "r8a0/__init__.py",
    "vera_recovery/__init__.py",
    (
        "vera_control/resources/architecture/control/vendor/"
        "vera-control-plane/VERA_R10A0_PROJECT_SOURCE_MANIFEST_R10.json"
    ),
    (
        "vera_identity/resources/architecture/identity/"
        "VERA_PROJECT_IDENTITY_V1.json"
    ),
    (
        "vera_memory/resources/architecture/integration/"
        "VERA_DEEP_MEMORY_ARCHIVE_INTEGRATION_V1.json"
    ),
    "runtime_cohesion/resources/ORGASM_RUNTIME_CONTRACT_V1.json",
    (
        "vera_assurance/resources/architecture/"
        "VERA_DRIFTGUARD_TRANSFERABILITY_V1.json"
    ),
}


def fail(message: str) -> None:
    raise SystemExit("wheel verification failed: " + message)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        fail("usage: verify_monorepo_wheel.py <wheel>")
    wheel = Path(argv[1]).resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        fail(f"not an exact wheel path: {wheel}")

    raw = wheel.read_bytes()
    wheel_digest = hashlib.sha256(raw).hexdigest()
    with ZipFile(wheel) as archive:
        names = tuple(archive.namelist())
        name_set = set(names)
        if len(names) != len(name_set):
            fail("wheel contains duplicate archive paths")
        unsafe = [
            name
            for name in names
            if name.startswith("/")
            or "\\" in name
            or ".." in Path(name).parts
        ]
        if unsafe:
            fail("wheel contains unsafe archive paths: " + ", ".join(unsafe))

        missing = sorted(REQUIRED_FILES - name_set)
        if missing:
            fail(
                "wheel is missing required runtime/resource files: "
                + ", ".join(missing)
            )

        metadata_names = sorted(
            name
            for name in names
            if name.endswith(".dist-info/METADATA")
        )
        if len(metadata_names) != 1:
            fail("wheel must contain exactly one distribution METADATA file")
        metadata_text = archive.read(metadata_names[0]).decode("utf-8")
        metadata = Parser(policy=default).parsestr(metadata_text)
        if metadata.get("Name") != "vera-mono":
            fail("wheel METADATA does not identify vera-mono")
        if metadata.get("Version") != "0.1.0":
            fail("wheel METADATA carries unexpected version")

        entry_point_names = sorted(
            name
            for name in names
            if name.endswith(".dist-info/entry_points.txt")
        )
        if len(entry_point_names) != 1:
            fail(
                "wheel must contain exactly one distribution entry_points.txt"
            )
        entry_points = archive.read(entry_point_names[0]).decode("utf-8")
        if "[console_scripts]" not in entry_points:
            fail("wheel console script group is missing")
        if "vera-mono = vera_core.cli:main" not in entry_points:
            fail("wheel vera-mono console entrypoint is missing")

    print(
        "VERA_MONO_WHEEL_PASS "
        f"sha256={wheel_digest} "
        f"files={len(names)} "
        f"required={len(REQUIRED_FILES)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
