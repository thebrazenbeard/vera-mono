"""Pinned signed PUBLIC grants: crypto provenance only, not host qualification."""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
except ImportError:
    Ed25519PrivateKey = None

from tests.test_mini_vera_source_bindings import KEY, ledger_fixture
from tools.mini_vera.host_memory_broker import PublicMemoryGrant, bind_host_public_memory
from tools.mini_vera.unprotected_revision_floor import UnprotectedRevisionFloor
from tools.mini_vera import signed_public_grant as verifier

NOW = 1794657600
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(Ed25519PrivateKey is None, "optional cryptography unavailable")
class SignedPublicMemoryGrantTests(unittest.TestCase):
    def setUp(self):
        self.signer = Ed25519PrivateKey.generate()
        self.public = self.signer.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.pin = hashlib.sha256(self.public).hexdigest()
        self.payload = {
            "schema": "MINI_VERA_SIGNED_PUBLIC_GRANT_PAYLOAD_V1",
            "issuer_id": "synthetic-issuer-A",
            "issued_at_unix": NOW - 5,
            "project_id": "vera-mono",
            "identity_id": "vera",
            "ledger_head": "a"*64,
            "revision": 13,
            "record_ids": ["work-1"],
            "record_digests": [["work-1", "b"*64]],
            "approval_epoch": 4,
            "authority_revision": 10,
            "expires_at_unix": NOW + 300,
        }

    def envelope(self, payload=None, signer=None):
        payload = self.payload if payload is None else payload
        signer = self.signer if signer is None else signer
        return json.dumps({
            "schema": "MINI_VERA_SIGNED_PUBLIC_GRANT_V1",
            "payload": payload,
            "signature_ed25519_hex": signer.sign(
                json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()).hex(),
        }, sort_keys=True, separators=(",", ":")).encode()

    def verifier(self, **overrides):
        params = {
            "trusted_public_key": self.public,
            "expected_public_key_sha256": self.pin,
            "expected_issuer_id": "synthetic-issuer-A",
            "expected_project_id": "vera-mono",
            "expected_identity_id": "vera",
            "now_seconds": lambda: NOW,
        }
        return verifier.PinnedSignedPublicGrantReader(**(params | overrides))

    def test_exact_signature_produces_immutable_broker_grant(self):
        grant = self.verifier().verify(self.envelope())
        self.assertIs(type(grant), PublicMemoryGrant)
        self.assertEqual(grant.record_ids, ("work-1",))
        self.assertEqual(grant.record_digests, (("work-1", "b"*64),))
        self.assertEqual(grant.authority_revision, 10)
        self.assertFalse(hasattr(grant, "host_issuer_qualified"))

    def test_forged_record_content_epoch_revision_and_scope_refuse(self):
        original = json.loads(self.envelope())
        for field, fake in (
            ("ledger_head", "c"*64), ("approval_epoch", 5),
            ("authority_revision", 11), ("record_ids", ["work-2"]),
            ("project_id", "evil-project"), ("identity_id", "evil"),
        ):
            with self.subTest(field=field):
                altered = json.loads(json.dumps(original))
                altered["payload"][field] = fake
                with self.assertRaises(verifier.SignedGrantRefused):
                    self.verifier().verify(json.dumps(altered).encode())

    def test_wrong_trust_pin_and_wrong_signature_refuse(self):
        with self.assertRaises(verifier.SignedGrantRefused):
            self.verifier(expected_public_key_sha256="0"*64)
        another = Ed25519PrivateKey.generate()
        with self.assertRaises(verifier.SignedGrantRefused):
            self.verifier().verify(self.envelope(signer=another))
        new_key = another.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        with self.assertRaises(verifier.SignedGrantRefused):
            self.verifier(trusted_public_key=new_key).verify(self.envelope())

    def test_signer_mismatch_or_wrong_project_refuse_even_if_resigned(self):
        for field, fake in (("issuer_id", "other-issuer"),
                            ("project_id", "other-project"),
                            ("identity_id", "another")):
            with self.subTest(field=field):
                updated = dict(self.payload)
                updated[field] = fake
                with self.assertRaises(verifier.SignedGrantRefused):
                    self.verifier().verify(self.envelope(updated))

    def test_stale_future_expired_and_long_lived_signed_grants_refuse(self):
        for time_field, value in (
            ("issued_at_unix", NOW-180),
            ("issued_at_unix", NOW+30),
            ("expires_at_unix", NOW),
            ("expires_at_unix", NOW+3600),
        ):
            with self.subTest(field=time_field, value=value):
                updated = dict(self.payload)
                updated[time_field] = value
                with self.assertRaises(verifier.SignedGrantRefused):
                    self.verifier().verify(self.envelope(updated))

    def test_malformed_duplicate_unknown_and_boolean_payload_values_refuse(self):
        raw = self.envelope()
        bad = (
            raw.replace(b'"schema":"MINI_VERA_SIGNED_PUBLIC_GRANT_V1"',
                        b'"schema":"MINI_VERA_SIGNED_PUBLIC_GRANT_V1","schema":"again"'),
            raw[:20],
            b"x"*9000,
            self.envelope(self.payload | {"record_ids": ["work-1", "work-1"]}),
            self.envelope(self.payload | {"authority_revision": True}),
            self.envelope(self.payload | {"record_digests": [["work-1", "ZZ"*32]]}),
            self.envelope(self.payload | {"extra": "injected"}),
        )
        for index, packet in enumerate(bad):
            with self.subTest(index=index):
                with self.assertRaises(verifier.SignedGrantRefused):
                    self.verifier().verify(packet)

    def test_separate_synthetic_signer_process_public_key_only_in_parent(self):
        signer_source = """
import sys,json,hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
payload=json.loads(sys.stdin.read())
key=Ed25519PrivateKey.generate()
public=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
raw=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
print(json.dumps({'public_hex':public.hex(),'packet':{'schema':'MINI_VERA_SIGNED_PUBLIC_GRANT_V1','payload':payload,'signature_ed25519_hex':key.sign(raw).hex()}}))
"""
        proc = subprocess.run([sys.executable, "-B", "-c", signer_source],
                              input=json.dumps(self.payload),text=True,
                              capture_output=True,cwd=ROOT,timeout=15,check=True)
        data = json.loads(proc.stdout)
        public = bytes.fromhex(data["public_hex"])
        grant = self.verifier(
            trusted_public_key=public,
            expected_public_key_sha256=hashlib.sha256(public).hexdigest()).verify(
                json.dumps(data["packet"]).encode())
        self.assertEqual(10, grant.authority_revision)

    def test_unprotected_same_user_key_repin_still_forges_authority(self):
        """Signed cannot mean qualified without independently pinned issuer."""
        attacker = Ed25519PrivateKey.generate()
        pub = attacker.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        forged = self.payload | {"approval_epoch": 99}
        with self.assertRaises(verifier.SignedGrantRefused):
            self.verifier().verify(self.envelope(forged, attacker))
        accepted = self.verifier(
            trusted_public_key=pub,
            expected_public_key_sha256=hashlib.sha256(pub).hexdigest()
            ).verify(self.envelope(forged, attacker))
        self.assertEqual(99, accepted.approval_epoch)

    def test_signed_replayed_grant_fails_on_independent_revision_floor(self):
        with tempfile.TemporaryDirectory(prefix="mini-vera-signed-replay-") as temp:
            folder = Path(temp)
            ledger, head = ledger_fixture(folder)
            digest = ledger.read("work-1").record_digest
            packet = self.envelope(self.payload | {
                "ledger_head": head,
                "record_digests": [["work-1", digest]],
                "authority_revision": 10,
            })
            reader = self.verifier()
            floor = UnprotectedRevisionFloor(folder / "external-floor.sqlite")
            source = {"revision": 10}
            def broker():
                return bind_host_public_memory(
                    ledger, integrity_key=KEY,
                    current_grant=lambda: reader.verify(packet),
                    approve_record=lambda rec, grant: rec.privacy_ref == "PUBLIC",
                    current_authority_revision=lambda: source["revision"],
                    atomic_host_revision_floor=floor,
                    now_seconds=lambda: NOW)
            broker()()
            # An independently advanced revision source is required.
            self.assertEqual(11, floor.advance(11))
            with self.assertRaisesRegex(Exception, "rollback"):
                broker()()
            source["revision"] = 11
            with self.assertRaisesRegex(Exception, "authority revision"):
                broker()()  # still signed with 10; reissuance required.

    def test_historical_signature_rejected_after_clock_advances(self):
        packet = self.envelope()
        future = self.verifier(now_seconds=lambda: NOW + 500)
        with self.assertRaises(verifier.SignedGrantRefused):
            future.verify(packet)

    def test_signed_grant_supplies_existing_broker_without_expanding_scopes(self):
        with tempfile.TemporaryDirectory(prefix="mini-vera-signed-grant-") as temp:
            folder = Path(temp)
            ledger, head = ledger_fixture(folder)
            digest = ledger.read("work-1").record_digest
            payload = self.payload | {
                "ledger_head": head, "record_digests": [["work-1", digest]]
            }
            packet = self.envelope(payload)
            reader = self.verifier()
            floor = UnprotectedRevisionFloor(folder / "external-floor.sqlite")
            provider = bind_host_public_memory(
                ledger, integrity_key=KEY,
                current_grant=lambda: reader.verify(packet),
                approve_record=lambda rec, grant: (
                    rec.privacy_ref == "PUBLIC" and
                    rec.authority_ref == "synthetic-approved"),
                current_authority_revision=lambda: 10,
                atomic_host_revision_floor=floor,
                now_seconds=lambda: NOW,
            )
            state, key, revision = provider()
            self.assertEqual(13, revision)
            self.assertEqual(["work-1"], [x["record_id"] for x in state["records"]])
            self.assertNotEqual(key, KEY)
            self.assertEqual(10, floor.advance(0))
            # Fresh signed grant with a newer revision cannot be confused
            # with an independently advanced authority revision source.
            changed = payload | {"authority_revision": 11}
            with self.assertRaisesRegex(Exception, "authority revision"):
                bind_host_public_memory(
                    ledger, integrity_key=KEY,
                    current_grant=lambda: reader.verify(self.envelope(changed)),
                    approve_record=lambda *_: True,
                    current_authority_revision=lambda: 10,
                    atomic_host_revision_floor=floor,
                    now_seconds=lambda: NOW)()
