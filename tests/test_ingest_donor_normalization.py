import unittest

from ingest.normalization import NormalizationError, normalize_bytes, sniff_media_type


class NormalizationTests(unittest.TestCase):
    def test_text_normalization_is_nfc_and_lf_without_stripping(self):
        raw = "Cafe\u0301\r\nline 2  \r".encode("utf-8")
        normalized = normalize_bytes(raw, "text/plain")
        self.assertEqual(normalized, "Café\nline 2  \n".encode("utf-8"))

    def test_json_is_canonicalized(self):
        raw = b'{"z": 2, "a": [3, 1]}'
        self.assertEqual(normalize_bytes(raw, "application/json"), b'{"a":[3,1],"z":2}')
        self.assertEqual(sniff_media_type(raw), "application/json")

    def test_invalid_json_fails_as_json(self):
        with self.assertRaises(NormalizationError):
            normalize_bytes(b'{"bad":', "application/json")


if __name__ == "__main__":
    unittest.main()
