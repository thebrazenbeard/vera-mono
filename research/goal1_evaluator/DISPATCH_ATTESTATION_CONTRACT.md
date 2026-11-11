# Goal 1 signed dispatch-attestation boundary

**Status: source-level verifier + synthetic-key tests only. No real independent gateway, production key, model dispatch, or learning result is present.**

## Contract

    controller validates trial/run/arm/challenge/prompt
      -> durable one-use reservation is committed
      -> independent gateway receives the reserved invocation
      -> gateway performs exactly one selected-model invocation
      -> gateway signs a receipt over the exact invocation and measured result
      -> evaluator verifies the pinned gateway public key and consumes reservation once
      -> feedback may be released only after the committed prediction

Ed25519DispatchEvidenceVerifier is the source-level verification implementation in dispatch_attestation.py. It requires a deployment-pinned Ed25519 public key and gateway identity. The private signing key must remain outside the learner/controller OS privilege boundary. The verifier stores pre-dispatch reservations and consumed receipt IDs in SQLite with transactional uniqueness so duplicate reservations and replay after verifier process restart fail closed.

The signed envelope has an exact schema:
- witness_kind, gateway_id, signature.
- attestation_id, invocation_id, reservation_id, run_id.
- arm, challenge_id, challenge_view_digest.
- model_prompt_sha256, model_response_sha256, model_identity, model_artifact_sha256.
- dispatch_monotonic_ns, response_monotonic_ns, outcome_status.
- resource_usage containing gateway-signed non-negative input/output token counts and positive wall time in milliseconds.

The reservation is bound to run, arm, challenge, challenge-view digest, exact prompt digest, and pinned model identity/artifact digest. The signed receipt must match those fields. The response digest and outcome are signed by the gateway. The evaluator separately compares receipt bindings with the committed prediction request. A valid signature authenticates the signer and signed bytes; it does not establish that the gateway implementation is honest, that the selected model's reported artifact identity equals loaded weights, or that the signer is outside learner control. Those are deployment and independent-review obligations.

## Failure policy

- Missing, malformed, unsigned, wrong-key, wrong-gateway, or modified receipt: reject.
- Unreserved invocation, wrong reservation binding, substituted model/prompt/challenge, invalid timestamp order, missing measured usage: reject.
- Duplicate reservation, duplicate attestation/invocation ID, reused receipt, or replay after verifier reopen: reject.
- Signed OUTCOME_UNKNOWN: mark the reservation UNKNOWN and reject. Do not automatically retry or turn uncertainty into success.
- Same-host TestOnlyVerifier.verify() -> True: rejected at controller construction; generic boolean verifier injection is not an authentication interface.
- SQLite integrity is not tamper-proof against a process with the same OS privileges. The pinned key and replay store must be protected by a separately controlled deployment boundary.

## Evidence and limits

The test suite uses ephemeral test keys generated inside the test process. These prove cryptographic and state-machine behavior for synthetic fixtures only; they are not independent evidence. No production key has been provisioned, no gateway service has been installed, no outbound ingress has been enabled, and no selected QVR invocation was attested by this module. Until Integration supplies a real independently controlled gateway/observer plus a deployment-pinned public key and measured usage contract, the controller must remain unqualified for real model runs.

This verifier is not itself a causal-learning experiment. LEARNED/FROZEN/PLACEBO/SHUFFLED scoring still requires independently held-out truth, matched measured resource budgets, actual model execution, pre-feedback commitment, and observed behavior after a distinct-process cold restart. No learning claim is supported by these protocol tests.
