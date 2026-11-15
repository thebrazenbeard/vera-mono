"""Minimal dependency test: advisory imports without optional cryptographic package."""
import subprocess
import sys
from pathlib import Path
import unittest


class TestOptionalCryptographyImport(unittest.TestCase):
    def test_module_imports_and_fails_closed_when_crypto_site_packages_absent(self):
        source = (
            Path(__file__).resolve().parents[1] /
            "packages/vera_core/src/vera_core/social_appraisal_preflight.py"
        )
        code = """
import importlib.util
import sys
source=sys.argv[1]
spec=importlib.util.spec_from_file_location('isolated_social_appraisal',source)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
item=module.AppraisalInput(
    claim=module.Claim.PROVISIONAL_POSITION,
    evidence=module.Evidence.CURRENT_VERA_SELF_REPORT,
    speaker='vera',current_turn='t1',evidence_turn='t1'
)
result=module.assess_appraisal(item)
assert result.current_position_candidate is False
assert result.external_action_authorized is False
try:
    module.TrustedHostSelfReportVerifier(
        issuer_id='fixture',key_id='fixture',
        public_key_bytes=b'1'*32
    )
except RuntimeError:
    pass
else:
    raise AssertionError('missing optional crypto must reject verifier construction')
print('OPTIONAL_CRYPTO_IMPORT_FAIL_CLOSED_OK')
"""
        completed = subprocess.run(
            [sys.executable, "-S", "-c", code, str(source)],
            capture_output=True, text=True, timeout=15
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("OPTIONAL_CRYPTO_IMPORT_FAIL_CLOSED_OK", completed.stdout)


if __name__ == "__main__":
    unittest.main()
