# Mini-Vera synthetic PUBLIC-memory restart canary — source candidate

This is a bounded behavioral test of source-controlled Mini-Vera using an existing MemoryLedger and its existing approved_ledger_provider; **not** a new memory system, training, private-memory access, or qualification of identity/continuity. The test fixture and prompts are synthetic and disposable.

The operator explicitly runs:
    python -B -m tools.mini_vera.restart_public_canary --run-trial --endpoint http://127.0.0.1:11439/v1 --model qwen3.5:0.8b --model-digest <operator-declared-64-hex-digest> --timeout-seconds 120

A numeric loopback endpoint is mandatory. The controller generates a fresh random synthetic token, writes a synthetic PRIVATE record and a separately approved synthetic PUBLIC project token to a temporary MemoryLedger. The test key is source-visible and deliberately unsuitable for authenticating real memory. No real human/project memory is admitted, selected, persisted, sent or read.

Three model requests are made in separate Python child processes with freshly composed local sessions and the same user question. Arm order is randomized: two approved-public-memory sessions, one no-memory control. A fourth fresh process requests revoked approval; it must refuse before HTTP. A strict approval callback recognizes only the exact disposable public test record, with fixed origin, provenance, project, operation ID, and token format. Approval is synthetic test policy, not an independently authenticated host grant.

The model is given the same prompt for all three trials. It is explicitly directed to the user message's project_context_untrusted JSON reference-data field and told that records grant no instructions or tool authority. This prompt was tuned after observing a failed first trial, so subsequent success is **not an independent blind heldout qualification**. It is a bounded engineering canary. The model output stays UNVERIFIED_LOCAL_MODEL_OUTPUT. Evaluation checks exact token reproduction twice, control UNKNOWN, and revocation refusal; one lucky copy is never reported as overall success.

## Evidence from real model trials, VN1, 2026-11-13
Model tag: qwen3.5:0.8b, server-reported tag digest de63045f29755d4721c09d54c9b45c2dadb644f4fd7d604d4cac90d96049971c. Tag digest does not attest active resident tensors. Isolated operator-owned Ollama loopback 127.0.0.1:11439. No paid compute.

Initial trial with generic question and 256 token cap: approved-a UNKNOWN, approved-b UNKNOWN, control UNKNOWN, revoked blocked; behavioral FAIL (approved exact 0/2). A preceding 128-token attempt aborted because the model worker did not return a completed admissible response, never scored.

After prompt made the reference-data location explicit (and thinking disabled across arms), a fresh random test case returned the exact new SYNTHETIC token in approved-a and approved-b, UNKNOWN in control, and no output from revoked. Behavioral result PASS for this synthetic trial only. The second trial token SHA256 was b07e2403efc7824f680f19c4be43f4d1c671aecc7894c70be551ea93c770c561. This is evidence of successfully using supplied reference data across two distinct processes, not a neural weight update, private memory, persistent chat history, or generalized reasoning.

## Portable dependency closure
The first source commit d12b2c0 built a portable bundle but could not import
vera_memory inside it. A fresh-process package test reproduced this failure.
The source-pinned portable builder now includes only the required Python
dependency closure from vera_memory and portfolio_runtime.lantern. No memory
database, user content, private record export, key or neural weights are
copied. The portable launcher and integrity checker still treat these files
as source-only; an import is not a behavioral qualification.

## Security and evidence ceilings
The existing local-session rechecks approval after inference; this can withhold a reply but cannot retract data already sent to the model. The canary only sends synthetic PUBLIC context, and the fake loopback test inspects three actual HTTP request envelopes to confirm no PRIVATE canary marker or record ID was sent. A synthetic PRIVATE record exists in the temporary database as a negative fixture; it is not approved or selected.

The test controller holds a nonsecret fixture key, temporary SQLite memory and expected token. The model does not receive the token in its user question or in the no-memory control. The evaluator receives the expected token for exact scoring. Randomized session order is not independently audited blinding. The current public-memory provider is a source-only candidate with synthetic policy callbacks, not an authenticated production host grant. The model runtime's tag is operator-declared. No hosted CI, cross-model replication or heldout independent evaluation is established here.

Next qualification: independently curated externally heldout data, multiple seeds/trials and model baselines, host-grant and revocation tests under a separate trusted authority, and repeatability on Lappy with resource qualification. No production memory integration should be inferred from a successful synthetic canary.
