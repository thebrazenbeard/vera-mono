"""No real filesystem ACL reads and no test directories created."""

import os
import unittest

from tools.security.windows_acl_fixture import run_synthetic_acl_cases, SYNTHETIC_CASES


class SyntheticAclFixtureTests(unittest.TestCase):
    def test_fixture_contract(self):
        result = run_synthetic_acl_cases()
        self.assertIs(result["real_acl_attested"], False)
        if os.name == "nt":
            # An inconclusive native API operation MUST NOT be a green skip.
            self.assertEqual(result["status"], "SYNTHETIC_ACL_FIXTURE_PASS")
            self.assertEqual(result["cases"], len(SYNTHETIC_CASES))
        else:
            self.assertEqual(result["status"], "NOT_RUN_NON_WINDOWS")


if __name__ == "__main__":
    unittest.main()
