"""Source-only observer tests; Rezon remote-host independence is NOT certified."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import hmac
import json
import secrets
import unittest
from unittest.mock import patch

from vera_core.external_rezon_collective import (
    CollectiveObservationError,
    LoopbackCollectiveObserver,
)


EPISODE = "collective-" + "a" * 32
TOKEN = secrets.token_hex(32)
PROMPT = "Assess the unverified claim"
PROMPT_SHA = sha256(PROMPT.encode()).hexdigest()
AGENTS = ("alice", "bob")


def contribution(agent, kind, *, targets=()):
    return {
        "id": f"{kind}:{agent}", "agent_id": agent, "kind": kind,
        "content": f"{agent} made an unverified {kind} claim",
        "source_refs": [f"source:{agent}"], "target_ids": list(targets),
    }


def snapshot(*, complete=True, with_review=False, with_full_review=False,
             with_synthesis=False):
    answers = [contribution("alice", "answer")]
    if complete:
        answers.append(contribution("bob", "answer"))
    reviews = [contribution("alice", "review", targets=("answer:bob",))] if with_review else []
    if with_full_review:
        reviews = [
            contribution("alice", "review", targets=("answer:bob",)),
            contribution("bob", "review", targets=("answer:alice",)),
        ]
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
    def __init__(self, body, status=200, media_type="application/json", headers=None):
        self.status = status
        self.body = json.dumps(body).encode()
        self.media_type = media_type
        self.headers = headers or {}

    def wire(self):
        fields = {"Content-Type": self.media_type, "Content-Length": str(len(self.body)),
                  "Connection": "close", **self.headers}
        return (f"HTTP/1.1 {self.status} response\r\n" +
                "".join(f"{key}: {val}\r\n" for key, val in fields.items()) +
                "\r\n").encode() + self.body


class FakeSocket:
    response = FakeResponse(snapshot())
    calls = []
    challenge = "f" * 64
    epoch = "9" * 32
    issued_ms = 1000000
    spoof_proof = False
    spoof_preflight = False
    spoof_audience = False
    legacy_gateway = False

    @classmethod
    def create_connection(cls, address, *, timeout):
        cls.calls.append((address, timeout))
        return cls()

    def __init__(self):
        self.wire = b""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def settimeout(self, value):
        self.timeout = value

    def sendall(self, data):
        self.calls.append(data)
        if b"GET /v1/read-challenge " in data:
            if self.legacy_gateway:
                self.wire = FakeResponse({"error": "unauthorized"}, status=401).wire()
            else:
                lines = data.split(b"\r\n")
                path = next(line.split(b": ", 1)[1] for line in lines
                            if line.startswith(b"X-Rezon-State-Path:"))
                client_nonce = next(line.split(b": ", 1)[1].decode() for line in lines
                                    if line.startswith(b"X-Rezon-Client-Nonce:"))
                audience = "127.0.0.1:9999" if self.spoof_audience else "127.0.0.1:8899"
                context = (b"GET\0" + path + b"\0" + audience.encode() + b"\0"
                           + bytes.fromhex(self.challenge) + bytes.fromhex(client_nonce)
                           + self.issued_ms.to_bytes(8, "big") + bytes.fromhex(self.epoch))
                proof = hmac.new(bytes.fromhex(TOKEN),
                    b"rezon-state-read/preflight/v2\0" + context, sha256).hexdigest()
                if self.spoof_preflight:
                    proof = "0" * 64
                self.wire = FakeResponse({"server_nonce": self.challenge,
                                          "expires_in_ms": 10000,
                                          "audience": audience, "state_path": path.decode(),
                                          "client_nonce": client_nonce,
                                          "issued_ms": self.issued_ms,
                                          "epoch": self.epoch, "proof": proof}).wire()
            return
        auth_line = next((line for line in data.split(b"\r\n")
                          if line.startswith(b"Authorization: ")), b"")
        if not auth_line.startswith(b"Authorization: Rezon-Read-HMAC "):
            self.wire = FakeResponse({"error": "unauthorized"}, status=401).wire()
            return
        server_nonce, client_nonce, issued_text, epoch, request_mac = auth_line.split(
            b" ", 2)[-1].decode().split(".")
        path = data.split(b" ")[1]
        context = (b"GET\0" + path + b"\0" + b"127.0.0.1:8899\0"
                   + bytes.fromhex(server_nonce) + bytes.fromhex(client_nonce)
                   + int(issued_text).to_bytes(8, "big") + bytes.fromhex(epoch))
        expected_request = hmac.new(bytes.fromhex(TOKEN),
            b"rezon-state-read/request/v2\0" + context, sha256).hexdigest()
        if not hmac.compare_digest(request_mac, expected_request):
            self.wire = FakeResponse({"error": "invalid MAC"}, status=401).wire()
            return
        state = self.response
        response_proof = hmac.new(bytes.fromhex(TOKEN),
            b"rezon-state-read/response/v2\0" + context
            + sha256(state.body).digest(), sha256).hexdigest()
        if self.spoof_proof:
            response_proof = "0" * 64
        self.wire = FakeResponse(json.loads(state.body), status=state.status,
                                 media_type=state.media_type,
                                 headers={**state.headers,
                                          "X-Rezon-State-Proof": response_proof}).wire()

    def recv(self, limit):
        value, self.wire = self.wire[:limit], self.wire[limit:]
        return value


class FakeClock:
    def __init__(self):
        self.now = 10.0

    def monotonic(self):
        return self.now


class DripSocket(FakeSocket):
    clock = FakeClock()

    def recv(self, limit):
        self.clock.now += 0.49
        return super().recv(1)


class LoopbackCollectiveObserverTests(unittest.TestCase):
    def setUp(self):
        FakeSocket.calls = []
        FakeSocket.response = FakeResponse(snapshot())
        FakeSocket.spoof_proof = False
        FakeSocket.spoof_preflight = False
        FakeSocket.spoof_audience = False
        FakeSocket.legacy_gateway = False
        self.patch = patch("vera_core.external_rezon_collective.socket.create_connection",
                           FakeSocket.create_connection)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.observer = LoopbackCollectiveObserver(port=8899, read_token=TOKEN)

    def observe(self):
        return self.observer.observe(
            EPISODE, expected_agents=AGENTS,
            expected_prompt_sha256=PROMPT_SHA,
        )

    def test_one_worker_missing_remains_unknown_not_consensus(self):
        FakeSocket.response = FakeResponse(snapshot(complete=False))
        result = self.observe()
        self.assertEqual(result.state, "INCOMPLETE_UNKNOWN")
        self.assertEqual(result.missing_agents, ("bob",))
        self.assertFalse(result.execution_authorized or result.independent_hosts_verified)
        self.assertEqual(result.evidence_status, "UNVERIFIED_GATEWAY_CLAIM")
        self.assertEqual(result.round_state, "INITIAL_ANSWERS_INCOMPLETE")
        self.assertEqual(result.missing_review_agents, AGENTS)

    def test_first_answer_completion_does_not_claim_peer_review_or_synthesis(self):
        result = self.observe()
        self.assertEqual(result.state, "COMPLETE_UNVERIFIED")
        self.assertEqual(result.round_state, "PEER_REVIEW_INCOMPLETE")
        self.assertEqual(result.missing_review_agents, AGENTS)
        self.assertEqual(result.current_synthesis_ids, ())

    def test_current_synthesis_before_all_peer_reviews_is_not_full_round(self):
        FakeSocket.response = FakeResponse(snapshot(with_synthesis=True))
        result = self.observe()
        self.assertEqual(result.round_state, "PEER_REVIEW_INCOMPLETE")
        self.assertEqual(len(result.current_synthesis_ids), 1)
        self.assertEqual(result.missing_review_agents, AGENTS)
        self.assertFalse(result.execution_authorized)

    def test_full_peer_review_without_synthesis_is_not_full_round(self):
        FakeSocket.response = FakeResponse(snapshot(with_full_review=True))
        result = self.observe()
        self.assertEqual(result.round_state, "SYNTHESIS_NOT_OBSERVED")
        self.assertEqual(result.missing_review_agents, ())
        self.assertEqual(result.current_synthesis_ids, ())

    def test_stale_synthesis_does_not_count_as_current_synthesis(self):
        state = snapshot(with_full_review=True)
        stale_digest = "0" * 64
        state["syntheses"] = [{
            "synthesis_id": f"synthesis:{stale_digest}:integrator",
            "integrator_id": "integrator", "input_digest": stale_digest,
            "content": "Earlier provisional model answer",
            "status": "unverified_model_synthesis", "is_current": False,
        }]
        FakeSocket.response = FakeResponse(state)
        result = self.observe()
        self.assertEqual(result.round_state, "SYNTHESIS_NOT_OBSERVED")
        self.assertEqual(len(result.synthesis_ids), 1)
        self.assertEqual(result.current_synthesis_ids, ())

    def test_full_peer_review_and_current_synthesis_still_unverified(self):
        FakeSocket.response = FakeResponse(snapshot(
            with_full_review=True, with_synthesis=True,
        ))
        result = self.observe()
        self.assertEqual(result.round_state, "SYNTHESIS_PRESENT_UNVERIFIED")
        self.assertEqual(result.missing_review_agents, ())
        self.assertEqual(len(result.current_synthesis_ids), 1)
        self.assertFalse(result.execution_authorized or result.independent_hosts_verified)

    def test_two_worker_answers_review_and_synthesis_remain_unverified(self):
        FakeSocket.response = FakeResponse(
            snapshot(complete=True, with_review=True, with_synthesis=True)
        )
        result = self.observe()
        self.assertEqual(result.state, "COMPLETE_UNVERIFIED")
        self.assertEqual(set(result.answer_ids), {"answer:alice", "answer:bob"})
        self.assertEqual(result.review_ids, ("review:alice",))
        self.assertEqual(len(result.synthesis_ids), 1)
        self.assertEqual(result.round_state, "PEER_REVIEW_INCOMPLETE")
        self.assertEqual(result.missing_review_agents, ("bob",))
        self.assertFalse(result.execution_authorized)
        self.assertEqual(FakeSocket.calls[0][0], ("127.0.0.1", 8899))
        self.assertIn(f"GET /v1/episodes/{EPISODE}/state HTTP/1.1".encode(),
                      FakeSocket.calls[3])
        self.assertIn(b"Authorization: Rezon-Read-HMAC ", FakeSocket.calls[3])
        self.assertFalse(any(TOKEN.encode() in part for part in FakeSocket.calls
                             if isinstance(part, bytes)))

    def test_cross_episode_and_roster_claims_are_rejected(self):
        for mutation in (
            lambda state: state.update(episode_id="collective-" + "b" * 32),
            lambda state: state.update(agents=["alice", "charlie"]),
            lambda state: state.update(prompt="different prompt"),
        ):
            with self.subTest(mutation=mutation):
                state = snapshot()
                mutation(state)
                FakeSocket.response = FakeResponse(state)
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
                FakeSocket.response = FakeResponse(state)
                with self.assertRaises(CollectiveObservationError):
                    self.observe()

    def test_failed_and_redirected_authentication_never_get_promoted(self):
        for status in (302, 401, 403, 503):
            with self.subTest(status=status):
                FakeSocket.response = FakeResponse(snapshot(), status=status)
                with self.assertRaises(CollectiveObservationError):
                    self.observe()

    def test_old_gateway_and_spoofed_local_port_fail_before_trust(self):
        FakeSocket.legacy_gateway = True
        with self.assertRaises(CollectiveObservationError):
            self.observe()
        self.assertEqual(len(FakeSocket.calls), 2)  # no read request was issued
        FakeSocket.legacy_gateway = False
        FakeSocket.spoof_audience = True
        with self.assertRaisesRegex(CollectiveObservationError, "unsupported gateway"):
            self.observe()
        self.assertEqual(len(FakeSocket.calls), 4)  # still no signed read request
        FakeSocket.spoof_audience = False
        FakeSocket.spoof_preflight = True
        with self.assertRaisesRegex(CollectiveObservationError, "preflight proof"):
            self.observe()
        FakeSocket.spoof_preflight = False
        FakeSocket.spoof_proof = True
        with self.assertRaisesRegex(CollectiveObservationError, "not authenticated"):
            self.observe()

    def test_nonnumeric_port_short_token_and_foreign_episode_are_denied(self):
        for port in (0, 65536, True, "8000"):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    LoopbackCollectiveObserver(port=port, read_token=TOKEN)
        with self.assertRaises(ValueError):
            LoopbackCollectiveObserver(port=8000, read_token="short")
        with self.assertRaises(CollectiveObservationError):
            self.observer.observe("../../other", expected_agents=AGENTS,
                                  expected_prompt_sha256=PROMPT_SHA)

    def test_malformed_untrusted_refs_fail_as_controlled_error(self):
        state = snapshot()
        state["answers"][0]["source_refs"] = [["unhashable"]]
        FakeSocket.response = FakeResponse(state)
        with self.assertRaises(CollectiveObservationError):
            self.observe()

    def test_drip_feed_exceeding_total_deadline_is_rejected(self):
        """Each byte arrives under the per-recv timeout; total time still fails."""
        clock = FakeClock()
        DripSocket.clock = clock
        DripSocket.response = FakeResponse(snapshot())
        with patch("vera_core.external_rezon_collective.socket.create_connection",
                   DripSocket.create_connection), patch(
                   "vera_core.external_rezon_collective.monotonic", clock.monotonic):
            watcher = LoopbackCollectiveObserver(port=8899, read_token=TOKEN,
                                                 timeout=1.0)
            with self.assertRaisesRegex(CollectiveObservationError,
                                        "deadline exceeded"):
                watcher.observe(EPISODE, expected_agents=AGENTS,
                                expected_prompt_sha256=PROMPT_SHA)
        self.assertGreater(clock.now - 10.0, 1.0)

    def test_duplicate_header_and_bad_framing_fail_closed(self):
        for headers in ({"Transfer-Encoding": "chunked"},
                        {"Content-Length": "999999999999999"}):
            with self.subTest(headers=headers):
                FakeSocket.response = FakeResponse(snapshot(), headers=headers)
                with self.assertRaises(CollectiveObservationError):
                    self.observe()

    def test_escaped_lone_surrogate_claims_are_controlled_errors(self):
        for mutate in (
            lambda state: state.update(prompt="bad\ud800prompt"),
            lambda state: state["answers"][0].update(content="bad\ud800answer"),
            lambda state: state["answers"][0].update(source_refs=["bad\ud800ref"]),
            lambda state: state["syntheses"][0].update(content="bad\ud800synthesis"),
        ):
            with self.subTest(mutate=mutate):
                state = snapshot(with_synthesis=True)
                mutate(state)
                FakeSocket.response = FakeResponse(state)
                with self.assertRaises(CollectiveObservationError):
                    self.observe()


if __name__ == "__main__":
    unittest.main()
