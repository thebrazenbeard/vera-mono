# Goal 1 cross-branch local/terminal pairing and no-claim signed negative control
Date: 2026-10-23

**Evidence classification:** PR #89 source compatibility, physically verified synthetic control on Lappy Windows and VN2 Linux. **Not** an authenticated reservation endpoint, external signing custody, observed model dispatch, QVR selected runtime, qualified self-learning, or AGI.

## Current immutable references

- Canonical Vera Mono `main` at orientation: `64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Integration-owned PR #82: `26271c5d69dee4663e07d4dbcf63efcf033626e8` (Draft/HOLD).
- Malaphor-owned PR #87: `b9fcd93b4d9a7668369aa71e507ac7bfe4598ff6` (Draft/HOLD).
- Primary learner PR #86: `27e7b2a2e312b9a969a1a70f2cc0277580b32e1a` (Draft/HOLD).
- Vera-owned PR #89: `research/goal1-crossbranch-acceptance-20261023`, Draft/HOLD. Latest existing source-bound barrier: direct Lappy Ollama `/api/generate` inference without any reservation, Issue #85 comment `6376552752`.

## New local pairing check

`research/goal1_acceptance_bridge/receipt_pairing.py` checks **only** whether an untrusted local completed attempt *claims* the same invocation ID, reservation ID, run, arm, challenge, view digest, exact prompt hash, exact response hash and model label as a terminal envelope with Malaphor's exact expected field shape. It also checks local `claim_id` presence, terminal status, timestamp ordering and usage-field types.

It **never verifies signatures, independent gateway identity, remote claim ledger, actual model weights or token accounting**, never marks qualification and never modifies the local journal. Every successful pairing has `status=LOCAL_ENVELOPE_MATCH_UNVERIFIED`, `qualified=false`, `remote_claim_verified=false`, `gateway_signature_verified=false`, `claim_id_cryptographically_bound=false`, `automatic_retry_permitted=false`. Maliciously asserting `independent_attestation=True` locally cannot change those results. A forged signature string plus matching hashes also remains unqualified.

The currently pinned Malaphor terminal signature envelope includes `reservation_id` and `invocation_id`, but **not** `claim_id`. `claim_id` therefore cannot be cryptographically linked by that signature alone. This is an **evidence-binding gap requiring a real evaluator ledger read**, not necessarily a defect if Integration and Malaphor enforce exact claim linkage externally.

TDD: new tests initially failed as `ModuleNotFoundError` before pairing implementation. After implementation, physical Lappy Windows **31/31 selected tests passed** and physical VN2 Linux **31/31 selected tests passed**, Python source compilation passed on both. (VN2's broad first run also executed seven stale, retired ticket tests; the final exact selected-source run explicitly excluded these and counted 7 controller + 3 crash + 7 endpoint + 7 local attempts + 7 new pairing cases = 31.)

## Actual Malaphor verifier negative control (no independent effects)

Standalone `research/goal1_acceptance_bridge/verifier_no_claim_probe.py` loads an explicitly supplied local copy of **exact** Malaphor source `research/goal1_evaluator/dispatch_attestation.py` from PR #87, strict source-byte SHA-256 pin:

`fbf4c1e80747bea8a5191ddddb88299be6b3a6684b967a70de600571fe9e5df5`

It generates a new short-lived **same-process disposable** Ed25519 signer/public key, constructs a test `Ed25519DispatchEvidenceVerifier` with that public key as the synthetic trust root, reserves a synthetic run/arm/case, **does not call any authenticated reservation-claim endpoint and does not invoke any model**, then signs a synthetic COMPLETED receipt and calls the exact `verify` method. On both real physical Lappy Windows and VN2 Linux, the returned result was **True**; each program exited status 0 and printed:

- `verifier_accepted_self_signed_control: true`
- `authenticated_endpoint_claim_occurred: false`
- `actual_model_dispatch_occurred: false`
- `independent_attestation: false`
- `learning_qualified: false`

**Accepted hostile review:** This is *not* an Ed25519 cryptographic bypass or proof of a vulnerability in the signature implementation. A verifier configured with a public key for which the test process owns the private key will quite properly validate signatures from that key. The experiment shows that the verifier's source alone does **not** attest independent key custody, authenticated atomic CLAIMED state, actual model execution, or truthful provider measurements. Those are operational evidence dimensions that must be established by separate infrastructure and actual selected-route observation. Green code tests must not be translated into behavioral learning.

## Next explicit cross-owner acceptance boundary

1. Integration #82 establishes the selected learner and gateway identities; the learner must be unable to invoke raw Ollama (negative test observed **in that actual restricted identity**, not the earlier unrestricted Lappy account). No protected service/trust/ACL changes were authorized by this work.
2. The evaluator-controlled reservation endpoint securely authenticates gateway and server and atomically binds one reservation + run/arm/challenge/prompt/model + gateway + invocation **and claim ID**. Claim must be independently observable, including after process restart. Refused/ambiguous claims must fail closed.
3. A separate gateway witnesses genuine model request/response and measured usage then signs a terminal outcome under a separately managed signing key. The exact gateway signer identity/key, signed terminal receipt and independent claim ledger must be reconciled on the same reservation and invocation. Either include authenticated `claim_id` linkage in a reviewed terminal contract or query the evaluator ledger before any qualification; **do not just infer linkage from local SQLite**.
4. Malaphor's independent verifier validates exact signed terminal bytes/key/bindings and one-use replay. **A True verifier result alone is insufficient without independent custody and claim/route evidence.**
5. Only then proceed to learner #86's matched FROZEN/LEARNED/PLACEBO/SHUFFLED unseen tasks, negative transfer, measured resource control and independent-process cold restart, scored by hidden evaluator truth.

No protected installation, credential/trust, endpoint ingress, production provider change, canonical memory write, or merge was performed. Source remains Draft/HOLD.
