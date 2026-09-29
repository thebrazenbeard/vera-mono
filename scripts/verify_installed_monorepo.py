from __future__ import annotations

from importlib import import_module, resources


MODULES = (
    "vera_core",
    "vera_core.cli",
    "ingest",
    "rezon",
    "portfolio_runtime",
    "protocol",
    "runtime_cohesion",
    "tul_fixture",
    "vera_identity",
    "coordination_bus",
    "vera_memory",
    "vera_assurance",
    "pc_connection",
    "vera_control",
    "r8a0",
    "vera_recovery",
)

RESOURCES = (
    (
        "ingest",
        "resources/schemas/ingest-record-v1.schema.json",
    ),
    (
        "vera_control",
        (
            "resources/architecture/control/vendor/vera-control-plane/"
            "VERA_R10A0_PROJECT_SOURCE_MANIFEST_R10.json"
        ),
    ),
    (
        "vera_identity",
        "resources/architecture/identity/VERA_PROJECT_IDENTITY_V1.json",
    ),
    (
        "vera_memory",
        (
            "resources/architecture/integration/"
            "VERA_DEEP_MEMORY_ARCHIVE_INTEGRATION_V1.json"
        ),
    ),
    (
        "runtime_cohesion",
        "resources/ORGASM_RUNTIME_CONTRACT_V1.json",
    ),
    (
        "vera_assurance",
        (
            "resources/architecture/"
            "VERA_DRIFTGUARD_TRANSFERABILITY_V1.json"
        ),
    ),
)


def main() -> int:
    imported = []
    for module_name in MODULES:
        module = import_module(module_name)
        if not getattr(module, "__file__", None):
            raise SystemExit(
                f"installed bundle import has no file: {module_name}"
            )
        imported.append(module_name)

    checked = []
    for package, relative in RESOURCES:
        target = resources.files(package).joinpath(*relative.split("/"))
        if not target.is_file():
            raise SystemExit(
                f"installed bundle is missing resource: {package}/{relative}"
            )
        if not target.read_bytes():
            raise SystemExit(
                f"installed bundle resource is empty: {package}/{relative}"
            )
        checked.append(f"{package}/{relative}")

    print(
        "VERA_MONO_INSTALLED_BUNDLE_PASS "
        f"imports={len(imported)} resources={len(checked)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
