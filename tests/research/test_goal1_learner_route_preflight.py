"""Non-effectful raw-provider-bypass falsifier tests; no model is executed."""
import errno
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path

from research.goal1_gateway.learner_route_preflight import (
    LOOPBACK, RouteProbe, main, probe_raw_provider_socket,
)

ROOT = Path(__file__).resolve().parents[2]


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class RoutePreflightTests(unittest.TestCase):
    def test_tcp_access_downgrades_to_fail_without_http_or_model(self):
        conn = FakeConnection()
        seen = []

        def dial(address, *, timeout):
            seen.append((address, timeout))
            return conn

        observed = probe_raw_provider_socket(dial=dial)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], (LOOPBACK, 11434))
        self.assertTrue(conn.closed)
        self.assertEqual(observed.tcp_observation, "TCP_REACHABLE")
        self.assertFalse(observed.sole_route_qualified)
        self.assertFalse(observed.denied_direct_model_inference_verified)
        self.assertFalse(observed.evaluation_claim_authorized)

    def test_refused_socket_does_not_falsely_qualify(self):
        def refused(*args, **kwargs):
            raise ConnectionRefusedError(errno.ECONNREFUSED, "connection refused")

        observed = probe_raw_provider_socket(dial=refused)
        self.assertEqual(observed.tcp_observation, "TCP_REFUSED")
        self.assertFalse(observed.sole_route_qualified)
        self.assertFalse(observed.actual_selected_learner_identity_verified)

    def test_timeout_and_ambiguous_network_error_both_hold(self):
        for error in (TimeoutError(), OSError(errno.ENETUNREACH, "unreachable")):
            with self.subTest(error=repr(error)):
                def failing(*args, **kwargs):
                    raise error
                observed = probe_raw_provider_socket(dial=failing)
                self.assertEqual(observed.tcp_observation, "INCONCLUSIVE")
                self.assertFalse(observed.sole_route_qualified)

    def test_rejects_unbounded_or_invalid_probe(self):
        for kwargs in ({"port": 0}, {"port": True}, {"timeout": 1.5},
                       {"timeout": 0}, {"dial": object()}):
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                probe_raw_provider_socket(**kwargs)

    def test_real_disposable_listener_only_reports_tcp_no_model(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((LOOPBACK, 0))
            listener.listen(1)
            probe = probe_raw_provider_socket(port=listener.getsockname()[1])
            self.assertEqual(probe.tcp_observation, "TCP_REACHABLE")
            self.assertFalse(probe.denied_direct_model_inference_verified)
            self.assertTrue(probe.pid > 0)
            self.assertEqual(probe.schema, "VERA_GOAL1_LEARNER_RAW_PROVIDER_PREFLIGHT_V1")
            self.assertIsInstance(json.dumps(probe.as_dict()), str)

    def test_no_argument_cli_is_strict_hold_regardless_of_connectivity(self):
        # CLI is designed to return 2 even when socket fails to connect.
        self.assertTrue(callable(main))
        with self.assertRaises(SystemExit):
            main(["--pretend-denied"])

    def test_no_credentials_model_inference_or_gateway_provisioning(self):
        # A regression guard against turning this preflight into a model POST.
        src = (ROOT / "research/goal1_gateway/learner_route_preflight.py").read_text()
        self.assertNotIn("/api/generate", src)
        self.assertNotIn("POST", src.split("def probe_raw_provider_socket(", 1)[1].split("def main(", 1)[0])
        self.assertNotIn("client_cert", src)
        self.assertNotIn("firewall", src.split("def probe_raw_provider_socket(", 1)[1].split("def main(", 1)[0])


if __name__ == "__main__":
    unittest.main()
