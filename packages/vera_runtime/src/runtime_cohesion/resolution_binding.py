from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
import re


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHUNK_ROUTE = re.compile(r"^chunk:(0|[1-9][0-9]*)$")


class ResolutionBindingError(ValueError):
    pass


class BoundRouteStatus(StrEnum):
    PROMOTE = "PROMOTE"
    DIRECT = "DIRECT"
    INSUFFICIENT_FIDELITY = "INSUFFICIENT_FIDELITY"


@dataclass(frozen=True, slots=True)
class ResolutionRouteBinding:
    block_ids: tuple[str, ...]
    binding_digest: str

    @classmethod
    def create(
        cls,
        block_ids: tuple[str, ...],
    ) -> "ResolutionRouteBinding":
        if type(block_ids) is not tuple or not block_ids:
            raise ResolutionBindingError(
                "block_ids must be a non-empty exact tuple"
            )
        for block_id in block_ids:
            if type(block_id) is not str or _SHA256.fullmatch(block_id) is None:
                raise ResolutionBindingError(
                    "every block_id must be a lowercase sha256 digest"
                )
        if len(block_ids) != len(set(block_ids)):
            raise ResolutionBindingError("block_ids must be unique")

        payload = {
            "schema": "VERA_RESOLUTION_ROUTE_BINDING_V1",
            "block_ids": list(block_ids),
        }
        digest = sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            block_ids=block_ids,
            binding_digest=digest,
        )

    def validate(self) -> None:
        rebuilt = type(self).create(self.block_ids)
        if self.binding_digest != rebuilt.binding_digest:
            raise ResolutionBindingError(
                "binding_digest does not bind the ordered block_ids"
            )


@dataclass(frozen=True, slots=True)
class BoundResolutionRoute:
    status: BoundRouteStatus
    route_label: str
    binding_digest: str
    evidence_ref: str | None
    chunk_index: int | None


def resolve_resolution_route(
    binding: ResolutionRouteBinding,
    route_label: str,
) -> BoundResolutionRoute:
    if type(binding) is not ResolutionRouteBinding:
        raise ResolutionBindingError(
            "binding must be an exact ResolutionRouteBinding"
        )
    binding.validate()
    if type(route_label) is not str or not route_label:
        raise ResolutionBindingError(
            "route_label must be a non-empty exact string"
        )

    if route_label == "DIRECT":
        return BoundResolutionRoute(
            status=BoundRouteStatus.DIRECT,
            route_label=route_label,
            binding_digest=binding.binding_digest,
            evidence_ref=None,
            chunk_index=None,
        )

    if route_label == "INSUFFICIENT_FIDELITY":
        return BoundResolutionRoute(
            status=BoundRouteStatus.INSUFFICIENT_FIDELITY,
            route_label=route_label,
            binding_digest=binding.binding_digest,
            evidence_ref=None,
            chunk_index=None,
        )

    match = _CHUNK_ROUTE.fullmatch(route_label)
    if match is None:
        raise ResolutionBindingError(
            "route_label must be chunk:N, DIRECT, or INSUFFICIENT_FIDELITY"
        )
    index = int(match.group(1))
    if index >= len(binding.block_ids):
        raise ResolutionBindingError(
            "chunk route is outside the bound candidate set"
        )
    return BoundResolutionRoute(
        status=BoundRouteStatus.PROMOTE,
        route_label=route_label,
        binding_digest=binding.binding_digest,
        evidence_ref=binding.block_ids[index],
        chunk_index=index,
    )
