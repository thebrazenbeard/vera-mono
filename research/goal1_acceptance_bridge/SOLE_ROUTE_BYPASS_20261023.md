# GOAL 1 — Actual unclaimed model-dispatch bypass (2026-10-23)

**Disposition: EXTERNAL DISPATCH QUALIFICATION BLOCKED BY AN OBSERVED BYPASS.**

**Evidence class:** physical Lappy host-local observation using an ordinary, separately invoked Python/PowerShell user process. This process was not established to be the exact Vera learner or QVR service identity; the result nevertheless proves the existing local model endpoint is accessible without the proposed claim wrapper to at least this current user process. It is a selected-route threat that Integration must address, not proof that any installed Vera runtime consumed this route.

## Frozen current subjects

- Canonical `thebrazenbeard/vera-mono/main`: `64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Integration-owned #82: `26271c5d69dee4663e07d4dbcf63efcf033626e8` (Draft/HOLD; unmodified by this work).
- Malaphor-owned #87: `b9fcd93b4d9a7668369aa71e507ac7bfe4598ff6` (independent reservation-status/claim endpoint SOURCE contract + signed result verifier; no deployed independent gateway).
- Primary-owned #86: `27e7b2a2e312b9a969a1a70f2cc0277580b32e1a` (Draft/HOLD).
- Vera-owned #89: source-level claim-before-dispatch and crash/recovery acceptance tests (Draft/HOLD).
- `VeraMonoPilot` on Lappy: `Stopped` / `Manual`, observed in physical `Get-Service`; not started or modified.

## Actual Lappy observations

1. In a **general-user Python process without passing any evaluator reservation, claim ID, service identity, gateway-issued permit or signing credential**, HTTP `GET http://127.0.0.1:11434/api/tags` returned 200 and included the model tag `qwen3:4b-instruct`. That alone establishes registry visibility, not inference.
2. A second **direct** HTTP `POST http://127.0.0.1:11434/api/generate`, without entering `EndpointClaimedLocalDispatcher` or supplying any reservation/claim, with `model=qwen3:4b-instruct`, a harmless inert research prompt, `stream=false`, `keep_alive=0`, `num_predict=2`, `temperature=0` produced **HTTP 200**, `done=true`, exact model tag match, backend-reported `eval_count=2`, **two output bytes**, SHA-256 `565339bc4d33d72817b583024112eb7f5cdf3e5eef0252d6ec1b9c9a94e12bb3`, 5,509 host-local elapsed milliseconds. No raw model output was persisted in this document.
3. This is **one actual, unwitnessed local-model invocation** that bypassed claim enforcement. It is not proof of independent model weight bytes, cryptographic invocation attestation, token-usage authenticity, installed QVR selection or learning.
4. Exact #82 `local_cognition.py` exposes direct localhost GET `/api/tags` then POST `/api/generate` guarded by an in-process `InferencePermit`. The permit is expressly a synthetic research opt-in, not independent authority. Source access/host observation are separate facts.

## Hostile design review

> **ACCEPTED:** A caller-owned Python function wrapping Ollama cannot establish a *sole permitted model route* while the same user/process privileges can call Ollama's loopback API directly. A model proxy operating with identical access may remain bypassable. A 200 direct POST is decisive negative evidence for a claim that this host-user context already enforces evaluator authorization.

> **ACCEPTED:** The observed bypass does not prove that a future learner placed in a *different, genuinely restricted OS privilege context* could bypass. The current evidence identifies an unsafe access boundary for this user context; Integration must demonstrate actual learner privilege separation/route selection before making a universal claim.

> **ACCEPTED:** Disabling the raw model service, altering firewall ACLs or swapping service identities now could break existing working systems. This report does not authorize such protected host mutations or infer the correct isolation mechanism.

## Required Integration-owned acceptance sequence

1. Fresh-read exact #82, #87, #89, Issue #85, current service/process and host/user privileges. Select a concrete gateway + local-model OS/process boundary whose raw model transport is not accessible to the *actual learner/QVR route*. Use the smallest supported isolation method, not an in-process boolean or caller-supplied key.
2. Independently administered evaluator endpoint must durably issue `RESERVED` and atomically `CLAIMED` for exact `reservation_id`, run, arm, challenge/view digest, prompt digest, pinned model/artifact identity, gateway and invocation. Gateway authenticates evaluator endpoint and vice versa. Source-only injected helper does not count.
3. **Before any real outbound model call**, gateway commits local reservation and obtains one exact matching authenticated remote `CLAIMED`; if denied, expired, revoked, unknown or timeout: zero model calls; preserve ambiguity; no automatic retry.
4. **Negative physical test, in the actual learner's restricted privilege context:** the direct `/api/generate` bypass attempt is denied *without* an independently authorized gateway claim. Record process identity, route, target, outcome and exact source/artifact/config cut. This is the blocking regression test that PR #89 cannot pass on the observed current host context.
5. **Positive physical test:** the same learner can request exactly one bounded, synthetic gateway-mediated model invocation under an evaluator-issued reservation; independently controlled gateway witnesses actual request/response bytes and usage/time, produces a signed COMPLETED (or conservative signed OUTCOME_UNKNOWN) receipt; Malaphor verifier accepts/rejects as appropriate against the exact reservation and prevents replay after process restart. No hidden labels leak.
6. Distinct-process crash before claim, after remote claim, after local claim and after provider effect; reconcile with evaluator-owned ledger without invented success or duplicate model invocation.
7. Only then progress to #86 four-arm matched-resource unseen-case/reversal/negative-transfer tests and true process-restart behavioral retention. Green local source tests by themselves are **never** a learning result.

**Authority:** This is a read-only negative host probe and Draft PR evidence artifact; no permission to alter credentials/trust, model provider, Windows service identities/firewall/TLS, install or activate new gateways, or merge main. Seek Patrick's explicit approval for exact protected effects if needed.

**Owner handoff:** Integration #82 owns actual gateway/route changes; Malaphor #87 owns independent evaluator custody and receipt verifier; Vera #89 owns noncolliding acceptance evidence. Do not modify delegated branches from this lane.
