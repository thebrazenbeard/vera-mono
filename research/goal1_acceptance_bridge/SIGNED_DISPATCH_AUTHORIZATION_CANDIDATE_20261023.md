# Goal 1 opt-in signed dispatch authorization candidate — 2026-10-23

**Claim ceiling: SOURCE-LEVEL GUARDED DISPATCH + SAME-HOST TEST KEY. This is not a configured or deployed gateway, independent witness, production authorization, QVR-selected route, model-weight verification, measured-token attestation, or learning result.**

## Why this increment exists

Vera's earlier local adapter `LocalAttemptStore.execute_controller_reserved` accepted an eight-field `reservation` dictionary shaped like Malaphor's PR #87 `CausalTrialController.reserve_invocation`. It checked exact run/arm/challenge/prompt/model fields and SQLite replay but could not authenticate the issuer: a forged well-formed dictionary passed, demonstrated by `test_structurally_valid_forgery_still_dispatches_without_authentication`.

Without editing Integration-owned PR #82 or Malaphor-owned PR #87, Draft PR #89 adds opt-in `research/goal1_acceptance_bridge/reservation_auth.py` to **verify** Ed25519-signed dispatch authorization under a pinned public key before passing an eight-field reservation to the existing durable local attempt fence. The module has **no private-key/signing function and no network/service setup**. This is a *proposed additional authorization envelope*, not an existing #87 controller output.

## Candidate authorization contract — no issuer claimed

Canonical signed JSON excludes only `signature_b64`; all other fields are signed:
`schema=GOAL1_DISPATCH_AUTHORIZATION_CANDIDATE_V1`, `audience`, `invocation_id`, `route_ref`, `max_tokens`, `issued_at_epoch`, `expires_at_epoch`, and a `reservation` dictionary consisting of exactly `reservation_id`, `run_id`, `arm`, `challenge_id`, `challenge_view_digest`, `model_prompt_sha256`, `model_identity`, `model_artifact_sha256`. The trusted issuer public key, audience, selected model, declared artifact identity and reported registry digest are set at dispatcher construction; the ticket cannot supply or replace the pinned key. Expiry is strictly enforced with maximum 120-second ticket lifetime. The model is never called for invalid/missing signatures, wrong key/audience/expiry, altered signed fields, or mismatch against the public challenge/prompt/model. A SQLite local reservation is committed transactionally before the outbound call and cannot be reused after completion/unknown.

**Crucial adoption prerequisite:** Malaphor's current #87 `reserve_invocation` issues an *unsigned* eight-field dictionary in an evaluator-controlled test-process state; it does not mint this candidate signed token. No independent issuer or pinned trusted gateway configuration was created. This candidate must be reviewed/reconciled with #87's actual intended reservation transport instead of silently assuming compatibility.

## Exact physical verification

1. Test-first RED on real VN2 Linux: importing `reservation_auth` raised `ModuleNotFoundError` before new code was created.
2. Synthetic Ed25519 test-only signer; physical VN2 Linux Python and Lappy Windows Python, exact files fetched from GitHub into existing disposable research trees. **21/21 tests passed on EACH host**, consisting of 7 new signed-authorization tests + 14 prior controller/local reservation tests; Python compile passed on both. Tests cover wrong/missing key/signature, missing and extra fields, wrong audience and expiry, tampered signed fields, prompt/view substitution, successful one-use dispatch, and replay across a fresh store instance. All positive tests use disposable same-process signing keys and a `CountingTransport` test fake.
3. One additional **actual** Lappy loopback Ollama Qwen3 4B research inference through the opt-in signed wrapper and exact PR #82 standalone `LocalCognitionGate`, `max_tokens=8`, disarmed-by-default gate armed only for this isolated call, 10-second timeout. A private test key was generated **within this one temporary Python process** and not persisted or printed. It is NOT Malaphor's key.
   - Preflight `unsigned` and `tampered` authorizations each rejected with **zero** local model calls and **zero** SQLite attempts.
   - Test-signed authorization issued to `lappy-research-gateway-01` succeeded in one actual local model call, reported model registry tag `qwen3:4b-instruct` digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`; response **2 bytes**, SHA-256 `565339bc4d33d72817b583024112eb7f5cdf3e5eef0252d6ec1b9c9a94e12bb3`, local measured elapsed **4,874 ms**. Local SQLite `COMPLETED`, `independent_attestation=False`, exactly one attempted invocation `signed-research-20261023-01` and one reservation `signed-research-res-20261023-01`.
   - **Another newly launched Windows Python process** reopened the same host-local SQLite file; one terminal completed row was present and a same-ID reservation replay was rejected. The temporary test signing key was not available to the second process. No re-dispatch took place.
   - Candidate module local SHA-256 readback on Lappy: `c3a60badd8a16cbe08038272c6a20b5d790fe8d464e23fe1c9e8da1ef10898f0`.

## Hostile falsifiers, preserved

> **ACCEPTED:** A caller able to instantiate `AuthorizedLocalDispatcher` with its own public key can create self-authorized tickets. True authority therefore depends on *deployment-pinned signer trust* outside the candidate's control. The constructor alone is not that trust boundary.

> **ACCEPTED:** Anyone who can call `LocalCognitionGate`, Ollama, or `LocalAttemptStore.execute` directly still bypasses this wrapper. Only a separately administered and *sole permitted* dispatch gateway with network/process restrictions could enforce exclusive authorization. No such enforcement exists here.

> **ACCEPTED:** A signature over an authorization request does not attest that the selected model weights were loaded, that a call happened at a given time, that response bytes or resource accounting were honestly observed, or that hidden evaluator truth is independent. The downstream signed **outcome** receipt still belongs to Malaphor's #87 verifier and a protected observer. This candidate produces NO gateway-signed outcome.

**Next integration subject:** obtain owner review of whether Malaphor's evaluator should sign a short-lived, gateway-audience-bound invocation permit or instead operate a private authenticated reservation-status endpoint. Integrate that protocol into the separately controlled gateway selected by Integration without altering #82/#87 under active delegation or changing service, keys, ingress or production route without Patrick's explicit authorization. Cold-restart causal learning remains later and entirely unqualified.

This is source-only evidence, not permission to deploy or merge.
