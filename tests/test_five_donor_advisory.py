"""Offline hostile tests for opt-in five-repo cognition boundary."""
from __future__ import annotations

import json
import unittest

from vera_core.five_donor_advisory import (
    DONORS, CognitiveAdvisory, DonorBinding, DonorBoundaryError,
    SourceReadback, SourceRef, collect_five_donor_advisory,
)


class FiveDonorBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.values = [0.8, "INSPECT", True, "TASK_DIRECT", "INSPECT_OPTION"]
        self.bindings = tuple(
            DonorBinding(
                SourceRef(name, f"thebrazenbeard/{name}", f"{i + 1:040x}",
                          f"src/{name.replace('-', '_')}.py", f"{i + 1:064x}"),
                lambda text, index=i: self._donor(index, text),
            ) for i, name in enumerate(DONORS)
        )

    def _donor(self, index, text):
        self.calls.append(("donor", index, text))
        return self.values[index]

    def _readback(self, expected):
        self.calls.append(("readback", expected.donor))
        return SourceReadback(expected.repository, expected.commit_sha,
                              expected.source_path, expected.blob_sha256)

    def test_default_off_never_calls_callbacks_or_parses_task(self):
        result = collect_five_donor_advisory("", enabled=False,
                                           bindings=self.bindings,
                                           readback=self._readback)
        self.assertEqual(result.status, "DISABLED")
        self.assertEqual(result.untrusted_prompt_data(), "")
        self.assertEqual(result.authority, "NONE")
        self.assertEqual(self.calls, [])

    def test_real_host_invocation_is_candidate_only(self):
        result = collect_five_donor_advisory(
            "synthetic inspect", enabled=True, bindings=self.bindings,
            readback=self._readback)
        self.assertEqual(result.status, "CANDIDATE_ONLY")
        self.assertEqual(result.memory_admission, "NONE")
        self.assertEqual(result.model_identity, "UNQUALIFIED")
        self.assertEqual(result.source_proof, "HOST_CALLBACK_REPORTED_ONLY")
        self.assertEqual(len(result.bindings), 5)
        self.assertEqual(len(result.signals), 5)
        self.assertEqual(dict(result.signals)["preactive_focus"], "INSPECT_OPTION")
        self.assertEqual(json.loads(result.untrusted_prompt_data())["classification"],
                         "UNVERIFIED_COGNITIVE_ADVISORY_DATA")
        self.assertEqual([call[0] for call in self.calls], ["readback"] * 5 + ["donor"] * 5)

    def test_mismatched_readback_blocks_all_donor_execution(self):
        def bad_readback(source):
            receipt = self._readback(source)
            if source.donor == "pre-active":
                return SourceReadback(receipt.repository, receipt.commit_sha,
                                      receipt.source_path, "f" * 64)
            return receipt
        with self.assertRaisesRegex(DonorBoundaryError, "readback mismatch"):
            collect_five_donor_advisory("synthetic", enabled=True,
                                        bindings=self.bindings, readback=bad_readback)
        self.assertFalse(any(call[0] == "donor" for call in self.calls))

    def test_boolean_fake_attestation_does_not_pass(self):
        with self.assertRaisesRegex(DonorBoundaryError, "readback mismatch"):
            collect_five_donor_advisory("synthetic", enabled=True,
                                        bindings=self.bindings, readback=lambda _: True)

    def test_forged_comparator_cannot_bypass_source_digest(self):
        class AlwaysEqual:
            def __eq__(self, _other):
                return True
        def hostile(source):
            return SourceReadback(source.repository, source.commit_sha,
                                  source.source_path, AlwaysEqual())
        with self.assertRaisesRegex(DonorBoundaryError, "readback mismatch"):
            collect_five_donor_advisory("synthetic", enabled=True,
                                        bindings=self.bindings, readback=hostile)
        self.assertFalse(any(row[0] == "donor" for row in self.calls))

    def test_missing_or_reordered_source_fails(self):
        with self.assertRaises(DonorBoundaryError):
            collect_five_donor_advisory("synthetic", enabled=True,
                                        bindings=self.bindings[:-1], readback=self._readback)
        wrong = (self.bindings[1], self.bindings[0], *self.bindings[2:])
        with self.assertRaisesRegex(DonorBoundaryError, "order"):
            collect_five_donor_advisory("synthetic", enabled=True,
                                        bindings=wrong, readback=self._readback)

    def test_wrong_repository_and_source_path_rejected(self):
        wrong = DonorBinding(
            SourceRef("noema", "other/noema", "1" * 40, "../escape.py", "2" * 64),
            lambda _: 0.8)
        with self.assertRaises(DonorBoundaryError):
            collect_five_donor_advisory("synthetic", enabled=True,
                                        bindings=(wrong, *self.bindings[1:]),
                                        readback=self._readback)

    def test_nonfinite_and_bool_disguised_as_number_rejected(self):
        for item in (float("nan"), float("inf"), True, -1, 2):
            with self.subTest(value=item):
                self.values[0] = item
                with self.assertRaisesRegex(DonorBoundaryError, "finite"):
                    collect_five_donor_advisory("synthetic", enabled=True,
                                                bindings=self.bindings,
                                                readback=self._readback)

    def test_nonliteral_opt_in_and_task_control_rejected(self):
        for enabled in ("true", 1, None):
            with self.assertRaisesRegex(DonorBoundaryError, "literal boolean"):
                collect_five_donor_advisory("synthetic", enabled=enabled)
        with self.assertRaisesRegex(DonorBoundaryError, "control"):
            collect_five_donor_advisory("synthetic\x1b", enabled=True,
                                        bindings=self.bindings, readback=self._readback)
        with self.assertRaisesRegex(DonorBoundaryError, "Unicode"):
            collect_five_donor_advisory("bad\ud800", enabled=True,
                                        bindings=self.bindings, readback=self._readback)
        self.assertFalse(any(row[0] == "donor" for row in self.calls))

    def test_same_referent_stop_vetoes_candidate(self):
        self.values = [0.8, "HOLD", False, "STOP_PLAY", "STOP_PLAY"]
        result = collect_five_donor_advisory("stop", enabled=True,
                                            bindings=self.bindings, readback=self._readback)
        self.assertEqual(dict(result.signals)["preactive_focus"], "STOP_PLAY")
        self.values[2] = True
        with self.assertRaisesRegex(DonorBoundaryError, "veto"):
            collect_five_donor_advisory("stop", enabled=True,
                                        bindings=self.bindings, readback=self._readback)
        self.values = [0.8, "INSPECT", True, "TASK_DIRECT", "STOP_PLAY"]
        with self.assertRaisesRegex(DonorBoundaryError, "veto"):
            collect_five_donor_advisory("stop", enabled=True,
                                        bindings=self.bindings, readback=self._readback)


if __name__ == "__main__":
    unittest.main()
