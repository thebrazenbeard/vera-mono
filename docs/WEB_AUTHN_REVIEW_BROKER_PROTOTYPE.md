# Vera Lappy reviewed-memory broker — source-only feasibility slice

Status: **ES256 assertion verifier prototype only**. No Windows Hello enrollment,
service, native prompt, private memory, production inference, or journal integration.
Do not describe the test key as Patrick's Windows Hello key.

## Why the existing journal cannot use Hello directly

Vera Mono main `7835b1a097ce` uses `SupervisedFeedbackJournal` with a pinned
raw 32-byte Ed25519 public key and a 64-byte Ed25519 signature over
`ReviewDecision.signable_bytes()`. Windows WebAuthn produces an assertion
envelope containing credential ID, authenticator data, client data JSON, and
an authenticator signature (typically ES256/P-256). Wrapping an arbitrary
software Ed25519 signer in a Windows Hello dialog would not prove that Hello
authorized the review.

The isolated module `packages/vera_memory/src/vera_memory/webauthn_review.py` only verifies synthetic
ES256 test assertions. It binds the SHA-256 challenge to every byte of the
review decision, including the journal head, candidate, action, nonce, expiry
and evaluation digest supplied by the existing decision schema. It checks
registered credential ID/key, RP ID hash, exact origin, UP+UV flags, and
signature over authenticatorData || SHA256(clientDataJSON).

Its `VerifiedWebAuthnAction` object is **not a bearer authorization**. A caller
can manufacture that Python object. The trusted journal must receive the raw
WebAuthn assertion and verify it itself using separately pinned enrollment.
The prototype exposes the authenticator sign counter for telemetry only:
it does **not** persist, enforce monotonicity or prevent replay by itself.
Many platform authenticators report zero counters; the journal's one-time
nonce, protected head and service custody must still block replay.

## Target boundaries

1. **Reviewer enrollment (interactive, one time).** An installed, admin-owned
   Windows broker registers an authenticator credential via
   `WebAuthNAuthenticatorMakeCredential`; Patrick must physically enroll
   with trusted Windows UI. Record credential ID, public key/COSE algorithm,
   RP ID, origin, attestation/provenance decision and recovery policy in a
   service-owned registry inaccessible to the Vera model process.
2. **Trusted challenge creation.** The service, not model output, reads the
   current staged evaluation and protected checkpoint. It creates an exact
   `ReviewDecision` with nonce and short expiry, holds it for one-time use,
   and displays action/answer/source/holdout summary in a trusted GUI.
3. **User-verifying signature.** The broker calls
   `WebAuthNAuthenticatorGetAssertion` with the registered RP ID,
   credential allow list, and required user verification. A Windows Hello
   or FIDO2 prompt is unavoidable; a silent headless sign must not be a
   supported production path.
4. **Service-side verification.** Extend the journal with a distinct raw
   `WebAuthnReviewProof` envelope and registered P-256 credential dispatch.
   Recheck exact challenge, clientDataJSON type/origin, RP hash, UP and UV,
   registered key signature, nonce/head/revision/action/expiry; do not accept
   `review_qualified=True`, free-form evidence strings, a caller-created
   `VerifiedWebAuthnAction`, or an Ed25519 private key provided by model code.
5. **Protected custody.** Put journal writes and the high-watermark checkpoint
   behind a distinct Windows service SID/account and protected data directory
   ACL. The model's interactive account may request bounded operations but
   must not have write access to database, checkpoint, reviewer registry, or
   broker executable. A same-user path probe has already shown
   check-then-open relocation can swap a SQLite file despite no symlink and
   `st_nlink==1`.
6. **Durability and fresh session.** Only the trusted service applies review,
   commits the append-only event and advances the protected checkpoint.
   A crash after journal append but before checkpoint update is **fail closed**
   and requires separately approved recovery, not an automatic rewind.
   Reopen in an independent process with the pinned key and protected head.
7. **Revocation.** Revoke or rollback with another fresh signed action. Before
   each model-facing read and before consequential effects, revalidate the
   protected head. Specify whether review revocation blocks an in-flight
   generation or only subsequent turns; the current synthetic journal has
   a lookup-to-use race and no effect lease.

## Negative acceptance gates before production

- Same-user model code cannot sign, alter or replace the broker, fake a
  trusted UI receipt, use another credential ID, or update reviewer registry.
- An actual Windows Hello/FIDO2 enrollment and UV-required assertion on
  Lappy is verified independently from signed data, not inferred from a
  Python synthetic ES256 key.
- The approval prompt unmistakably identifies the full pending action;
  clicking a generic consent button is insufficient.
- Forged origin/challenge/RP hash, missing UP/UV, duplicate JSON keys,
  signature mutation, replay, expiry, old head, wrong evaluation, wrong key,
  offline journal rollback and fresh-process stale cache all fail closed.
- NTFS permissions are tested with a second ordinary Windows identity;
  Windows junction/hardlink/reparse and rename-race probes verify **handle
  identity**, not just prior path checks. Production staging currently
  inherits Authenticated Users Modify and must remain off.
- Real model-facing correction test shows baseline answer, separately
  consented revised answer across restart, fresh heldout non-identical cues,
  then signed revocation and return to baseline; quantify failures.

## Verified prototype evidence

```powershell
# This is a Linux-hosted source-only simulated assertion test, not a Hello test.
VERA_MONO_SOURCE=<monorepo-root> python -m pytest -q tests/test_vera_webauthn_review.py
```

At the frozen prototype: **10 passing tests, 1 expected failure**. The expected
failure executes a *valid synthetic ES256 proof* then shows the merged
Ed25519-only journal rejects it. An expected failure is an unresolved
integration gate, not success.

Official specifications:

- [Microsoft Win32 WebAuthn API](https://learn.microsoft.com/en-us/windows/win32/webauthn/-webauthn-portal)
- [Microsoft GetAssertion](https://learn.microsoft.com/en-us/windows/win32/api/webauthn/nf-webauthn-webauthnauthenticatorgetassertion)
- [Microsoft MakeCredential](https://learn.microsoft.com/en-us/windows/win32/api/webauthn/nf-webauthn-webauthnauthenticatormakecredential)
- [Microsoft assertion result layout](https://learn.microsoft.com/en-us/windows/win32/api/webauthn/ns-webauthn-webauthn_assertion)
- [W3C Web Authentication Level 3 verification](https://www.w3.org/TR/webauthn-3/)
