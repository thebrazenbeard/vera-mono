# Goal 1 reservation authorization: preferred contract

## Decision

Prefer a **gateway-pulled, independently authenticated reservation-status/claim endpoint** over evaluator-issued short-lived signed bearer tickets.

A signed ticket can be forged only if the signing key is compromised, but a stolen valid ticket can be replayed during its validity window unless the gateway also maintains atomic one-use state. It also creates a key-distribution and rotation dependency and can authorize dispatch while a revocation/status change is not observed. Short TTL narrows, but does not remove, those risks.

A status endpoint gives the selected gateway a fresh, atomic claim at the dispatch boundary. It can reject revoked, expired, consumed, or mismatched reservations and bind a claim to one authenticated gateway identity and one invocation ID. It is stronger only if the endpoint is independently administered, authenticated both ways, and performs a durable atomic RESERVED -> CLAIMED transition. A same-process mock or local SQLite function is not an independent endpoint.

## Required flow

1. Evaluator durably creates RESERVED with a unique reservation ID and binds run, arm, challenge ID/view digest, exact prompt digest, pinned model identity, and artifact digest.
2. The only permitted model gateway authenticates to the reservation endpoint using deployment-managed service identity (e.g. mutual TLS or equivalent), and the endpoint authenticates the gateway identity. The gateway must verify the endpoint server identity.
3. Immediately before any model/network dispatch, gateway submits reservation ID plus invocation ID and its authenticated gateway identity.
4. Endpoint atomically verifies all bindings and transitions RESERVED -> CLAIMED, binding exactly one gateway and invocation. A second claim, changed invocation, wrong gateway, expired/revoked reservation, or unknown reservation fails closed. Durable state survives endpoint restart.
5. Only after successful claim may the gateway dispatch. It emits a separately signed terminal COMPLETED or OUTCOME_UNKNOWN receipt with response digest, model/artifact identity, chronology, and measured usage. Unknown outcome is terminal; no automatic retry.
6. Gateway is the only route to the selected model. Raw Ollama/local transport and alternate adapters must be inaccessible to the learner/controller privilege domain. Otherwise this protocol is bypassable.

## Why not evaluator-signed tickets?

Tickets are a reasonable fallback for disconnected gateways, but require a separately held evaluator signing key, a gateway-pinned issuer key, strict audience and expiry checks, and a durable atomic nonce/claim ledger at the gateway. That last requirement recreates most of the endpoint's statefulness while retaining a bearer artifact that can be copied. Do not deploy both mechanisms as ambiguous alternate authorization paths; select one.

## Source status and security boundary

reservation_status_contract.py defines a small typed source-level contract and fail-closed response-binding checks. Its test doubles validate the client contract only. They do not implement transport authentication, independent custody, atomic remote state, or a sole-route gateway. A compromised process can fake a client response; a caller can bypass this helper and invoke a model directly. Those protections require Integration #82's independently administered endpoint/gateway and host/network isolation, none of which this PR provisions or activates.

No key or hidden labels are created, stored, or published by this contract. No credentials, services, ingress, or trust settings are changed.
