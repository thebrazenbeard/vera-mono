"""Synthetic, public-host-assertion tests for unsigned-to-signed correction boundaries."""
from __future__ import annotations

from dataclasses import replace
import base64
import hashlib
import json
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from vera_core.social_revision_ledger import (
    CorrectionEntry, CorrectionLedger, PropositionType, SourceKind, ROOT_HEAD,
)
from vera_core.social_user_correction_witness import (
    SignedUserCorrectionV1, TrustedCorrectionVerifier,
)


def sign(witness: SignedUserCorrectionV1, private) -> SignedUserCorrectionV1:
    return replace(
        witness,
        signature_b64=base64.b64encode(private.sign(witness.signed_bytes())).decode("ascii")
    )


class TestSignedUserCorrection(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.verifier = TrustedCorrectionVerifier(
            issuer_id="synthetic-host", key_id="ephemeral-key", public_key_bytes=self.public
        )
        self.ledger = CorrectionLedger()
        self.first = CorrectionEntry(
            event_id="e1", session_id="synthetic-session", turn_id="t1",
            subject_ref="world/life/nonbiological",
            proposition_type=PropositionType.DEFINITION,
            source_kind=SourceKind.CURRENT_USER,
            statement="Nonbiological life is a question, not a definition.",
            supersedes=None,
        )
        self.second = replace(
            self.first, event_id="e2", turn_id="t2",
            statement="I mean a self-maintaining nonbiological process.",
            supersedes="e1",
        )

    def signed(self, ledger=None, entry=None, previous=None):
        ledger = self.ledger if ledger is None else ledger
        entry = self.first if entry is None else entry
        previous = ledger.head if previous is None else previous
        after = ledger.append(entry, expected_head=previous)
        binding = SignedUserCorrectionV1(
            issuer_id="synthetic-host", key_id="ephemeral-key",
            actor_id="authenticated_user", session_id=entry.session_id,
            turn_id=entry.turn_id, subject_ref=entry.subject_ref,
            proposition_type=entry.proposition_type,
            source_kind=entry.source_kind,
            event_id=entry.event_id,
            supersedes=entry.supersedes,
            statement_sha256=hashlib.sha256(entry.statement.encode("utf-8")).hexdigest(),
            expected_previous_head=previous,
            resulting_head=after.head,
            signature_b64="",
        )
        return sign(binding, self.private)

    def checked(self, binding, ledger=None, entry=None, expected_session=None,
                expected_turn=None, expected_head=None):
        ledger = self.ledger if ledger is None else ledger
        entry = self.first if entry is None else entry
        return self.verifier.verify(
            binding, ledger=ledger, entry=entry,
            expected_session_id=(
                entry.session_id if expected_session is None else expected_session
            ),
            expected_turn_id=entry.turn_id if expected_turn is None else expected_turn,
            expected_previous_head=ledger.head if expected_head is None else expected_head,
        )

    def receipt(self, binding, entry=None):
        entry = self.first if entry is None else entry
        return self.verifier.public_receipt(
            binding, ledger=self.ledger, entry=entry,
            expected_session_id=entry.session_id,
            expected_turn_id=entry.turn_id,
            expected_previous_head=self.ledger.head,
        )

    def test_valid_exact_signed_host_assertion_is_candidate_not_action(self):
        signed = self.signed()
        self.assertTrue(self.checked(signed))
        self.assertFalse(self.ledger.current_position_authorized)
        self.assertFalse(self.ledger.external_action_authorized)
        self.assertEqual(len(self.ledger.entries), 0)

    def test_direct_archive_reconstruction_cannot_yield_current_without_host_witness(self):
        signed = self.signed()
        archival = self.ledger.append(self.first, expected_head=ROOT_HEAD)
        reconstructed = CorrectionLedger(entries=archival.entries)
        self.assertIsNone(reconstructed.current_turn_evidence("synthetic-session", "t1"))
        self.assertFalse(self.checked(signed, ledger=reconstructed))
        self.assertTrue(self.checked(signed, ledger=CorrectionLedger()))

    def test_signed_successive_correction_uses_exact_parent_and_head(self):
        binding = self.signed()
        one = self.ledger.append(self.first, expected_head=ROOT_HEAD)
        next_binding = self.signed(ledger=one, entry=self.second)
        self.assertTrue(self.checked(next_binding, ledger=one, entry=self.second))
        self.assertFalse(self.checked(next_binding, ledger=self.ledger, entry=self.second))
        self.assertFalse(self.checked(binding, ledger=one))

    def test_signature_cannot_replay_new_session_or_turn(self):
        binding = self.signed()
        self.assertFalse(self.checked(binding, expected_session="other-session"))
        self.assertFalse(self.checked(binding, expected_turn="other-turn"))

    def test_invalid_source_kind_or_actor_rejected(self):
        binding = self.signed()
        for field, value in (
            ("actor_id", "vera"),
            ("source_kind", SourceKind.HISTORICAL_RECORD),
        ):
            with self.subTest(field=field):
                altered = replace(binding, **{field: value})
                self.assertFalse(self.checked(altered))
        historical = replace(self.first, source_kind=SourceKind.HISTORICAL_RECORD)
        self.assertFalse(self.checked(binding, entry=historical))

    def test_scope_substitutions_rejected(self):
        binding = self.signed()
        for field, value in (
            ("issuer_id", "foreign-host"),
            ("key_id", "other-key"),
            ("session_id", "other-session"),
            ("turn_id", "t2"),
            ("subject_ref", "world/life/biological"),
            ("proposition_type", PropositionType.PREFERENCE),
            ("event_id", "e2"),
            ("supersedes", "unknown"),
            ("statement_sha256", "0" * 64),
            ("expected_previous_head", "0" * 64),
            ("resulting_head", "0" * 64),
        ):
            with self.subTest(field=field):
                altered = replace(binding, **{field: value})
                self.assertFalse(self.checked(altered))

    def test_crypto_valid_but_semantically_wrong_host_claim_is_denied(self):
        binding = self.signed()
        mutations = (
            ("actor_id", "vera"),
            ("source_kind", SourceKind.HISTORICAL_RECORD),
            ("proposition_type", PropositionType.CONSENT),
            ("subject_ref", "unrelated/person/preference"),
            ("event_id", "different-event"),
            ("statement_sha256", hashlib.sha256(b"other").hexdigest()),
            ("expected_previous_head", "0" * 64),
            ("resulting_head", "0" * 64),
            ("session_id", "different-session"),
            ("turn_id", "different-turn"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                # Re-sign so that a valid crypto signature cannot hide wrong scope.
                altered = sign(replace(binding, **{field: value}), self.private)
                self.assertFalse(self.checked(altered))

    def test_altered_entry_content_and_referent_rejected(self):
        binding = self.signed()
        for field, value in (
            ("statement", "Different self report"),
            ("subject_ref", "world/life/biological"),
            ("proposition_type", PropositionType.PREFERENCE),
            ("event_id", "imposter"),
            ("session_id", "session2"),
            ("turn_id", "turn2"),
        ):
            with self.subTest(field=field):
                changed = replace(self.first, **{field: value})
                self.assertFalse(self.checked(binding, entry=changed))

    def test_rejected_under_other_public_key(self):
        binding = self.signed()
        other = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        verifier = TrustedCorrectionVerifier(
            issuer_id="synthetic-host", key_id="ephemeral-key", public_key_bytes=other
        )
        self.assertFalse(verifier.verify(
            binding, ledger=self.ledger, entry=self.first,
            expected_session_id="synthetic-session", expected_turn_id="t1",
            expected_previous_head=ROOT_HEAD,
        ))

    def test_malformed_signature_rejected(self):
        binding = self.signed()
        for signature in ("", "%%%", "a"*100, None, "AAAA"):
            with self.subTest(signature=signature):
                self.assertFalse(self.checked(replace(binding, signature_b64=signature)))

    def test_signed_witness_type_violations_rejected(self):
        binding = self.signed()
        for field, value in (
            ("proposition_type", "DEFINITION"),
            ("source_kind", "CURRENT_USER"),
            ("statement_sha256", "x"),
            ("resulting_head", "garbage"),
            ("actor_id", ""),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    replace(binding, **{field: value}).signed_bytes()

    def test_malformed_request_data_rejected(self):
        binding = self.signed()
        self.assertFalse(self.verifier.verify(
            binding, ledger=self.ledger, entry=self.first,
            expected_session_id="", expected_turn_id="t1",
            expected_previous_head=ROOT_HEAD,
        ))
        self.assertFalse(self.verifier.verify(
            binding, ledger=self.ledger, entry=self.first,
            expected_session_id="synthetic-session", expected_turn_id="t1",
            expected_previous_head="0"*64,
        ))
        self.assertFalse(self.verifier.verify(
            binding, ledger=object(), entry=self.first,
            expected_session_id="synthetic-session", expected_turn_id="t1",
            expected_previous_head=ROOT_HEAD,
        ))

    def test_valid_signed_consent_utterance_still_grants_no_effect(self):
        consent = replace(
            self.first, proposition_type=PropositionType.CONSENT,
            statement="I consent to discuss a fictional example, not publication."
        )
        binding = self.signed(entry=consent)
        self.assertTrue(self.checked(binding, entry=consent))
        receipt = self.receipt(binding, consent)
        self.assertTrue(receipt["signer_assertion_valid"])
        self.assertFalse(receipt["external_effect_authorized"])
        self.assertFalse(receipt["canonical_memory_admitted"])
        self.assertFalse(receipt["verified_user_identity"])

    def test_v2_self_report_signature_cannot_replay_as_user_correction(self):
        from vera_core.social_appraisal_preflight import (
            Claim, CurrentTurnPropositionAttestationV2,
            Evidence, ProposedEffect, RelationalPlan,
        )
        host_observation = CurrentTurnPropositionAttestationV2(
            issuer_id="synthetic-host", key_id="ephemeral-key",
            actor_id="vera", session_id="synthetic-session", turn_id="t1",
            statement_sha256=hashlib.sha256(self.first.statement.encode()).hexdigest(),
            claim=Claim.PROVISIONAL_POSITION,
            evidence=Evidence.CURRENT_VERA_SELF_REPORT,
            proposition_ref=self.first.subject_ref,
            relational_plan=RelationalPlan.NONE, effect=ProposedEffect.NONE,
            signature_b64="",
        )
        foreign_signature = base64.b64encode(
            self.private.sign(host_observation.signed_bytes())
        ).decode("ascii")
        forged = replace(self.signed(), signature_b64=foreign_signature)
        self.assertFalse(self.checked(forged))

    def test_caller_boolean_cannot_mint_a_signature_valid_receipt(self):
        # A receipt must be derived by the verifier, not trust a caller bool.
        with self.assertRaises(TypeError):
            self.verifier.public_receipt(True)

    def test_public_receipt_contains_no_subject_or_statement_or_signature(self):
        binding = self.signed()
        text = json.dumps(self.receipt(binding))
        for secret in (
            binding.signature_b64, self.first.statement, self.first.subject_ref,
            self.first.session_id, self.first.turn_id, binding.statement_sha256,
        ):
            self.assertNotIn(secret, text)
        self.assertIn("SIGNER_ASSERTION_ONLY", text)

    def test_signed_bytes_are_domain_separated_from_v2_legacy_actor_propositions(self):
        binding = self.signed()
        self.assertTrue(binding.signed_bytes().startswith(b"VERA_HOST_USER_CORRECTION_V1\0"))
        self.assertNotIn(self.first.statement.encode(), binding.signed_bytes())


if __name__ == "__main__":
    unittest.main()
