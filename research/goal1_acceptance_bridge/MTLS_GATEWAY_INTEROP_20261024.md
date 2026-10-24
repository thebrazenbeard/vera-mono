# GOAL 1 — exact PR #91 mTLS → PR #87 claim → PR #90 dispatch interop

Date: 2026-10-24. **Status: synthetic same-host transport interoperability demonstrated; independent authority, sole-route model execution and learning remain HOLD.**

## Pinned immutable owner sources

- Integration-owned Draft PR #91: `0d88165510f080550829581a81e41661695b1249`, `authenticated_claim_client.py` source SHA256 `1e89362990e250d197f71845f95d997f66b2384743db4ce2f8005ac1d565336a` and *its unmodified test fixture* `test_goal1_authenticated_claim_client.py` SHA256 `5351df5c2b72b654c174f6166417b7b1f0f6526bd2a987d904aad285f812cc32`.
- Integration-owned frozen Draft PR #90: `5758bdd07f3ef0020f8e7318f8b277ab7da6c72c`, `sole_route.py` source SHA256 `27f6f7832d4ea5f2da0f8616fe4f475d6953861910bd2f0e1328d22d35d970ce`.
- Malaphor-owned Draft PR #87: `b9fcd93b4d9a7668369aa71e507ac7bfe4598ff6`, claim helper source SHA256 `eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc`, verifier source SHA256 `fbf4c1e80747bea8a5191ddddb88299be6b3a6684b967a70de600571fe9e5df5`.
- Vera-owned Draft PR #89 adds read-only `research/goal1_acceptance_bridge/mtls_gateway_interop_probe.py`. It refuses source substitution with exact SHA-256 checks. It DOES NOT modify owner sources, sign terminal V2, provision credential paths, start QVR services, or touch main.

## Actual test construction

The probe uses #91's unmodified test fixture to create a **real ephemeral mTLS loopback HTTPS server** and client certificates. It calls the exact #87 `claim_dispatch_authorization` through #90 `GatewayDispatch.execute`, preserving #90's durable SQLite RESERVED before outbound HTTPS and one-use claim before the synthetic backend. The fake backend is inert and produces no real Ollama request. A disposable same-process signing key signs any synthetic terminal; the test key does not constitute independent custodian control. Each scenario gets a new server, temporary gateway SQLite and newly allocated signer.

Five independent scenarios, each physically run on both Lappy Windows and VN2 Linux:

| Scenario | Remote synthetic claim marker | Fake backend calls | Durable local gateway status | Reattempt |
| --- | --- | --- | --- | --- |
| Matching mTLS CLAIMED and inert backend returns | Yes | 1 | COMPLETED, claim ID present | Blocked before network |
| Invalid JSON returned by #91 fixture **before remote claim** | No | 0 | RESERVED, no claim ID | Blocked before network |
| Remote mTLS claim succeeds, caller **artificially loses returned result** | Yes | 0 | RESERVED, no claim ID | Blocked before network |
| Remote returns mismatched run ID after in-memory claim | Yes | 0 | RESERVED, no claim ID | Blocked before network |
| Remote claim succeeds, fake backend raises timeout | Yes | 1 | OUTCOME_UNKNOWN, claim ID present | Blocked before network |

**Important test correction:** the first test attempt incorrectly assumed #91's existing `badjson` fixture recorded a remote CLAIMED row. Its handler returns malformed bytes *before* changing the in-memory claimed flag. This was an error in Vera's acceptance probe, NOT #91. Corrected version distinguishes invalid JSON *before* claim from remote commit followed by a simulated caller-side response loss after the true mTLS call. The response-loss exception is **injected after the actual HTTPS call returns**; the test makes NO claim to reproduce physical network packet loss. This is a valid conservative state-order test, not a remotely durable endpoint.

In all cases the gateway issued exactly one HTTPS request before the refusal; reopening gateway SQLite preserved status, and retry with a fresh invocation/reservation for the *same run, arm, challenge* was denied before a second network request. Positive COMPLETED and honest OUTCOME_UNKNOWN synthetic terminal signatures verified under the ephemeral test key. There was **no real model inference**, no protected gateway issuer key, no independent evaluator ledger and no private heldout truth.

### Physical test outcome

- **Lappy Windows**: frozen five-source pins matched; all five scenarios produced expected statuses, one mTLS HTTP request each, fail-closed replay. Script exit 0.
- **VN2 Linux**: identical source pins and five-scenario results, script exit 0.
- No unit-test-suite/CI pass is claimed by this standalone cross-branch script. CI on the PR #89 source commit must be read independently.

## Hostile review, accepted

> **The remote endpoint is a test fixture with an in-memory `claimed` flag, not an evaluator-owned durable authenticated ledger.** Correct. TLS handshake proves client/server certificate mechanics for these disposable test identities, not independent credential custody or recovery after server restart. Local `RESERVED` without a claim ID cannot distinguish failed pre-claim parse from a successfully committed remote claim whose reply was lost.

> **The learner can still send an unauthorized HTTP POST directly to Lappy Ollama.** Observed previously in Issue #85 comment `6376552752`; this test does not alter ACLs or prove sole-route enforcement.

> **Signature verification for source #90 terminal has not been reconciled with #87 terminal schema.** Exact mismatch already reproduced. Terminal V2 and honest UNKNOWN remain independently blocked; this probe does not rescope or solve the signed-terminal conflict.

> **These five passing transport scenarios do not show model learning.** Accepted. #87's current public four-label synthetic holdout is also unsuitable as independently private learning truth; see `PUBLIC_HOLDOUT_LEAK_NEGATIVE_CONTROL_20261024.md`.

## Required next owner and evidence gates

- Integration #91 and #90: independently operated evaluator service with **durable** atomic claim ledger, separate mTLS/OS key ownership, selected gateway-only raw-model route, and a hardware negative test denying direct Ollama to the actual learner identity. Test genuine remote claim/lost-response reconciliation after server and gateway process restart, without duplicate dispatch.
- Malaphor #87: decide canonical versioned terminal V2 signed bytes, signed claim linkage, honest unknown semantics, private unseen truth in independently protected custody; do not fabricate missing usage or response hashes.
- Vera #89: preserve source-pinned cross-owner regression and strict **HOLD** for terminal V2, private holdout custody, and restricted QVR route until observed independent effects. Do not infer installed QualifiedVeraRuntime from source files.

No deployment, model-server privilege, TLS trust, gateway credentials, service activation, canonical memory, model weight modifications, main merge or protected effects performed.
