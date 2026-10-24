# Goal 1 — physical networkless learner cell, host-only inference broker

Date: 2026-10-24. **Disposition: ACTUAL DISPOSABLE DOCKER NETWORK ISOLATION VERIFIED on Lappy; not selected/installed QVR; independent inference + learning HOLD.**

## Need and current observable baseline

Lappy's ordinary Windows session can connect to `127.0.0.1:11434`, and a previous real direct Ollama request succeeded without a reservation. A Python wrapper that checks authorization cannot stop another local Python process on that same unrestricted host from opening a socket. As of the latest read-only runtime inventory, `VeraMonoPilot` is Stopped/Manual; the selected Goal 1 learner/gateway OS processes are UNKNOWN. Those facts have not been changed by the work here.

Microsoft describes WFP's identity-aware authorization layers and AppContainer network isolation, but **neither was installed here**. Instead, a source-only research candidate uses a *separate Docker networking namespace* to remove the learner's network interfaces. Docker documents that `--network none` creates only the container's loopback device, not host loopback. This avoids relying on a Windows firewall rule silently handling loopback.

References:
- https://docs.docker.com/engine/network/drivers/none/
- https://learn.microsoft.com/en-us/windows/win32/fwp/application-layer-enforcement--ale-
- https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation

## New code, bounded interface

Vera-owned Draft PR #89: `research/goal1_acceptance_bridge/networkless_learner_cell.py`, `tests/research/test_goal1_networkless_learner_cell.py`.

`build_command(image_id)` accepts **only an existing immutable Docker image ID** of the exact `sha256:<64 lowercase hex>` form. Runtime Docker invocation specifies:

- `--pull=never`: never pulls or silently replaces images;
- `--network=none`: no Docker networking beyond container loopback;
- `--read-only`, `--user=65534:65534`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`;
- `--pids-limit=32`, `--memory=128m`, `--cpus=0.5`, `--ipc=private`; Docker's default private PID mode;
- `--rm` disposable container and `-i` controlled stdin/stdout JSON; **no bind mounts, no host Docker socket, no device or GPU access, no ports, no user-provided Docker flags, no environment/credentials forwarding**.

A fixed Python worker receives `{nonce,prompt}` over stdin, probes network interfaces and host Ollama TCP paths from *inside its own namespace*, and emits one JSON `REQUEST_GATEWAY_INFERENCE` over stdout. The untrusted worker is never given an evaluator signing key, client mTLS key, claim ledger, Docker socket or access to host model transport. The parent verifies schema, nonce and prompt digest, insists on the sole loopback interface and no successful raw-model TCP probes, and only then invokes a **host-selected** callback with the original trusted-parent prompt (never a worker-chosen gateway URL or instruction). Any runner failure, missing image, timeout, invalid JSON, extra network interface, reachable model socket, forged nonce/digest or worker `qualified=true` stops before the callback.

The callback **is a research interface**; it has *not yet been wired* to Integration's #95 gateway, Malaphor's evaluator claim authority, real Ollama, independently held keys, or selected QVR. The result explicitly sets `gateway_effect_independently_verified=false`, `actual_selected_qvr_route_verified=false`, `learning_qualified=false`, regardless of what the callback returns. The container worker does not perform learning or make a model inference. It proposes a bounded inference request to be executed **only by a future outside trusted gateway**. This is a candidate transport route, not a runtime-selected substitute for Vera Mono.

## Physical host tests

Lappy Docker Engine version 29.7.2 had cached `python:3.11-slim` image with immutable image ID `sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534`. No image pull.

First standalone Docker network-none experiment, non-root/read-only/capdrop: *actual container execution* exit0, `interfaces=["lo"]`, TCP to `127.0.0.1:11434` inside cell DENIED_OR_UNAVAILABLE; TCP to Docker gateway `172.17.0.1:11434` DENIED_OR_UNAVAILABLE. No model HTTP call.

**RED→FIX:** The first launcher unit tests passed 8/8 on both hosts, but the first real Docker invocation failed closed with Docker exit125: invalid `--pid=private` option. Docker defaults to private PID namespace; removing that invalid flag (without enabling `--pid=host`) made the actual non-root/read-only/network-none worker work. The project unit tests now check for no shared PID option. The next actual Lappy `run_networkless_learner_step` completed successfully: one fixed worker request, **one** host callback returning `{"status":"NO_REAL_MODEL_CALLED"}`, `isolation_observed=true`, `actual_selected_qvr_route_verified=false`, `gateway_effect_independently_verified=false`, `learning_qualified=false`. No persistent container, model provider effect, credential or host configuration change.

- Lappy Windows focused networkless policy tests **8/8 PASS**, physical Docker + host broker test exit 0.
- VN2 Linux focused source policy tests **8/8 PASS**. VN2 has no Docker daemon in this test context; do not infer a physical VN2 container isolation outcome.
- Full staged source tests Lappy Windows **78/78 PASS** and `py_compile` PASS.
- Full staged source tests VN2 Linux **78/78 PASS** and `py_compile` PASS. These include 70 previously verified Goal 1 source tests plus 8 new policy tests, not installed runtime or independent reviewer qualification.

## Hostile review — accepted

> **The original unrestricted Windows user can still reach Ollama.** Accepted. This deliberately does not alter that user's privileges, Ollama's bind address or firewall. The isolation applies **only to processes actually launched in the new networkless container**. Selecting the learner QVR route is not observed and remains a protected deployment effect.

> **A host Docker administrator can change network attachments after container start, and a compromised Docker engine defeats the boundary.** Accepted. The Docker engine and host-side broker must reside in a separately controlled trust domain; no daemon socket or host bind mount can be exposed to the learner. A further production gate needs independent host-side container ID/inspection and runtime policy attestation, plus denial of alternate raw provider access on exact selected learner principal.

> **A gateway callback could bypass evaluator reservations.** Accepted. The research callback does not itself grant authority. Integration #95 must own and verify the authenticated evaluator-owned atomic claim before a genuine model dispatch; Malaphor must independently verify remote durable claim and signed terminal against externally pinned trust roots, honest unknown/recovery, and hidden private truth.

> **Networkless container Python is not the actual self-learning QVR.** Accepted. Worker here only tests model-inference request handoff. Source adapter must be integrated with `vera_core.QualifiedVeraRuntime` by its owner and selected/deployed after exact authorization, then real negative learner HTTP bypass and positive gateway-model POST must be observed.

## Concrete cutover contract, NOT EXECUTED

1. Integration freezes exact learner binary/image/UID and gateway/claim source heads; establish an externally pinned Docker image ID, broker identity, and remote evaluator/trust anchors. No learner access to Docker engine, host filesystem, mTLS keys, model provider address or private challenge truth.
2. Owner binds actual selected Goal 1 learner inference requests to the sandbox's stdin/stdout gateway request exchange; **only the outside gateway** may dispatch, after an independently authenticated evaluator-ledger claim. The gateway and evaluator remain separate independently controlled processes/credentials.
3. Owner adds host Docker inspection and physical selected-PID/namespace observations, tries learner direct HTTP POST to actual model, tests alternate provider hostnames/interfaces, cold-restarts learner and evaluator, rejects lost-reply duplicate dispatch, and captures independently verified signed terminal/usage.
4. Only after those tests pass may the selected route be described as **sole route**. Then separate fresh custodian-private heldout matched FROZEN/LEARNED/PLACEBO/SHUFFLED evaluations can begin.
5. Rollback must restore the prior selected route **without** silently weakening evidence or marking any in-flight unknown invocation safe to retry.

**Protected effect boundary:** No current authorization in this task identifies a specific production service/identity cutover, gateway credential/trust provisioning, firewall/ACL changes, model-provider relocation or merge. These require Patrick's explicit approval for those exact targets/effects. This work committed source and tests only and ran automatically removed temporary test containers.

No selected QVR route, model HTTP POST, Ollama service modification, live mTLS key provisioning, trust/ACL/firewall policy mutation, merge, deployment, canonical memory write, private truth publication or causal learning claim was made.
