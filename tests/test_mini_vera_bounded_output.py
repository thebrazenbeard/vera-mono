"""Bounded local output sizes stay source-validated and hash-bound."""
import unittest

from tools.mini_vera import compose, local_session, loopback


class BoundedOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity, cls.identity_raw = compose.read_object(compose.IDENTITY_PATH, 16384)
        cls.behavior, cls.behavior_raw = compose.read_object(compose.BEHAVIOR_PATH, 16384)

    def candidate(self, count):
        state, key = local_session.empty_public_state()
        return local_session.compose_local_turn(
            text="Hello Vera", turn_id="synthetic-test-1", history=[],
            identity=self.identity, identity_raw=self.identity_raw,
            behavior=self.behavior, behavior_raw=self.behavior_raw,
            state=state, key=key, revision=0,
            model="qwen3.5:0.8b", model_digest="a" * 64,
            num_predict=count)

    def test_extended_256_is_hash_bound_and_validated(self):
        request = self.candidate(256)
        self.assertEqual(request["inference"]["options"]["num_predict"], 256)
        payload, digest = loopback.validate_candidate(request)
        self.assertEqual(payload["max_tokens"], 256)
        self.assertEqual(digest, compose.sha256(compose.canonical(payload)))
        self.assertEqual(request["request_sha256"],
                         compose.sha256(compose.canonical(request["inference"])))

    def test_original_128_remains_compatible(self):
        request = self.candidate(128)
        loopback.validate_candidate(request)

    def test_invalid_size_refused_by_composer(self):
        for value in (0, 257, 4096, True, "256"):
            with self.subTest(value=value):
                with self.assertRaises(compose.CompositionRejected):
                    self.candidate(value)

    def test_rehashed_unbounded_request_still_refused(self):
        request = self.candidate(256)
        request["inference"]["options"]["num_predict"] = 4096
        request["request_sha256"] = compose.sha256(
            compose.canonical(request["inference"]))
        with self.assertRaises(loopback.LoopbackRejected):
            loopback.validate_candidate(request)


if __name__ == "__main__":
    unittest.main()
