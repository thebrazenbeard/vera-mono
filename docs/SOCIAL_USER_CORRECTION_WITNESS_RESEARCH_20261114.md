# Synthetic signed user-correction witness - research, 2026-11-14

Status: **SOURCE-ONLY SECURITY CANDIDATE. NO HOST USER AUTHENTICATION OR LIVE RUNTIME CONSUMPTION.**

Source: `packages/vera_core/src/vera_core/social_user_correction_witness.py`. This work is isolated to Vera Mono Draft PR #214. The existing correction ledger continues to return **no current-turn evidence** from caller-constructed or restored records. A distinct, externally pinned signing key would be required before any authorized runtime may attribute a newly signed correction to the actual user.

## Exact scope of a signer assertion

`SignedUserCorrectionV1.signed_bytes()` is canonical JSON with domain prefix `VERA_HOST_USER_CORRECTION_V1\0` and fixed schema. It binds **issuer ID, key ID, actor role `authenticated_user`, session, turn, subject referent, typed proposition, source category, event ID, superseded event ID, SHA-256 of exact UTF-8 statement, expected previous ledger head, and derived next ledger head**. The actor role string is asserted *by the signer*; it is not independently verified user identity.

`TrustedCorrectionVerifier.verify()` is pure verification. The caller must supply its proposed `CorrectionEntry`, existing `CorrectionLedger`, independently expected session/turn and prior head, and a trusted key whose ownership must be established **outside the caller's message**. It checks complete typed field equality, requires `CURRENT_USER` source label, previews `CorrectionLedger.append` without mutation to validate exact parent and next hash, and verifies Ed25519 over domain-separated bytes. Any invalid signature, type, head, scope or missing crypto is rejected. This is not semantic truth, a consent authority or even proof of which host controlled the signing key. The verifier public receipt excludes source text, subject, session IDs, turn, signature and low-entropy statement hash and explicitly denies verified user identity, actual host currentness, memory admission and effects.

## Reproducible synthetic test evidence

- TDD **RED**: tests imported the missing `vera_core.social_user_correction_witness` and correctly failed collection with `ModuleNotFoundError`, exit2. The source module was then implemented.
- Fixed fictional Ed25519 fixtures are **ephemeral**, generated only within test execution. No real Vera or Patrick text, private signing key, canonical memory, credentials or external provider service was accessed or modified.
- Hostile mutations cover: wrong/foreign keys; wrong actor and source; wrong subject and proposition kind (including consent); other session/turn; changed statement; event/supersession mismatch; stale/incorrect previous head; derived next-head mismatch; malformed signatures; and **resigned** incorrect metadata using the actual ephemeral test key. This proves valid cryptography alone cannot bypass the local scope checks.
- A separate real-Python-process test serializes **only a synthetic signed witness and public key** (not the private key) to a throwaway file and verifies it under three separate fresh processes with expected sessions `fictional-session1`, `fictional-session2`, and `fictional-session1`: outcomes **[true, false, true]**. This confirms session mismatch denial and separately demonstrates that **identical original context can be replayed after restart**. The source is intentionally read-only; no durable spent-token register or one-time-use guarantee exists. No claims of persistent host authority, genuine session continuity or privileged state.
- Cross-protocol test signs a `CurrentTurnPropositionAttestationV2` and places that signature into a correction witness with the same ephemeral key: correction verification denies it because the signed domain and scope are different.
- Explicitly signed `CONSENT` utterance can be a signer assertion, but the verifier receipt **still denies effect and memory authority**.
- Focused Lappy Python3.12 verification before receipt hardening: **17 passed, 39 subtests passed**, exit0. Whole Vera Mono full suite at that revision **1104 passed, 104 skipped, 198 subtests passed**, one collection warning, exit0. No independent reviewer has qualified the behavior or host.

## Further receipt forgery control

**RED**: `TrustedCorrectionVerifier.public_receipt(True)` previously accepted a caller-supplied boolean and emitted a `signer_assertion_valid=True` status without any signature check. A new negative test reproduced the misleading receipt (pytest exit1). The public receipt method now **requires the actual witness, exact entry, ledger, expected session, turn and previous head** and independently invokes `verify()` before reporting status. A bare boolean is rejected with `TypeError`; the separate-process test recomputes receipts for valid and invalid expected sessions rather than trusting a passed result.

This correction improves the local evidence trail but **still cannot establish that the caller-provided trust key is owned by the authorized runtime host**. A caller could build a different verifier with an unauthorized key. No public receipt should be cited as independent user authentication.

## Hostile release challenge

> A caller who chooses an arbitrary Ed25519 key can create a mathematically valid self-signed claim and supply that key to `TrustedCorrectionVerifier`. The module CANNOT prove that the key belongs to an authorized host or that the host correctly bound a real user utterance. An old same-session signed assertion can be verified again against an old reconstructed ledger with the same externally claimed head. Do not convert a signature-valid boolean into current consent, persistent memory, a protected action or a production release qualification.

Release-blocking work: protected issuer/key custody, independent session/currentness authority, trusted exact user-source observation, persistent single-use or transactional revision-floor policy where necessary, private storage policy, independent multi-seed and position-invariant behavior review, actual opt-in host consumer, Patrick's exact authority for any protected installation or canonical write.

## Final local verification and release boundary

After the receipt-forgery fix, the complete Lappy Python3.12.10 Vera Mono suite returned **1105 passed, 104 skipped, 198 subtests passed**, one pre-existing pytest collection warning, exit0, using isolated D: basetemp (109.26 seconds). Focused host correction tests **18 passed +39 subtests**, exit0; Python3.12 -O **18 passed +39 subtests**, exit0 (pytest assertion optimization warning), Python3.14 **18 passed**, exit0 (pytest-asyncio warning); compileall and local diff check exit0. These are local source tests, not hosted CI or independent runtime qualification. The specific false receipt was reproduced RED before the change, and the complete tests were rerun after it.

A valid witness should be described only as a cryptographically valid **assertion under the configured public key** for the checked synthetic content. Key ownership, observed user speech, any clock/session authority, private storage or data rights, signed effects, and one-time replay control are all separate unresolved dependencies. No live host signer, credentials, native controls or canonical memory were created in this iteration.
