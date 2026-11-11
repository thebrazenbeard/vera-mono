# Goal 1 selected claim-before-dispatch candidate — 2026-10-23

**Disposition: SOURCE-LEVEL INTEROP DEMONSTRATED; INDEPENDENT ENDPOINT / SELECTED GATEWAY NOT DEPLOYED; LEARNING QUALIFICATION BLOCKED.**

## Authority, sources and protocol decision

- Vera Mono main at orientation: `64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Integration-owned Draft #82 exact head `26271c5d69dee4663e07d4dbcf63efcf033626e8`, `packages/vera_core/src/vera_core/local_cognition.py` imported as isolated local research model transport. Not `vera_core.QualifiedVeraRuntime` installation or selected live route.
- Malaphor-owned Draft #87 head `b9fcd93b4d9a7668369aa71e507ac7bfe4598ff6`, `research/goal1_evaluator/reservation_status_contract.py` (Git blob `e4b142ad121e73a53e64251bc9e109be6131d53e`; Lappy downloaded bytes SHA-256 `eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc`), `RESERVATION_STATUS_ENDPOINT_CONTRACT.md`. His Issue #85 checkpoint `6376259522` selects a *gateway-pulled authenticated reservation claim endpoint*, not a signed bearer authorization. Reuse `claim_dispatch_authorization` exactly.
- Primary-owned Draft #89 contains additive `research/goal1_acceptance_bridge/endpoint_claim_dispatch.py`; accepts a `claim_authorization` callable and client. Research composition must supply the exact #87 helper and a separately authenticated endpoint client once it actually exists. Do not silently substitute a new protocol.
- Unselected previous signed-bearer ticket `reservation_auth.py` and its test were removed from PR #89's current tree, but their historical evidence report remains marked **RETIRED**.

## Local source sequence

1. Validate exact eight-field controller reservation, public challenge/prompt digests, model and artifact claim before creating any attempt.
2. Transactionally persist local SQLite `RESERVED` with run/arm/challenge/reservation/invocation identities and no claim ID.
3. At the **inside-transport edge**, call the injected exact #87 `claim_dispatch_authorization(client, reservation, gateway_id, invocation_id)`. The endpoint client must authenticate remote server and gateway and perform a durable atomic one-use `RESERVED → CLAIMED` externally. **No such client, endpoint, auth or key was provisioned by this change.**
4. If (and only if) a matching `CLAIMED` response is returned, persist its `claim_id` in the local SQLite attempt **before** the call to `LocalCognitionGate.generate`.
5. Dispatch to local model only afterward, record `COMPLETED` or conservative `OUTCOME_UNKNOWN`. Any claim denial/malformed response/timeout results in `OUTCOME_UNKNOWN` locally, with zero model calls; the same run/arm/case cannot be retried even with a fresh invocation ID. It is conservative ambiguity, not a claim that dispatch occurred.
6. Distinct-process SQLite readback preserves the local row. This is not an independently signed outcome receipt; `independent_attestation=False`.

## Reproducible physical evidence

- TDD RED: new endpoint claim tests initially could not import `endpoint_claim_dispatch` on physical VN2 because implementation did not exist.
- After implementation, physical **VN2 Linux** and **Lappy Windows** passed 27/27 local tests plus Python compilation while the older, subsequently retired ticket tests still existed. After selecting one protocol, source of retired ticket route and its tests were deleted; the final reduced suite will be verified separately.
- New local tests include pre-claim durable RESERVED observation, persist `claim_id` before dispatch, claim refusal → no dispatch + OUTCOME_UNKNOWN, ambiguous endpoint timeout → no retry, changed prompt before endpoint call, duplicate same case rejection, and an intentional same-process fake `claim_authorization` bypass counterexample.
- A physical **Lappy** run loaded actual #87 `claim_dispatch_authorization` from the immutable head above and injected a same-process **test-only endpoint double** (not a network endpoint). An endpoint response with a substituted gateway ID was correctly rejected, zero model calls. The next attempted reservation for the **same run+arm+case** was rejected by durable uniqueness. In a fresh test DB, a denied FROZEN arm produced `OUTCOME_UNKNOWN`, an attempted new FROZEN invocation was blocked, and a **distinct LEARNED arm** was allowed, yielding one actual loopback Qwen3:4b-instruct call: `COMPLETED`, 2 output bytes, response SHA256 `565339bc4d33d72817b583024112eb7f5cdf3e5eef0252d6ec1b9c9a94e12bb3`, host-local elapsed **7,156 ms**, local claim ID `synthetic-claim-2`, `independent_attestation=False`. Note: the arm name LEARNED is only a transport/test identifier; **no learning or adaptation happened**.

## Hostile review — accepted

> **A successful injected helper and endpoint double is not authenticated transport or independent issuer custody.** A compromised same-process client can return fabricated `CLAIMED` data. The new code includes a deliberately passing demonstration of this bypass. `claim_id` is locally logged, not externally attested. The source cannot prove the gateway is the sole route: raw Ollama and `LocalCognitionGate` remain accessible from ordinary code paths.

> **An atomic remote CLAIMED state without an authenticated terminal outcome does not establish actual model/weight provenance, chronology or resource consumption.** The independent gateway still needs protected authentication, sole-route isolation, signed COMPLETED/OUTCOME_UNKNOWN receipt, and replay-safe reconciliation. Malaphor's #87 verifier remains separate, unconnected and unqualified.

> **A denied claim marking local OUTCOME_UNKNOWN is conservative, not precise.** The adapter intentionally sacrifices a retryable failure distinction to avoid duplicate dispatch. A future genuine gateway must distinguish pre-dispatch reject from ambiguous transport failure without inventing outcomes, and the evaluator's protected claim ledger is authoritative.

No protected credential, trust key, ingress, persistent service, main merge, QVR cutover, canonical memory or hidden evaluator truth was modified. Integration #82 remains the owner of the actual selected gateway/transport; Malaphor #87 retains independently controlled authorization, signed result verifier and hidden truth; #86's four-arm cold-restart learning qualification remains later.

**Current next gate:** Integration must supply independently authenticated claim transport and sole-route gateway, with separately controlled endpoint; then test real remote CLAIMED → signed terminal outcome → evaluator acceptance against held-out secret cases. Until then, the result remains an isolated source/host compatibility experiment.
