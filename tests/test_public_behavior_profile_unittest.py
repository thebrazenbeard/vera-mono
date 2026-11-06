"""Dependency-free source test for the opt-in public style projection.

Other CLI/socket integration tests live in test_cli_chat.py and require the
monorepo's declared runtime/test dependencies.
"""

from __future__ import annotations

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/vera_core/src/vera_core/behavior_profile_context.py"
PACKAGE_ROOT = ROOT / "packages/vera_identity/src/vera_identity"
SPEC = spec_from_file_location("behavior_profile_context_standalone", SOURCE)
assert SPEC is not None and SPEC.loader is not None
PROFILE = module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class PublicBehaviorStyleTests(unittest.TestCase):
    def test_style_projection_uses_exact_public_packaged_profile(self) -> None:
        raw = (PACKAGE_ROOT / PROFILE.PROFILE_RESOURCE).read_bytes()
        self.assertEqual(PROFILE.PROFILE_SHA256, sha256(raw).hexdigest())
        with patch.object(PROFILE, "files", return_value=PACKAGE_ROOT):
            prompt = PROFILE.public_behavior_style()
        self.assertIn("PUBLIC Vera behavior-style source", prompt)
        self.assertIn("candor:", prompt)
        self.assertIn("context_sensitivity:", prompt)
        self.assertIn(PROFILE.PROFILE_SHA256, prompt)
        self.assertIn("not installed identity or authority", prompt)
        self.assertLess(len(prompt), 4000)

    def test_tampered_packaged_profile_is_rejected(self) -> None:
        raw = (PACKAGE_ROOT / PROFILE.PROFILE_RESOURCE).read_bytes()
        with TemporaryDirectory() as temp:
            forged_root = Path(temp)
            path = forged_root / PROFILE.PROFILE_RESOURCE
            path.parent.mkdir(parents=True)
            path.write_bytes(raw.replace(b'"candor"', b'"cand0r"', 1))
            with patch.object(PROFILE, "files", return_value=forged_root):
                with self.assertRaisesRegex(ValueError, "byte binding mismatch"):
                    PROFILE.public_behavior_style()


if __name__ == "__main__":
    unittest.main()
