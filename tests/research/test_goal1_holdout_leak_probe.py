"""Public-label leakage is a falsifier, never evidence of held-out learning."""
from __future__ import annotations
import tempfile
from pathlib import Path
import unittest

from research.goal1_acceptance_bridge.holdout_leak_probe import (
    inspect_public_trial_source, private_holdout_exit_code,
)


class HoldoutLeakageTests(unittest.TestCase):
    def test_plain_public_holdout_answers_yield_trivial_perfect_score(self):
        source='HOLDOUT = (("bits:110", "B"), ("bits:101", "B"), ("bits:011", "A"), ("bits:000", "A"))'
        result=inspect_public_trial_source(source)
        self.assertEqual(result["public_inline_holdout_labels"],4)
        self.assertEqual(result["public_source_oracle_accuracy"],1.0)
        self.assertEqual(result["classification"],"PUBLIC_FIXTURE_LEAKED_NOT_PRIVATE_HOLDOUT")
        self.assertFalse(result["private_holdout_verified"])
        self.assertFalse(result["learning_qualified"])
        self.assertEqual(private_holdout_exit_code(result),2)
    
    def test_no_inline_labels_is_not_private_custody_proof(self):
        source='def load():\n    return custodian.get_private_labels()\n'
        result=inspect_public_trial_source(source)
        self.assertEqual(result["public_inline_holdout_labels"],0)
        self.assertEqual(result["classification"],"NO_INLINE_LEAK_OBSERVED_CUSTODY_UNKNOWN")
        self.assertFalse(result["private_holdout_verified"])
        self.assertEqual(private_holdout_exit_code(result),2)

    def test_partial_public_truth_blocks_without_inventing_remaining_labels(self):
        source='HOLDOUT=(("a","A"),("b","NOT_REVEALED"))'
        result=inspect_public_trial_source(source)
        self.assertEqual(result["public_inline_holdout_labels"],1)
        self.assertIsNone(result["public_source_oracle_accuracy"])
        self.assertFalse(result["private_holdout_verified"])
        self.assertEqual(private_holdout_exit_code(result),2)

    def test_dynamic_source_does_not_promote_absence_to_private_truth(self):
        source='HOLDOUT = tuple(generator())'
        result=inspect_public_trial_source(source)
        self.assertEqual(result["public_inline_holdout_labels"],0)
        self.assertFalse(result["private_holdout_verified"])
        self.assertEqual(private_holdout_exit_code(result),2)

    def test_public_label_reassignment_is_not_silently_ignored(self):
        source='HOLDOUT = (("a", "A"),)\nHOLDOUT = (("b", "B"),)'
        result=inspect_public_trial_source(source)
        self.assertEqual(result["public_inline_holdout_labels"],2)
        self.assertEqual(private_holdout_exit_code(result),2)

    def test_rejects_non_module_python_as_unscannable(self):
        with self.assertRaises(SyntaxError):
            inspect_public_trial_source('HOLDOUT = ((,,))')

    def test_forged_qualified_flag_cannot_pass_strict_mode(self):
        result=inspect_public_trial_source('HOLDOUT=(("x","A"),)')
        result["private_holdout_verified"]=True
        result["learning_qualified"]=True
        self.assertEqual(private_holdout_exit_code(result),2)


if __name__=="__main__":
    unittest.main()
