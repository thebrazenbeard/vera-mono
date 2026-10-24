# Goal 1 — experimental evaluator-held atomic claim and mTLS custody

**2026-10-24 · PR #89 Draft/HOLD · exact source head before this evidence file: `e883f53d448bee02f97a906ad3130ecdfc929a9a`.**

## What was implemented

Research-only `research/goal1_acceptance_bridge/evaluator_claim_custody.py` implements an operator-seeded SQLite evaluator reservation store, atomic one-use `RESERVED → CLAIMED` across concurrent processes, durable original canonical claim bytes with Ed25519 detached signature, bounded HTTPS/mTLS claim and readback routes, client-certificate CN-to-gateway-ID binding, and `ClaimEvidenceReader.verify_claim_evidence` which reads signed original evidence through mTLS and checks exact V2 binding against a separately supplied pinned evaluator public key. No gateway-accessible reservation creation endpoint exists. Research listener bind is restricted to parsed loopback IPv4 or CGNAT `100.64.0.0/10`, not string-prefix `100.`. All keys/certs in tests are ephemeral scratch fixtures, not production credentials or issuer/trust roots.

**Important authority limitation:** The test uses the same human-administrative owner of both source and host accounts; it does not establish independently administered signer custody even when host processes or machines are separate. The service is not deployed/installed and has not been exposed across machines. Host credential/ACL/firewall changes were not made.

## Immutable owners retained

- Canonical `main`: `64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Integration local QVR PR #82: `26271c5d69dee4663e07d4dbcf63efcf033626e8` (unchanged).
- Gateway PR #95: `7c191b2a97063ccc5821f3f274fb4f5e47ff99ed` (unchanged).
- Malaphor V2 PR #87: `d3784d9886a5cb071aed38fbe6b91f8ac1d6bbcf` (unchanged).
- Frozen PR #95 actual `authenticated_claim_client.py` SHA256 `1e89362990e250d197f71845f95d997f66b2384743db4ce2f8005ac1d565336a`, `sole_route.py` `ba20f64cf92dc6e58f4c82cecbe85963a6895ab97d5a3d4abfa961708945558d`. Frozen PR #87 claim helper `eeabe42d304515f0c068c30145230209af3f395ee49890ee6f5fba451772b2bc`, V2 `153aed3f37e013f9fbb213af2539a1984bebf3086a1d77544d189e0c8104d187`.
- Lappy isolated image `sha256:61f0481288d22df1071745463d83cedbf29489f8d71338dd09f9110357405c94` includes exact PR #82 QVR in Python 3.12.15, networkless, nonroot and constrained. Not installed as selected production route.

## Actually executed

**TDD:** Four atomic ledger tests initially RED at intentional missing implementation, GREEN 4/4. They exercise duplicate seed, unseeded/substituted reservation denial, eight racing claim processes/threads (one accepted, seven denied), cold ledger reopen, preserved canonical signed bytes. Real mTLS tests initially failed on Windows strict OpenSSL certificate verification. Corrected test fixture X.509 Authority/Subject Key Identifiers and CA keyCertSign usage **without disabling certificate validation**. Five mTLS tests GREEN: real TLS client/server authentication, wrong gateway certificate CN HTTP403, no client cert TLS refusal, wrong pinned evaluator Ed25519 key refusal, exact claim binding mismatch refusal. Two new tests RED exposing overbroad prefix-based `100.` bind guard; GREEN after IPv4 parser + `100.64.0.0/10` restriction.

Lappy Windows Python 3.14: **50/50** selected Goal 1 tests PASS with one external pytest-asyncio deprecation warning; includes earlier 39 QVR/bridge tests and new 11 custodian tests. Linux VN2 Python 3.12.3: **11/11** custodian tests PASS, compileall exit0. Both machines independently executed `physical_mtls_pr95_pr87_probe.py` against pinned real #95 HTTPS claim client, #95 GatewayDispatch and #87 claim helper and V2: real ephemeral loopback mTLS, evaluator SQLite and Ed25519 evidence, immutable original signed gateway bytes preserved and verified, one **FAKE backend** call; cold store reopens, duplicate claim refused, gateway public-key substitution denied. Both probe processes exit0. VN2 has no Docker; not a physical full-QVR invocation there.

Lappy additionally executed `full_qvr_mtls_custody_chain.py` with actual PR #95 mTLS client → temporary evaluator claim service → #95 dispatch (INERT backend) → original signed terminal → actual #87 V2 with mTLS-authenticated, evaluator-signed claim readback → outside stdio broker → actual PR #82 QualifiedVeraRuntime inside immutable, physically networkless Python3.12 Docker container → fresh container journal readback. Exit0; **one fake backend call and one QVR journal entry**. Result schema `GOAL1_FULL_QVR_MTLS_CUSTODY_CHAIN_V1`, `independent_operator=false`, `real_model_invoked=false`, `actual_selected_service=false`, `learning_qualified=false`. Gateway original signed terminal SHA256 in isolated run `af9793f983ec8c08e540c6ff8ffcd0ee1067a72a46bc3a490df6b7b036e962bd` (not portable run-independent attestation).

## Hostile review / material HOLD

> **ACCEPTED:** The evaluator service now exists as runnable research source, with real mTLS and durable signed evidence, but it is not independently governed. The same operator can control its scratch keys/SQLite. Even running the exact code on VN2 does not establish separate administrative signer custody.
>
> **ACCEPTED:** Container-tested QVR is not the selected Windows `VeraMonoPilot` service. Its stopped/manual state and unrestricted ordinary-host `127.0.0.1:11434` access remain a production gateway-only blocker.
>
> **ACCEPTED:** PR #95 backend was fake: no actual loaded Ollama weight/model-byte attestation, no real inference, no independent live readback across physical hosts, no held-out learning trial or benefit measurement.
>
> **ACCEPTED:** Test TLS cert/CA and signer keys are ephemeral same-actor fixtures; independently administered root, per-gateway credential provisioning, trust pinning, rotation/revocation, operator privilege isolation, lock/DoS/resilience and exact deployment/readiness must undergo separate threat review before activation.
>
> **ACCEPTED:** Current claim custody store permits admin to seed reservations offline; no assertion that a real evaluator admin has seeded challenge reservations or holds private test labels separate from candidate learner.

No production service/credential/trust/firewall changes, no merges to main, no provider/model mutation and no key publication. Blotter central credential still unavailable in Lappy/VN2 shells; only local six-event ledger read, no central write claimed. Issue #85 is the actual owner-coordination surface.
