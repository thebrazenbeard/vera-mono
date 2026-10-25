"""One gateway invocation must never trigger overlapping backend generations."""
from __future__ import annotations

from threading import Event, Thread
from types import SimpleNamespace
import unittest

from research.goal1_acceptance_bridge.gateway_terminal_text_bridge import (
    CapturingBackend,
    GatewayTextHold,
)


class CapturingBackendConcurrencyTest(unittest.TestCase):
    def test_capturing_backend_rejects_second_call_while_first_is_in_flight(self):
        entered = Event()
        release = Event()
        calls = []
        results = []

        class SlowBackend:
            def generate(self, prompt, *, model, max_tokens):
                calls.append((prompt, model, max_tokens))
                entered.set()
                if not release.wait(3):
                    raise AssertionError("test must release first backend request")
                return SimpleNamespace(text="synthetic", model=model)

        capture = CapturingBackend(SlowBackend())

        def invoke():
            try:
                results.append(capture.generate("prompt", model="test", max_tokens=3))
            except GatewayTextHold as exc:
                results.append(exc)

        first = Thread(target=invoke)
        second = Thread(target=invoke)
        first.start()
        self.assertTrue(entered.wait(3), "first generation did not enter delegate")
        second.start()
        try:
            # A correctly fenced second caller is rejected without waiting for
            # the model provider to finish the first slow generation.
            second.join(timeout=1)
            self.assertFalse(second.is_alive(), "second generation was not rejected promptly")
        finally:
            release.set()
            first.join(timeout=3)
            second.join(timeout=3)

        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(calls, [("prompt", "test", 3)])
        self.assertEqual(len(capture.observations), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(isinstance(value, GatewayTextHold) for value in results), 1)

    def test_backend_failure_consumes_one_shot_permit(self):
        calls = []

        class FailingBackend:
            def generate(self, prompt, *, model, max_tokens):
                calls.append(prompt)
                raise TimeoutError("ambiguous provider outcome")

        capture = CapturingBackend(FailingBackend())
        with self.assertRaises(TimeoutError):
            capture.generate("first", model="test", max_tokens=3)
        with self.assertRaises(GatewayTextHold):
            capture.generate("retry", model="test", max_tokens=3)
        self.assertEqual(calls, ["first"])


if __name__ == "__main__":
    unittest.main()
