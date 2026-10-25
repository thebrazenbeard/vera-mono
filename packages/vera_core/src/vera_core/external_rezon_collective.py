"""Opt-in read-only observation of Rezon's authenticated loopback collective.

An HTTP response is a gateway *claim*, never an independent-host attestation,
verified answer, quorum decision, or permission to execute an action.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import socket
from time import monotonic


_EPISODE = re.compile(r"collective-[0-9a-f]{32}\Z")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BODY = 1_000_000
_MAX_HEADERS = 16_384


class CollectiveObservationError(ValueError):
    """The gateway response cannot be used as even an unverified observation."""


@dataclass(frozen=True, slots=True)
class CollectiveObservation:
    episode_id: str
    input_digest: str
    agents: tuple[str, ...]
    answer_ids: tuple[str, ...]
    review_ids: tuple[str, ...]
    synthesis_ids: tuple[str, ...]
    missing_agents: tuple[str, ...]
    state: str  # COMPLETE_UNVERIFIED | INCOMPLETE_UNKNOWN
    evidence_status: str = "UNVERIFIED_GATEWAY_CLAIM"
    independent_hosts_verified: bool = False
    execution_authorized: bool = False


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(value: object) -> str:
    try:
        return sha256(_canonical(value).encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise CollectiveObservationError("invalid Unicode in collective source claims") from exc


def _valid_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def _agents(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not (1 <= len(value) <= 32) or any(
        not isinstance(agent, str) or not _AGENT.fullmatch(agent) for agent in value
    ) or len(set(value)) != len(value):
        raise CollectiveObservationError("invalid or duplicate worker roster")
    return tuple(value)


def _contributions(value: object, *, kind: str, agents: tuple[str, ...],
                   allowed_targets: set[str]) -> tuple[tuple[str, ...], list[dict]]:
    if not isinstance(value, list) or len(value) > len(agents):
        raise CollectiveObservationError("invalid contribution count")
    seen: set[str] = set()
    identities: list[str] = []
    canonical: list[dict] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "id", "agent_id", "kind", "content", "source_refs", "target_ids"
        }:
            raise CollectiveObservationError("invalid contribution envelope")
        agent = item["agent_id"]
        if agent not in agents or agent in seen or item["kind"] != kind or (
            item["id"] != f"{kind}:{agent}"
        ):
            raise CollectiveObservationError("invalid or duplicated contribution identity")
        if not _valid_text(item["content"]) or not item["content"].strip() or (
            len(item["content"]) > 32_768
        ):
            raise CollectiveObservationError("invalid contribution content")
        refs, targets = item["source_refs"], item["target_ids"]
        if not all(isinstance(v, list) and len(v) <= 32
                   and all(_valid_text(s) and 0 < len(s) <= 1024 for s in v)
                   and len(v) == len(set(v))
                   for v in (refs, targets)):
            raise CollectiveObservationError("invalid source references or targets")
        if kind == "answer" and targets:
            raise CollectiveObservationError("answer cannot review peers")
        if kind == "review" and (not targets or f"answer:{agent}" in targets or
                                 not set(targets).issubset(allowed_targets)):
            raise CollectiveObservationError("invalid peer-review target")
        seen.add(agent)
        identities.append(item["id"])
        canonical.append({
            "contribution_id": item["id"], "agent_id": agent, "kind": kind,
            "content": item["content"], "source_refs": refs, "target_ids": targets,
        })
    return tuple(identities), canonical


def _decode(snapshot: object, *, episode_id: str, expected_agents: tuple[str, ...],
            expected_prompt_sha256: str) -> CollectiveObservation:
    if not isinstance(snapshot, dict) or snapshot.get("episode_id") != episode_id:
        raise CollectiveObservationError("cross-episode or invalid snapshot")
    prompt = snapshot.get("prompt")
    if not _valid_text(prompt) or not prompt.strip() or len(prompt) > 16_384:
        raise CollectiveObservationError("prompt provenance mismatch")
    if sha256(prompt.encode("utf-8")).hexdigest() != expected_prompt_sha256:
        raise CollectiveObservationError("prompt provenance mismatch")
    agents = _agents(snapshot.get("agents"))
    if agents != expected_agents:
        raise CollectiveObservationError("roster mismatch")
    answer_ids, answers = _contributions(
        snapshot.get("answers"), kind="answer", agents=agents, allowed_targets=set()
    )
    review_ids, reviews = _contributions(
        snapshot.get("reviews"), kind="review", agents=agents,
        allowed_targets=set(answer_ids),
    )
    missing = tuple(sorted(set(agents) - {value.removeprefix("answer:") for value in answer_ids}))
    if snapshot.get("missing_agents") != list(missing) or (
        type(snapshot.get("complete")) is not bool or snapshot["complete"] != (not missing)
    ):
        raise CollectiveObservationError("inconsistent completion claim")
    if missing and review_ids:
        raise CollectiveObservationError("peer review before all worker answers")
    # Rezon's actual CollectiveStore computes this from all immutable claims.
    basis = {"episode_id": episode_id, "prompt": prompt, "agents": agents,
             "contributions": sorted(answers + reviews, key=lambda v: (v["kind"], v["agent_id"]))}
    digest = _digest(basis)
    if snapshot.get("input_digest") != digest:
        raise CollectiveObservationError("contribution input digest mismatch")
    syntheses = snapshot.get("syntheses")
    if not isinstance(syntheses, list) or len(syntheses) > 32:
        raise CollectiveObservationError("invalid synthesis list")
    ids: list[str] = []
    for item in syntheses:
        if not isinstance(item, dict) or set(item) != {
            "synthesis_id", "integrator_id", "input_digest", "content", "status", "is_current"
        }:
            raise CollectiveObservationError("invalid synthesis envelope")
        if not isinstance(item["integrator_id"], str) or not _AGENT.fullmatch(item["integrator_id"]) or (
            not isinstance(item["input_digest"], str) or not _SHA.fullmatch(item["input_digest"])
        ) or item["synthesis_id"] != (
            f"synthesis:{item['input_digest']}:{item['integrator_id']}"
        ) or item["is_current"] is not (item["input_digest"] == digest) or (
            item["status"] != "unverified_model_synthesis"
        ) or not _valid_text(item["content"]) or not item["content"].strip():
            raise CollectiveObservationError("invalid or promoted synthesis")
        ids.append(item["synthesis_id"])
    if len(ids) != len(set(ids)) or (missing and any(item["is_current"] for item in syntheses)):
        raise CollectiveObservationError("duplicate or premature synthesis")
    return CollectiveObservation(
        episode_id, digest, agents, answer_ids, review_ids, tuple(ids), missing,
        "INCOMPLETE_UNKNOWN" if missing else "COMPLETE_UNVERIFIED",
    )


class LoopbackCollectiveObserver:
    """Non-mutating origin client; one total elapsed deadline, no redirects."""

    def __init__(self, *, port: int, read_token: str, timeout: float = 3.0) -> None:
        if type(port) is not int or not 1 <= port <= 65535 or (
            not isinstance(read_token, str) or not 16 <= len(read_token) <= 256
            or not read_token.isascii() or not read_token.isprintable()
            or any(ch.isspace() for ch in read_token)
        ) or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or (
            not 0 < timeout <= 20
        ):
            raise ValueError("bounded loopback port, token and timeout required")
        self._port = port
        self._token = read_token
        self._timeout = timeout

    def observe(self, episode_id: str, *, expected_agents: tuple[str, ...],
                expected_prompt_sha256: str) -> CollectiveObservation:
        if not isinstance(episode_id, str) or not _EPISODE.fullmatch(episode_id) or (
            not isinstance(expected_agents, tuple)
            or _agents(list(expected_agents)) != expected_agents
            or not isinstance(expected_prompt_sha256, str)
            or not _SHA.fullmatch(expected_prompt_sha256)
        ):
            raise CollectiveObservationError("exact episode and source expectations required")
        # `http.client` socket timeout is per blocking read. A peer could drip
        # arbitrarily small chunks forever. We require one monotonic wall-clock
        # budget for connect, send, headers, and entire bounded body.
        deadline = monotonic() + self._timeout

        def remaining() -> float:
            budget = deadline - monotonic()
            if budget <= 0:
                raise CollectiveObservationError("collective observation deadline exceeded")
            return budget

        request = (
            f"GET /v1/episodes/{episode_id}/state HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self._port}\r\n"
            f"Authorization: Bearer {self._token}\r\n"
            "Accept: application/json\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        try:
            with socket.create_connection(("127.0.0.1", self._port), timeout=remaining()) as peer:
                peer.settimeout(remaining())
                peer.sendall(request)
                pending = bytearray()
                while b"\r\n\r\n" not in pending:
                    if len(pending) > _MAX_HEADERS:
                        raise CollectiveObservationError("collective headers too large")
                    peer.settimeout(remaining())
                    block = peer.recv(4096)
                    if not block:
                        raise CollectiveObservationError("incomplete collective headers")
                    pending.extend(block)
                header_bytes, _, initial_body = pending.partition(b"\r\n\r\n")
                if len(header_bytes) > _MAX_HEADERS:
                    raise CollectiveObservationError("collective headers too large")
                lines = header_bytes.decode("ascii").split("\r\n")
                if not re.fullmatch(r"HTTP/1\.[01] 200(?: [^\r\n]*)?", lines[0]):
                    raise CollectiveObservationError("unauthorized or unavailable collective state")
                headers: dict[str, str] = {}
                for line in lines[1:]:
                    if ":" not in line:
                        raise CollectiveObservationError("invalid collective header")
                    key, val = line.split(":", 1)
                    key = key.strip().lower()
                    if not re.fullmatch(r"[a-z0-9-]+", key) or key in headers:
                        raise CollectiveObservationError("duplicate or invalid collective header")
                    headers[key] = val.strip()
                if headers.get("content-type", "").split(";", 1)[0] != "application/json" or (
                    not re.fullmatch(r"[0-9]+", headers.get("content-length", ""))
                ) or "transfer-encoding" in headers:
                    raise CollectiveObservationError("invalid collective response framing")
                length = int(headers["content-length"])
                if length > _MAX_BODY or len(initial_body) > length:
                    raise CollectiveObservationError("collective response too large or malformed")
                body = bytearray(initial_body)
                while len(body) < length:
                    peer.settimeout(remaining())
                    block = peer.recv(min(4096, length - len(body)))
                    if not block:
                        raise CollectiveObservationError("incomplete collective response")
                    body.extend(block)
                remaining()  # A last byte received at/after expiry is not success.
            snapshot = json.loads(body)
        except CollectiveObservationError:
            raise
        except (OSError, TimeoutError, UnicodeError, ValueError, RecursionError) as exc:
            raise CollectiveObservationError("collective observation unavailable") from exc
        return _decode(snapshot, episode_id=episode_id, expected_agents=expected_agents,
                       expected_prompt_sha256=expected_prompt_sha256)
