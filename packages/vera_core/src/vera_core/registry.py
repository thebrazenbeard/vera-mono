from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalCapability:
    capability_id: str
    package: str
    import_root: str
    role: str

    def validate(self) -> None:
        for value, label in (
            (self.capability_id, "capability_id"),
            (self.package, "package"),
            (self.import_root, "import_root"),
            (self.role, "role"),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"{label} must be a non-empty exact string")
        if "github.com/" in self.import_root or self.import_root.startswith("thebrazenbeard/"):
            raise ValueError("runtime capability cannot resolve through a sibling repository")


CAPABILITIES: tuple[LocalCapability, ...] = (
    LocalCapability(
        capability_id="reasoning",
        package="rezon",
        import_root="rezon",
        role="progressive reasoning, evidence handling, replay, scheduling, and verification",
    ),
    LocalCapability(
        capability_id="identity_resources",
        package="vera_identity",
        import_root="vera_identity",
        role="local Vera identity, bootstrap, and schema resources",
    ),
    LocalCapability(
        capability_id="runtime_cohesion",
        package="vera_runtime",
        import_root="runtime_cohesion",
        role="Vera runtime cohesion and bounded runtime mechanisms",
    ),
    LocalCapability(
        capability_id="protocol",
        package="vera_runtime",
        import_root="protocol",
        role="Vera workflow and temporal protocol implementation",
    ),
    LocalCapability(
        capability_id="tul_fixture",
        package="vera_runtime",
        import_root="tul_fixture",
        role="local fixture/proof support",
    ),
    LocalCapability(
        capability_id="portfolio_runtime",
        package="portfolio_runtime",
        import_root="portfolio_runtime",
        role="absorbed reusable provenance, admission, state, and work mechanisms",
    ),
    LocalCapability(
        capability_id="coordination",
        package="vera_coordination",
        import_root="coordination_bus",
        role="local message contracts, routing, operator policy, and temporal coordination",
    ),
    LocalCapability(
        capability_id="memory",
        package="vera_memory",
        import_root="vera_memory",
        role="local governed memory admission, CAS heads, supersession, and provenance",
    ),
    LocalCapability(
        capability_id="assurance",
        package="vera_assurance",
        import_root="vera_assurance",
        role="internal deterministic drift and invariant checking",
    ),
    LocalCapability(
        capability_id="pc_connection",
        package="vera_pc_connection",
        import_root="pc_connection",
        role="local computer-connection contracts, journaling, path policy, and state machine",
    ),
    LocalCapability(
        capability_id="control",
        package="vera_control",
        import_root="vera_control",
        role="local Vera control-plane architecture and restore resources",
    ),
)


def validate_registry(
    capabilities: tuple[LocalCapability, ...] = CAPABILITIES,
) -> tuple[str, ...]:
    errors: list[str] = []
    if type(capabilities) is not tuple or not capabilities:
        return ("capability registry must be a non-empty exact tuple",)

    seen_ids: set[str] = set()
    seen_imports: set[str] = set()
    for capability in capabilities:
        if type(capability) is not LocalCapability:
            errors.append("capability registry contains a non-LocalCapability entry")
            continue
        try:
            capability.validate()
        except ValueError as exc:
            errors.append(f"{capability.capability_id or '<unknown>'}: {exc}")
            continue
        if capability.capability_id in seen_ids:
            errors.append(f"duplicate capability id: {capability.capability_id}")
        if capability.import_root in seen_imports:
            errors.append(f"duplicate capability import root: {capability.import_root}")
        seen_ids.add(capability.capability_id)
        seen_imports.add(capability.import_root)
    return tuple(errors)


def capability(capability_id: str) -> LocalCapability:
    if type(capability_id) is not str or not capability_id:
        raise ValueError("capability_id must be a non-empty exact string")
    for item in CAPABILITIES:
        if item.capability_id == capability_id:
            return item
    raise KeyError(capability_id)
