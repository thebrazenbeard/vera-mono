import unittest

from ingest.canonical import canonical_digest, canonical_json


class CanonicalTests(unittest.TestCase):
    def test_canonical_json_and_digest_ignore_mapping_order(self):
        left = {"b": 2, "a": {"y": 2, "x": 1}}
        right = {"a": {"x": 1, "y": 2}, "b": 2}
        self.assertEqual(canonical_json(left), canonical_json(right))
        self.assertEqual(canonical_digest(left), canonical_digest(right))


if __name__ == "__main__":
    unittest.main()
