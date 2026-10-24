"""Research networkless Docker learner cell security-policy unit tests."""
from __future__ import annotations

import hashlib
import json
import subprocess
from types import SimpleNamespace
import unittest

from research.goal1_acceptance_bridge.networkless_learner_cell import (
    IsolationFailure, build_command, run_networkless_learner_step,
)

IMAGE = "sha256:" + "a" * 64


class LearnerCellPolicyTests(unittest.TestCase):
    def test_docker_policy_uses_immutable_offline_image_and_no_network(self):
        args = build_command(IMAGE)
        self.assertEqual(args[:2], ["docker", "run"])
        for token in ("--network=none", "--read-only", "--cap-drop=ALL",
                      "--security-opt=no-new-privileges", "--user=65534:65534",
                      "--pull=never", "--ipc=private",
                      "--pids-limit=32", "--memory=128m", "--cpus=0.5"):
            self.assertIn(token, args)
        self.assertNotIn("--privileged", args)
        self.assertNotIn("--network=host", args)
        self.assertFalse(any(item.startswith("--pid=") for item in args),
                         "Docker default private PID mode; host sharing forbidden")
        self.assertFalse(any(arg.startswith(("--mount", "--volume", "--device", "--gpus",
                                             "--env", "--publish")) for arg in args))
        self.assertIn(IMAGE, args)

    def test_no_tags_or_untrusted_docker_arguments(self):
        for image in ("python:3.11-slim", "sha256:" + "g"*64,
                      IMAGE + " --network=host", "", None):
            with self.subTest(image=image), self.assertRaises(ValueError):
                build_command(image)

    def runner_for(self, *, checks=None, interfaces=None, extra=None, exit_code=0):
        def run(cmd, **kwargs):
            self.assertIn("--network=none", cmd)
            request = json.loads(kwargs["input"])
            record = {
                "schema": "GOAL1_NETWORKLESS_LEARNER_REQUEST_V1",
                "nonce": request["nonce"],
                "prompt_sha256": hashlib.sha256(request["prompt"].encode()).hexdigest(),
                "network_interfaces": ["lo"] if interfaces is None else interfaces,
                "network_checks": (
                    {"container_loopback":"DENIED_OR_UNAVAILABLE",
                     "docker_bridge_gateway":"DENIED_OR_UNAVAILABLE"}
                    if checks is None else checks),
                "proposal":"REQUEST_GATEWAY_INFERENCE",
                "qualified":False,
            }
            if extra is not None:
                record.update(extra)
            return SimpleNamespace(returncode=exit_code, stdout=json.dumps(record),
                                   stderr="")
        return run

    def test_good_sandbox_only_requests_host_callback_not_qualification(self):
        called = []
        outcome = run_networkless_learner_step(
            image_id=IMAGE, prompt="research prompt",
            gateway_callback=lambda text: called.append(text) or {"status":"SYNTHETIC"},
            runner=self.runner_for())
        self.assertEqual(called, ["research prompt"])
        self.assertTrue(outcome.isolation_observed)
        self.assertTrue(outcome.host_gateway_callback_called)
        self.assertFalse(outcome.gateway_effect_independently_verified)
        self.assertFalse(outcome.actual_selected_qvr_route_verified)
        self.assertFalse(outcome.learning_qualified)

    def test_raw_provider_reachable_cannot_trigger_gateway(self):
        called = []
        with self.assertRaises(IsolationFailure):
            run_networkless_learner_step(
                image_id=IMAGE, prompt="x",gateway_callback=lambda x: called.append(x),
                runner=self.runner_for(checks={
                    "container_loopback":"REACHABLE",
                    "docker_bridge_gateway":"DENIED_OR_UNAVAILABLE"}))
        self.assertEqual(called, [])

    def test_extra_network_interface_cannot_trigger_gateway(self):
        called = []
        with self.assertRaises(IsolationFailure):
            run_networkless_learner_step(
                image_id=IMAGE,prompt="x",gateway_callback=lambda x: called.append(x),
                runner=self.runner_for(interfaces=["eth0","lo"]))
        self.assertEqual(called, [])

    def test_forged_nonce_and_qualified_flags_cannot_trigger_gateway(self):
        for extra in ({"nonce":"forged"}, {"qualified":True},
                      {"schema":"WRONG"}, {"prompt_sha256":"a"*64},
                      {"unexpected":"field"}):
            with self.subTest(extra=extra):
                called=[]
                with self.assertRaises(IsolationFailure):
                    run_networkless_learner_step(
                        image_id=IMAGE,prompt="x",gateway_callback=lambda x: called.append(x),
                        runner=self.runner_for(extra=extra))
                self.assertEqual(called, [])

    def test_worker_failure_and_timeout_fail_closed(self):
        called=[]
        with self.assertRaises(IsolationFailure):
            run_networkless_learner_step(
                image_id=IMAGE,prompt="x",gateway_callback=lambda x: called.append(x),
                runner=self.runner_for(exit_code=3))
        def timed_out(*a, **kw):
            raise subprocess.TimeoutExpired("docker",15)
        with self.assertRaises(IsolationFailure):
            run_networkless_learner_step(
                image_id=IMAGE,prompt="x",gateway_callback=lambda x: called.append(x),
                runner=timed_out)
        self.assertEqual(called, [])

    def test_invalid_request_rejected_without_launch(self):
        def fail(*a,**k):
            raise AssertionError("not supposed to run Docker")
        for prompt in ("", "x"*12001, None):
            with self.assertRaises(ValueError):
                run_networkless_learner_step(
                    image_id=IMAGE,prompt=prompt,gateway_callback=lambda x: None,
                    runner=fail)
        with self.assertRaises(TypeError):
            run_networkless_learner_step(
                image_id=IMAGE,prompt="valid",gateway_callback=None,runner=fail)


if __name__ == "__main__":
    unittest.main()
