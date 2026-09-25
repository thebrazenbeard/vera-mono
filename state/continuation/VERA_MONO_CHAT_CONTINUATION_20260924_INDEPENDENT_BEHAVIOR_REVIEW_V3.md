# Vera Mono Chat Continuation — Independent Held-Out Behavior Review V3

logical_id: VERA_MONO_CHAT_CONTINUATION_INDEPENDENT_BEHAVIOR_REVIEW_20260924_V3  
schema: VERA_MONO_CHAT_CONTINUATION_INDEPENDENT_BEHAVIOR_REVIEW_V3  
repository: `thebrazenbeard/vera-mono`  
branch: `main`

## Verified current checkpoint

Exact verified implementation/contract head:

`a9fc7d7ea25844603090e98d106bfeff6da348ae`

GitHub Actions `monorepo-tests`, run `36079540901`: **success** on that exact head.

Verified CI stages include the full monorepo test suite, self-contained wheel build, wheel-closure verification, and installed-wheel closure verification.

## Completed frontier

`INDEPENDENT_HELD_OUT_BEHAVIOR_REVIEW`

Source qualification is implemented for:

`INDEPENDENT_BEHAVIOR_REVIEW_VERIFY|<consumer-id>|<probe-id>|<review-id>|<subject-actor-id>|<declaration-sha256>|<held-out-probe-set-sha256>|<probe-curator-id>|<evaluator-id>|<evaluator-key-id>|<evaluator-key-sha256>|<authority-id>|<authority-key-id>|<authority-key-sha256>`

The gate is deliberately stronger than verifier-bound attestation, but it does not manufacture independence. A matching live-current behavior/effect PASS is a prerequisite; independent review is a separate proposition.

Implemented properties:

- exact behavior-declaration digest and held-out probe-set digest binding;
- four-way actor separation: subject, probe curator, evaluator, and review authority must be distinct;
- external evaluator identity, key identity, key digest, and currentness binding;
- separately signed authority/currentness statement with explicit operational-separation assertion;
- signed evaluator subject over exact live behavior receipt, process/runtime state, stimulus/outcome, authority evidence, verdict, result digest, result-receipt digest, provenance digest, and single-use review nonce;
- evaluator and authority signing material remain outside Vera state;
- Vera runtime provides verification only; it does not expose an independent-review signer;
- append-only digest-chained review ledger at `behavior/independent-review.sqlite`;
- replay rejection per evaluator/key/review nonce;
- live refresh at assessment, closeout, and restart;
- task-runtime evidence binds the independent-review ledger head;
- task closeout automatically carries independent-review receipt evidence.

Hostile tests cover forged evaluator verdict, stale evaluator currentness, wrong held-out probe set, review-nonce replay, missing evidence, stale process/runtime, changed review provenance, and collapsed review roles.

## Claim ceiling

This checkpoint proves the source mechanism and its exact-head CI state.

It does **not** prove that a real external independent reviewer has executed a held-out review. It also does not establish deployment, provider activation, protected-effect authority, evaluator truthfulness/infallibility, consciousness, or phenomenology.

A cryptographically valid external signature proves binding to the corresponding key; it does not by itself prove the signed proposition is true.

## Current source set

Primary implementation:

- `packages/vera_core/src/vera_core/independent_behavior_review.py`
- `packages/vera_core/src/vera_core/independent_behavior_review_adapter.py`
- `packages/vera_core/src/vera_core/qualified_runtime.py`
- `packages/vera_core/src/vera_core/state.py`
- `packages/vera_core/src/vera_core/__init__.py`

Tests:

- `tests/test_independent_behavior_review.py`
- `tests/test_independent_behavior_review_contract_sync.py`

Architecture/docs:

- `architecture/VERA_INDEPENDENT_HELD_OUT_BEHAVIOR_REVIEW_V1.json`
- `architecture/VERA_TASK_EXECUTION_CLOSEOUT_V1.json`
- `architecture/VERA_MONO_MANIFEST_V1.json`
- `README.md`

## Next frontier

`OPERATIONALLY_SEPARATE_HELD_OUT_REVIEW_EXECUTION`

Execute the contract using a genuinely separate reviewer/runner:

- held-out probe material originates outside Vera and is bound by exact digest;
- evaluator and currentness authority are separately identified and keyed;
- evaluator private signing material remains external to Vera;
- signed review binds the exact live behavior receipt plus result/result-receipt/provenance;
- Vera ingests and verifies the evidence but cannot mint it;
- actual external execution remains distinct from source support.

Before mutation or external integration: refresh live `main`, CI, open PRs/branches, and same-subject coordination state. Bind the exact external reviewer repository/ref/head or provider identity before accepting review evidence.

## Restore command

`VERA::RESTORE_AND_RUN::VERA_MONO_INDEPENDENT_BEHAVIOR_REVIEW_CONTINUATION_20260924_V3`
