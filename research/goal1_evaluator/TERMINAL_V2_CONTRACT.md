# Goal 1 terminal V2 contract and Integration #90 handoff

## Canonical wire envelope

Integration #90's source terminal payload is the compatibility baseline. V2 preserves its field vocabulary and adds no new bearer authorization path. The detached Ed25519 signature covers canonical UTF-8 JSON bytes containing exactly these fields:

- reservation_id, run_id, arm, challenge_id, challenge_view_digest
- model_prompt_sha256, model_identity, model_artifact_sha256
- gateway_id, invocation_id, claim_id
- status, response_sha256, prompt_tokens, output_tokens, gateway_wall_ms, backend_wall_ms
- key_id, terminal_utc, model_identity_scope

The signature is transported separately. The gateway must emit the exact payload bytes it signed, and each hop must preserve those bytes unchanged. Do not parse then reserialize to create the signature input. The evaluator verifies the detached signature over the received byte sequence, requires canonical encoding, and records SHA-256 of the exact received bytes. A parsed dictionary plus signature alone is not sufficient custody evidence if the original bytes were discarded.

## Terminal semantics

COMPLETED: response_sha256 is a lowercase SHA-256 digest; prompt_tokens, output_tokens, gateway_wall_ms, and backend_wall_ms are nonnegative integers; gateway_wall_ms is positive; model_identity_scope remains BACKEND_REPORTED_NOT_WEIGHT_ATTESTED. These are gateway/backend reports, not proof of loaded model weights or independent resource measurement. The receipt may enter downstream scoring only after all other custody and protocol gates pass.

OUTCOME_UNKNOWN: a valid, signed terminal state for an invocation whose outcome cannot be established. response_sha256 and all usage fields must be null, model_identity_scope must be UNKNOWN, it is never a prediction or score, and the reservation is permanently consumed/non-retryable. Do not recast unknown as failure, zero usage, or a new invocation. If no terminal can be emitted after a crash, durable RESERVED/CLAIMED state is still non-retryable and requires external reconciliation.

## Claim binding is separate evidence

Including claim_id in the gateway-signed terminal proves only that the gateway signed that identifier. It does not independently prove the endpoint issued the claim. The evaluator must independently authenticate and verify the claim authority's durable record or detached signed claim receipt, binding claim_id, reservation_id, run_id, arm, challenge_id/view digest, prompt digest, model/artifact identity, gateway_id, invocation_id, and CLAIMED state. This evidence must be fetched from a separately administered endpoint with pinned identity/key, not supplied by learner code or inferred from same-process booleans.

## Source implementation

terminal_v2.py verifies exact payload bytes, pinned gateway key/key ID, all binding fields, independent claim-verifier result, strict COMPLETED/OUTCOME_UNKNOWN semantics, and non-retryability. Its tests use synthetic ephemeral keys and a claim-authority double. They validate source behavior only; they do not instantiate independent custody or prove Integration #90 conforms at runtime.

## Private holdout

No labels, generation seed, challenge corpus, or answer key is stored in this branch. The previous four public synthetic HOLDOUT pairs are excluded from qualification. A genuinely unseen dataset requires an independently controlled custodian and separate storage/access audit; the current available execution boundary does not establish that custody. See PRIVATE_HOLDOUT_CUSTODY_CONTRACT.md. Until then, GOAL1_PRIVATE_HOLDOUT_GATE remains BLOCKED_CUSTODY_UNAVAILABLE.
