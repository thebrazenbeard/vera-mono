"""Source-only observer tests; Rezon remote-host independence is NOT certified."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from vera_core.external_rezon_collective import (
    CollectiveObservationError,
    LoopbackCollectiveObserver,
)


EPISODE = "collective-" + "a" * 32
TOKEN = "a-strong-admin-token-for-loopback"
PROMPT = "Assess the unverified claim"
PROMPT_SHA = sha256(PROMPT.encode()).hexdigest()
AGENTS = ("alice", "bob")


def contribution(agent, kind, *, targets=()):
    return {
        "id": f"{kind}:{agent}", "agent_id": agent, "kind": kind,
        "content": f"{agent} made an unverified {kind} claim",
        "source_refs": [f"source:{agent}"], "target_ids": list(targets),
    }


def snapshot(*, complete=True, with_review=False, with_synthesis=False):
    answers = [contribution("alice", "answer")]
    if complete:
        answers.append(contribution("bob", "answer"))
    reviews = [contribution("alice", "review", targets=("answer:bob",))] if with_review else []
    claims = [
        {
            "contribution_id": row["id"], "agent_id": row["agent_id"],
            "kind": row["kind"], "content": row["content"],
            "source_refs": row["source_refs"], "target_ids": row["target_ids"],
        }
        for row in (answers + reviews)
    ]
    basis = {"episode_id": EPISODE, "prompt": PROMPT, "agents": AGENTS,
             "contributions": claims}
    digest = sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False,
                               separators=(",", ":")).encode()).hexdigest()
    syntheses = []
    if with_synthesis:
        syntheses = [{
            "synthesis_id": f"synthesis:{digest}:integrator", "integrator_id": "integrator",
            "input_digest": digest, "content": "Provisional answer, not independently verified",
            "status": "unverified_model_synthesis", "is_current": True,
        }]
    return {
        "episode_id": EPISODE, "prompt": PROMPT, "agents": list(AGENTS),
        "answers": answers, "reviews": reviews, "syntheses": syntheses,
        "missing_agents": [] if complete else ["bob"],
        "complete": complete, "input_digest": digest,
    }


class FakeResponse:
    def __init__(self, body, status=200, media_type="application/json"):
        self.status = status
        self.body = json.dumps(body).encode()
        self.media_type = media_type

    def getheader(self, name, default=None):
        return self.media_type if name == "Content-Type" else default

    def read(self, limit):
        return self.body[:limit]


class FakeConnection:
    response = FakeResponse(snapshot())
    calls = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout

    def request(self, method, route, headers):
        self.calls.append((self.host, self.port, method, route, headers))

    def getresponse(self):
        return self.response

    def close(self):
        pass


class LoopbackCollectiveObserverTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.calls = []
        FakeConnection.response = FakeResponse(snapshot())
        self.patch = patch("vera_core.external_rezon_collective.HTTPConnection", FakeConnection)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.observer = LoopbackCollectiveObserver(port=8899, admin_token=TOKEN)

    def observe(self):
        return self.observer.observe(
            EPISODE, expected_agents=AGENTS,
            expected_prompt_sha256=PROMPT_SHA,
        )

    def test_one_worker_missing_remains_unknown_not_consensus(self):
        FakeConnection.response = FakeResponse(snapshot(complete=False))
        result = self.observe()
        self.assertEqual(result.state, "INCOMPLETE_UNKNOWN")
        self.assertEqual(result.missing_agents, ("bob",))
        self.assertFalse(result.execution_authorized or result.independent_hosts_verified)
        self.assertEqual(result.evidence_status, "UNVERIFIED_GATEWAY_CLAIM")

    def test_two_worker_answers_review_and_synthesis_remain_unverified(self):
        FakeConnection.response = FakeResponse(
            snapshot(complete=True, with_review=True, with_synthesis=True)
        )
        result = self.observe()
        self.assertEqual(result.state, "COMPLETE_UNVERIFIED")
        self.assertEqual(set(result.answer_ids), {"answer:alice", "answer:bob"})
        self.assertEqual(result.review_ids, ("review:alice",))
        self.assertEqual(len(result.synthesis_ids), 1)
        self.assertFalse(result.execution_authorized)
        self.assertEqual(FakeConnection.calls[0][:4], (
            "127.0.0.1", 8899, "GET", f"/v1/episodes/{EPISODE}/state"
        ))
        self.assertEqual(FakeConnection.calls[0][4]["Authorization"], f"Bearer {TOKEN}")

    def test_cross_episode_and_roster_claims_are_rejected(self):
        for mutation in (
            lambda state: state.update(episode_id="collective-" + "b" * 32),
            lambda state: state.update(agents=["alice", "charlie"]),
            lambda state: state.update(prompt="different prompt"),
        ):
            with self.subTest(mutation=mutation):
                state = snapshot()
                mutation(state)
                FakeConnection.response = FakeResponse(state)
                with self.assertRaises(CollectiveObservationError):
                    self.observe()

    def test_replay_collision_and_forged_contribution_digest_are_rejected(self):
        for mutation in (
            lambda state: state["answers"].append(deepcopy(state["answers"][0])),
            lambda state: state["answers"][0].update(content="tampered text"),
            lambda state: state.update(input_digest="0" * 64),
            lambda state: state["reviews"].append(
                contribution("alice", "review", targets=("answer:alice",))
            ),
        ):
            with self.subTest(mutation=mutation):
                state = snapshot(complete=True)
                mutation(state)
                FakeConnection.response = FakeResponse(state)
                with self.assertRaises(CollectiveObservationError):
                    self.observe()

    def test_failed_and_redirected_authentication_never_get_promoted(self):
        for status in (302, 401, 403, 503):
            with self.subTest(status=status):
                FakeConnection.response = FakeResponse(snapshot(), status=status)
                with self.assertRaises(CollectiveObservationError):
                    self.observe()

    def test_nonnumeric_port_short_token_and_foreign_episode_are_denied(self):
        for port in (0, 65536, True, "8000"):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    LoopbackCollectiveObserver(port=port, admin_token=TOKEN)
        with self.assertRaises(ValueError):
            LoopbackCollectiveObserver(port=8000, admin_token="short")
        with self.assertRaises(CollectiveObservationError):
            self.observer.observe("../../other", expected_agents=AGENTS,
                                  expected_prompt_sha256=PROMPT_SHA)

    def test_malformed_untrusted_refs_fail_as_controlled_error(self):
        state = snapshot()
        state["answers"][0]["source_refs"] = [["unhashable"]]
        FakeConnection.response = FakeResponse(state)
        with self.assertRaises(CollectiveObservationError):
            self.observe()


if __name__ == "__main__":
    unittest.main()
