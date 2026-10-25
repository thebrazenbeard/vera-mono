"""Opt-in read-only observation of Rezon's authenticated loopback collective.

An HTTP response is a gateway *claim*, never an independent-host attestation,
verified answer, quorum decision, or permission to execute an action.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from http.client import HTTPConnection, HTTPException
import json
import re


_EPISODE = re.compile(r"collective-[0-9a-f]{32}\Z")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BODY = 1_000_000


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
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


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
        if not isinstance(item["content"], str) or not item["content"].strip() or (
            len(item["content"]) > 32_768
        ):
            raise CollectiveObservationError("invalid contribution content")
        refs, targets = item["source_refs"], item["target_ids"]
        if not all(isinstance(v, list) and len(v) <= 32
                   and all(isinstance(s, str) and 0 < len(s) <= 1024 for s in v)
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
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16_384 or (
        sha256(prompt.encode("utf-8")).hexdigest() != expected_prompt_sha256
    ):
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
        ) or not isinstance(item["content"], str) or not item["content"].strip():
            raise CollectiveObservationError("invalid or promoted synthesis")
        ids.append(item["synthesis_id"])
    if len(ids) != len(set(ids)) or (missing and any(item["is_current"] for item in syntheses)):
        raise CollectiveObservationError("duplicate or premature synthesis")
    return CollectiveObservation(
        episode_id, digest, agents, answer_ids, review_ids, tuple(ids), missing,
        "INCOMPLETE_UNKNOWN" if missing else "COMPLETE_UNVERIFIED",
    )


class LoopbackCollectiveObserver:
    """Non-mutating origin client; `GET /state` only, no retries or redirects."""

    def __init__(self, *, port: int, admin_token: str, timeout: float = 3.0) -> None:
        if type(port) is not int or not 1 <= port <= 65535 or (
            not isinstance(admin_token, str) or not 16 <= len(admin_token) <= 256
            or not admin_token.isascii() or not admin_token.isprintable()
            or any(ch.isspace() for ch in admin_token)
        ) or isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or (
            not 0 < timeout <= 20
        ):
            raise ValueError("bounded loopback port, token and timeout required")
        self._port = port
        self._token = admin_token
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
        connection = HTTPConnection("127.0.0.1", self._port, timeout=self._timeout)
        try:
            connection.request(
                "GET", f"/v1/episodes/{episode_id}/state",
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200 or response.getheader("Content-Type", "").split(";")[0] != "application/json":
                raise CollectiveObservationError("unauthorized or unavailable collective state")
            body = response.read(_MAX_BODY + 1)
            if len(body) > _MAX_BODY:
                raise CollectiveObservationError("collective response too large")
            snapshot = json.loads(body)
        except (OSError, HTTPException, TimeoutError, UnicodeError, ValueError, RecursionError) as exc:
            raise CollectiveObservationError("collective observation unavailable") from exc
        finally:
            connection.close()
        return _decode(snapshot, episode_id=episode_id, expected_agents=expected_agents,
                       expected_prompt_sha256=expected_prompt_sha256)
