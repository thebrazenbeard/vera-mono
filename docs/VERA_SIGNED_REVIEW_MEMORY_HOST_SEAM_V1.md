# Signed reviewed-memory host seam, V1

Status: ENGINEER B CANDIDATE; NOT PRODUCTION REVIEW AUTHORIZATION.
Source base: vera-mono/main@49a779017ded184c22712ec1a0dc7a8b558faf71.
Purpose: narrow read-only memory influence at a real local model with a cryptographically bound receipt, durable replay prevention, and independently falsifiable evidence. This is not autonomous learning, ChatGPT account memory, or a runtime identity.

## Exactly what exists

- vera_core.signed_review_attestation.verify_signed_review_attestation: pure Ed25519 signature and exact-scope verifier. It accepts only canonical bounded JSON signed with a domain separator, matching an EXTERNALLY trusted 32-byte Ed25519 public key. Signed fields bind project ID, identity ID, canonical state-root SHA256, record ID and digest, memory CAS head, privacy reference, association, exact cue and use evidence IDs, review evidence reference, and a ten-minute maximum validity window. Duplicate JSON keys, unknown fields, changed data, wrong keys, wrong scope, noncanonical signatures, expired or future-signed receipts fail closed. Signature checking DOES NOT authenticate human consent, signer independence or public-key provenance.
- vera_core.qualified_review_use.consume_attested_reviewed_memory: reads only an exact current bounded WORKING_PROJECT record in an explicitly bound state directory, rejects stale/superseded or aliasing memory files, checks signature against that record and its privacy reference, then consumes the existing DurableLearnedInfluenceGate qualified cue once. Matching the signed review evidence reference now happens INSIDE the same SQLite transaction before inserting use evidence, so a wrong review cannot burn the cue. Returns untrusted data; grants no authority.
- vera_core.reviewed_chat_advisory.advise_with_host_signed_memory: host-only, opt-in composition of verified retrieval with the existing exact-loopback, effectless local-model adapter. The record is explicitly labeled untrusted and cannot grant tools, writes, protected effects, or other authority. It is NOT wired into the production vera-mono chat command.
- vera_core.local_model_advisory: optional 0.0–1.0 temperature parameter, existing default 0.2 unchanged. Supports zero-temperature reproducibility without non-loopback networking.

Source tests use disposable SELF-GENERATED signer keys, not actual independent reviewers, and exercise wrong signer, identity, project, root, record revision, memory head, privacy, review reference, cue/use IDs, time, malformed/duplicate JSON, stale records, database aliases, missing qualified review, durable replay on fresh Python process, and no model contact on denial.

## Live synthetic Lappy evidence, November 19, 2026

A real local qwen2.5-coder:1.5b-instruct-q8_0 model was contacted through the existing loopback /v1/chat/completions adapter. In separate Python processes using disposable memory and a SYNTHETIC signed reviewer, the current corrected rule returned HOLD for evidence containing only HTTP 200 and ticket 201. An otherwise matched no-correction control returned PASS on the zero-temperature run. Wrong signing key was rejected before model contact; reused cue failed on later process. The ephemeral fixture private key was not persisted. No real human approved the fixture review and no private screen image was produced.

A second repeated inference-only probe reconstructed the EXACT same SHA256 prompt hashes (86f295c9... signed-context preview and 789a9760... old-rule control) WITHOUT repeatedly consuming a one-use signed cue:
- At temperature 0.0: signed-context preview 20/20 HOLD; old-rule control 20/20 PASS.
- At default temperature 0.2: signed-context preview 20/20 HOLD; old-rule control 7/20 PASS and 13/20 HOLD.

This is a small synthetic task, not a general accuracy claim. Temperature materially affected the control's answer. Private harness source on Lappy:
- D:\VERA\_agent-work\engineer-b-signed-advisory-temp0-20261119 (source SHA256 08CC2B0E5264F1BFC9AE6DA2EE368EA8B9C8C237898CC6A8BA3754B00802F449).
- D:\VERA\_agent-work\engineer-b-advisory-stability-20261119 (source SHA256 73B6FD50D71BBCAF497D9C4BB8411662083F3FA71662B0FF93CE4598B75D3322).

No private screen images, credentials, intimate material or canonical memory records were published.

## Security and approval dependencies

> Hostile challenge: Anyone who can present both a self-signed receipt and its own public key can satisfy a mathematical signature check. That is NOT independent review. A source test with an ephemeral key demonstrates algorithm correctness only.

> Hostile challenge: Even a valid signed cue does not force a model to heed a correction. Real-model runs need protected controls and repeatability; no model reply grants effect authority.

Engineer A's host/runtime/security lane and BT2 independent hostile review must supply a separate authenticated REVIEW BROKER and operator-owned signer trust registry not redefinable by an untrusted model, prompt or worker. Broker must bind exact project/identity/state root, current memory revision and privacy, reviewer identity and reasoned approval, cue nonce/use evidence, TTL and revocation. Private signing keys must NEVER enter GitHub, memory records, model prompts, or logs. Verify Windows ACLs, installed host identity, wrong-user/wrong-state, key rotation, stale and replayed requests. A worker presenting its own signer and own key is NOT acceptable production review.

The production CLI remains fail-closed: _require_independent_review_attestation() refuses reviewed memory before opening state or contacting a model. Never monkeypatch this guard in a deployed process. A real authenticated host provider with a securely administered trust root and separately qualified privacy/consent is currently missing.

Minimum acceptance: real independently approved host-broker review; new separate process consuming exactly current signed review and replay fence; real local model positive/negative controls; denied revoked/foreign/stale/wrong-privacy/replayed capsules; independent BT2 readback. Protected host effects require a separate authorization path. Merge, install, activation and canonical memory promotion remain HOLD.

Rollback: revert this candidate branch. No signing keys, production service, account settings, canonical state, existing worker branches or Windows listeners are changed by the candidate source.