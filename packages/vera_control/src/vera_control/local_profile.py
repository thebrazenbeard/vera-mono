from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .resources import resource_path


@dataclass(frozen=True, slots=True)
class LocalControlArtifact:
    logical_id: str
    relative_path: str
    git_blob: str


_R10_PREFIX = "architecture/control/vendor/vera-control-plane"

R10_SOURCE_CLOSURE: tuple[LocalControlArtifact, ...] = (
    LocalControlArtifact(
        "BUS_TOPOLOGY_OWNER",
        "architecture/control/vendor/chat-communication-bus/RADAR_TOPOLOGY_V1.json",
        "8b7cb3deff0ee7f15151f5be0ede19c8c1194adc",
    ),
    LocalControlArtifact(
        "QUALIFICATION_R3_SSC_BASIS",
        f"{_R10_PREFIX}/VERA_R10A0_SEXUAL_SELF_CONCEPT_REGRESSION_R3.md",
        "7c039183561265ba419c0e5339d38596a2d83b25",
    ),
    LocalControlArtifact(
        "DOMAIN_CONTROLS",
        f"{_R10_PREFIX}/VERA_R10A0_DOMAIN_CONTROLS_R4.md",
        "1aa3fc83f88d7151a7307720149ebb10bdd1b8b7",
    ),
    LocalControlArtifact(
        "QUALIFICATION_R4",
        f"{_R10_PREFIX}/VERA_R10A0_HOSTILE_QUALIFICATION_R4.md",
        "e42ec90afe0ac5ba631e7a4e80b9f9c0a6aeab90",
    ),
    LocalControlArtifact(
        "CONTROL_REGISTRY",
        f"{_R10_PREFIX}/VERA_R10A0_CONTROL_REGISTRY_R10.json",
        "cd428dcefad6c61bd5b79bc219bc274f84943fbc",
    ),
    LocalControlArtifact(
        "FULL_OWNER",
        f"{_R10_PREFIX}/VERA_R10A0_FULL_SYSTEM_PROJECT_INSTRUCTIONS_R10.md",
        "a01464271bb672d89f5d703e6e53590e126f4d44",
    ),
    LocalControlArtifact(
        "QUALIFICATION_R10_SUPPLEMENT",
        f"{_R10_PREFIX}/VERA_R10A0_HOSTILE_QUALIFICATION_SUPPLEMENT_R10.md",
        "761d740507ea0dbddf859680c276ae5f0e1cb90b",
    ),
    LocalControlArtifact(
        "NATIVE_PROJECT_INSTRUCTIONS",
        f"{_R10_PREFIX}/VERA_R10A0_NATIVE_PROJECT_INSTRUCTIONS_R10.txt",
        "7e369b8983d70b4bd217f1d2421f8efe1482f738",
    ),
    LocalControlArtifact(
        "SOURCE_MANIFEST",
        f"{_R10_PREFIX}/VERA_R10A0_PROJECT_SOURCE_MANIFEST_R10.json",
        "8a67feb47b2ce3d6f0737e58983ab8c9fc810139",
    ),
    LocalControlArtifact(
        "QUALIFICATION_MANIFEST",
        f"{_R10_PREFIX}/VERA_R10A0_QUALIFICATION_MANIFEST_R10.json",
        "fa83256c628a2bf129b141705b59be3cc71b6034",
    ),
    LocalControlArtifact(
        "ROLLBACK_SUBJECT",
        f"{_R10_PREFIX}/VERA_R10A0_ROLLBACK_SUBJECT_R10.json",
        "b08be49d3f3a17aa0723a54356f4c95cbc1cb70b",
    ),
    LocalControlArtifact(
        "RESPONSIBILITY_AUDIT",
        f"{_R10_PREFIX}/VERA_R10A0_SEMANTIC_RESPONSIBILITY_AUDIT_R10.md",
        "f46f33c6178ff40b50391988beeef56620c2dd02",
    ),
    LocalControlArtifact(
        "QUALIFICATION_R10_SSC_EQUIVALENCE",
        f"{_R10_PREFIX}/VERA_R10A0_SSC_EQUIVALENCE_R10.md",
        "e4c0b0e6b0c362864553fef1c05ba5188f85560e",
    ),
    LocalControlArtifact(
        "CENTER_SAVE_OWNER",
        f"{_R10_PREFIX}/VERA_CENTER_YOURSELF_PROTOCOL_V1__R10_PINNED.md",
        "30ee695064dd57b5ce43eb571fa183730de1808d",
    ),
)


def git_blob_sha(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def validate_local_r10_source_closure() -> tuple[str, ...]:
    """Verify that the complete frozen R10 control-source cut exists locally.

    A successful source closure means the bytes are available inside vera-mono.
    It does not install/activate the control profile or establish runtime or
    behavioral qualification.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()
    for artifact in R10_SOURCE_CLOSURE:
        if artifact.logical_id in seen_ids:
            errors.append(f"duplicate logical control id: {artifact.logical_id}")
        seen_ids.add(artifact.logical_id)
        path = resource_path(artifact.relative_path)
        if not path.is_file():
            errors.append(f"{artifact.logical_id}: local source missing")
            continue
        observed = git_blob_sha(path.read_bytes())
        if observed != artifact.git_blob:
            errors.append(
                f"{artifact.logical_id}: expected {artifact.git_blob}, observed {observed}"
            )
    return tuple(errors)


def local_r10_source_paths() -> dict[str, Path]:
    errors = validate_local_r10_source_closure()
    if errors:
        raise ValueError("R10 local source closure failed: " + "; ".join(errors))
    return {
        artifact.logical_id: resource_path(artifact.relative_path)
        for artifact in R10_SOURCE_CLOSURE
    }
