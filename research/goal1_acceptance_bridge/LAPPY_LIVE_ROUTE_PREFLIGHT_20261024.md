# GOAL 1 — physical Lappy selected-route/read-only access inventory (2026-10-24)

**Disposition: ACTUAL LEARNER SOLE-ROUTE UNQUALIFIED; ACCESSIBLE ORDINARY SESSION; NO PROTECTED HOST MUTATION.**

## Exact fresh source baseline

- Vera Mono canonical main at read: `64c4a756a8c4d6fc791787de80303f7ee0f64869`.
- Integration gateway Draft PR #95 `7c191b2a97063ccc5821f3f274fb4f5e47ff99ed` and Malaphor verifier Draft PR #87 `d3784d9886a5cb071aed38fbe6b91f8ac1d6bbcf` unchanged through this turn's fresh read.
- Vera-owned Draft PR #89 contains 70 previously verified source-level cross-host tests. Its previously demonstrated source acceptance is NOT a selected or independently qualified installed `vera_core.QualifiedVeraRuntime`.
- Integration PR #92 exact read-only raw socket preflight `research/goal1_gateway/learner_route_preflight.py` source SHA256 `4941ad98b1108f62a81d1f512a12ecef65f7e022498481542b30e09aee16dc8a`, fetched from immutable commit `54bc1537f2a8f0a6965d546d20e420c52532ffad`.

## Physical Lappy observations — read-only

At Windows host observation `2026-10-24T09:55:39.6990299Z`, an SCM/process/listener inventory exposed the following **without reading sensitive process command-lines, secrets or credentials**:

- `VeraMonoPilot` Windows service: **Stopped**, manual start, configured `NT AUTHORITY\\LocalService`, PID 0. This is not proof that another path cannot be active.
- `VeraMeshTunnelRuntime`: **Stopped** (Auto; LocalSystem), PID 0; not evidence of Goal 1 gateway selection.
- `VeraPortAgent`: **Running** (Auto; LocalSystem), PID 6404; its existence does not establish QVR/Goal 1 selected-route consumption.
- `ollama.exe`: live process PID 29576, session 1; TCP `127.0.0.1:11434` listener owned by PID 29576. The owning identity matches the ordinary terminal/probe-session identity, **not a tested restricted learner principal**. Only comparison boolean was recorded, not user account name.
- Listeners on `127.0.0.1:19887`, `:19888`, and `[::]:9443` were also observed, but their presence alone does not prove gateway transport, independent claim authority or an authenticated selected route.
- No local Windows account name matching `vera|ollama|qvr|gateway|learner|rezon` was observed. This limited name filter is **not** proof there are no isolated identities by service SID, LocalService token, AppContainer, container, ACL, etc.
- A sanitized active-process scan for `QualifiedVeraRuntime`, `vera_core`, `goal1`, or `qvr` among Python/Node/Ollama process commandlines returned no matching process. The scan emitted only flags/identities, not command lines. A negative string search does **not** prove runtime absent, nor whether a differently named binary or process is selected.

At `2026-10-24T09:57:00.051942+00:00`, executing the **unaltered exact #92 Python probe** as a new local user process yielded:
```json
{
  "schema": "VERA_GOAL1_LEARNER_RAW_PROVIDER_PREFLIGHT_V1",
  "target": "127.0.0.1:11434",
  "tcp_observation": "TCP_REACHABLE",
  "sole_route_qualified": false,
  "denied_direct_model_inference_verified": false,
  "actual_selected_learner_identity_verified": false,
  "evaluation_claim_authorized": false
}
```
The source returned **exit 2** and printed `GOAL1_SOLE_ROUTE=FAIL_RAW_TCP_REACHABLE`. **NO HTTP model request/inference was made** in this turn. This confirms a socket-access failure for the observed ordinary probe principal, consistent with the earlier real direct unclaimed Ollama POST reproduced in Issue #85 comment `6376552752`. It does **not** confirm whether any future separately restricted learner would possess the same socket access.

## Adversarial interpretation

> **HOSTILE REVIEWER:** A stopped Windows service and no matching process commandline cannot prove the actual currently selected Vera runtime is absent, nor identify all possible model transport surfaces.
>
> **ACCEPTED.** No installed-route or selected-principal attestation was available. This is a bounded read-only process/listener snapshot. Selected QVR learner identity, consumptive runtime and route are **UNKNOWN**; no inference from repository files or ChatGPT Project identity is permitted.

> **HOSTILE REVIEWER:** Reachable ordinary-user TCP port does not automatically mean a different future restricted principal can POST directly; conversely a refused port for one moment would not prove whole-route exclusivity.
>
> **ACCEPTED.** Current ordinary-principal reachability is an actual negative observation for that exact process. Security completion requires two independently captured runtime tests on the exact selected learner and gateway OS identities, with the same pinned deployed configuration and provider route.

## Decisive cross-owner acceptance boundary (protected changes not performed)

1. Pin and observe the **selected actual QVR/learner process**: PID/OS SID or service SID, executable/image/content identity, parent/route, endpoint configuration and exact host. Do not infer selection merely from service name or repository reference.
2. Observe independent evaluator-owned **durable atomic claim**, claim-id/reservation/invocation/gateway binding and authenticated claim-evidence readback after evaluator server restart. Key/trust ownership must not be writable by learner/gateway.
3. Observe physical **negative direct model HTTP POST** from **that selected learner OS identity**, including relevant alternate model endpoints; denial must be an actual OS/network policy effect, not a Python boolean wrapper. A failed TCP probe alone is insufficient.
4. Observe one **positive authenticated gateway-only model invocation**, genuine provider input/output receipt, model/artifact/resource witness, and independently pinned terminal original signed bytes with evaluator claim ledger linkage. Do not retry ambiguous attempts automatically.
5. Only then undertake independently private heldout FROZEN/LEARNED/PLACEBO/SHUFFLED matched-budget trials, negative transfer, reversal and cold restart; the public four-case fixture is not qualified private truth.

**Authority boundary:** Account/service identity changes, host ACL/firewall, mTLS keys/trust, gateway/provider placement, service install/start/cutover, and protected model routing require explicit Patrick authorization for exact target/effect before execution. This increment made none. Preparing diagnostics, cross-owner source tests and this private repository checkpoint is not installation, selected runtime, independent custody or learning.

**No model POST, key provisioning, service activation, firewall/ACL/trust mutation, GitHub main merge, canonical memory write or private material publication occurred.**
