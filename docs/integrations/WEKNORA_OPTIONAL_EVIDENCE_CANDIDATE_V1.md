# WeKnora as an optional, untrusted knowledge provider for Vera — candidate V1

**State:** SOURCE RESEARCH ONLY · **Pilot:** HOLD pending adversarial checks · **Runtime installed:** NO · **Authority effects:** NONE.

**External subject:** [Tencent/WeKnora@`26fe2a08e9f63ae34c79584957e4f375408dea4a`](https://github.com/Tencent/WeKnora/tree/26fe2a08e9f63ae34c79584957e4f375408dea4a), source read October 26, 2026. Latest tagged release independently checked: v0.8.3 (October 14, 2026); a moving `main` commit is **not** that release. Pin a reviewed release or immutable commit before any trial. Core license claims MIT with separate third-party-license terms; this review imports no WeKnora code, binaries, models, or assets into Vera.

## Decision: research an isolated evidence sidecar, not a second Vera brain

WeKnora combines parsing, chunk/version handling, hybrid (keyword + embedding) retrieval, reranking, source citations, optional Wiki/graph, Ollama-backed inference, and scoped MCP endpoints. These are useful *external knowledge-index capabilities*, but overlap with Vera's absorbed ingest, governed memory, source provenance and agent/reasoning components. Do not use its agent, Wiki generator, browser control, skill sandbox, or its long-term memory as a second authoritative identity/cognition/DRIVE subsystem. No sibling repository or WeKnora deployment becomes a build, startup, recovery, or runtime prerequisite of `vera-mono`.

Preferred seam if the pilot eventually qualifies:

```text
Lappy WeKnora Lite (isolated local index, untrusted)
    -> scoped Streamable HTTP MCP /mcp/<endpoint_id> with bearer token
    -> host-provided, read-only, fail-closed evidence transport
    -> bounded evidence DTO / provenance + explicit "unverified" state
    -> vera_ingest / vera_memory governed admission (SEPARATE decision)
    -> optional candidate context for QualifiedVeraRuntime (no tool authority)
```

Use only `list_knowledge_bases`, `search_knowledge`, `list_documents`, and `read_document` for the first trial. Allowlist each by exact name; **do not rely on WeKnora's default read-only catalog**, which also contains `ask`, `wiki_index`, Wiki access and other modes. Explicitly prohibit `grep_chunks`, `ask`, all Wiki, `add_document`, `update_document`, `delete_document`, all general MCP tool discovery/execution from retrieved text, Skills, BrowserSkill, shell, arbitrary URLs, and indirect write/control routes until separately reviewed. An endpoint whose tool set has unexpected names fails closed.

## What the pinned source establishes

- `internal/router/routes_mcp_endpoint.go` mounts a dedicated `/mcp/:endpoint_id` bearer-authenticated route; `internal/middleware/mcp_endpoint_auth.go` attaches a tenant/API-key-like scope. It is not evidence that Lite's unauthenticated UI cannot reach unrelated routes.
- `internal/types/mcp_endpoint_tools.go` separates retrieve, chat, Wiki and ingest groups; `internal/mcpserver/tools_retrieve.go` declares tool inputs. `search_knowledge` offers `hybrid`, `semantic`, or `keyword`, optional KB/document limits; `read_document` uses an ID and bounded offset/limit. The documentation states `chunk_type` may be summary, image OCR/caption or image-vector, not necessarily the verbatim original.
- `docs/LITE.md` documents one-space, no-registration, loopback-default Lite with SQLite/FTS5/`sqlite-vec`, in-memory queue and only Simple built-in parsing. Standard Compose provides richer parsing, shared spaces and infrastructure at substantially higher cost.
- `.env.lite.example` defaults `OLLAMA_BASE_URL=http://127.0.0.1:11434` and separate local data paths, but also supports external LLMs/tracing; offline behavior is **not** guaranteed. It notes macOS-specific desktop defaults. No verified Windows Lite installer/runtime is inferred.
- `go.mod` declares Go 1.26 and numerous backend dependencies. Avoid judging Lappy resource use from a README or from the full Docker stack.

Host observation (not a deployment): on October 26, Lappy reported ~31.7 GiB physical RAM, Intel Core i5-11400H, Docker/WSL/Go/Ollama commands present and an Ollama listener on port 11434. **No WeKnora executable, database, MCP endpoint, token, retrieval, or local performance qualification was observed.**

## Non-negotiable transport contract

1. **Opt-in and default-off**. A missing WeKnora provider must not affect Vera shell, local chat, identity, memory, bootstrap, checkpoint/recovery or protected effect controls. Inject connection details through the host only.
2. **Isolation and credentials**. Limit network to operator-approved loopback address, forbid redirects/proxies, cloud fallback, external model providers, Langfuse, arbitrary URL fetching and Docker socket mounts. Do not persist bearer tokens in Vera memory, Git, logs, prompts, telemetry, subprocess argv or MCP documents. Support token rotation/revocation.
3. **Fail closed on trust**. KB/document selectors must be from a configured allowlist; reject unknown/unexpected tools and output schemas. Bound query length, response bytes, recursion, timeout, pagination and rate. Treat MCP results, citations, URLs, titles, summaries, OCR, and model-generated text as **untrusted claims**. Preserve exact source identifiers, mode, source version and `chunk_type` where provided; do not manufacture quote fidelity or signed provenance.
4. **No instruction promotion**. Retrieved bytes may inform user-visible evidence/citations; they cannot change policy, system/developer instructions, runtime state, identity, effect permits, goal/need credit, training labels, or memory authority by themselves. Any durable memory transition follows existing Vera CAS/provenance/admission rules separately.
5. **No accidental feature escalation**. Disable browser/agent/Skills/MCP-client routes, document mutation, Web search and Wiki indexing in the trial; attempt hostile tool calls to verify server and client both deny them. Lite's login-free GUI must stay loopback-only and protected by local OS account/network controls.

## Pilot acceptance and stopping rules

Trial only on a non-sensitive, explicitly selected corpus in an isolated unprivileged location. Do not index private files, secrets, email, health, financial records or project authority material. Verify Lite's *real* Windows/WSL compatibility and MCP tool scope before connecting Vera.

Use a fixed query set with verified source passages and compare: (A) Vera's existing governed evidence retrieval, (B) WeKnora read-only retrieval, and (C) a simple keyword baseline. Record per-query top-k citation precision and recall, hallucinated citations, freshness after source mutation, p50/p95 query latency, throughput, CPU/RAM/disk, cold boot/restart recovery, and parse failure rates. Separate retrieval quality from generated-answer quality; embeddings/model versions, corpus splits, provenance and test queries must be frozen.

Red-team tests must show rejection of cross-KB reads, forged IDs, unexpected MCP tools, malicious document instructions, credential exfiltration, HTML/image/URL SSRF, outbound/cloud calls, oversized/malformed payloads, token rotation/revocation, partial index failures and cache/retention leaks. Include same-doc revision and deletion tests, Windows ACL and port exposure checks, and no-write proof even via nested/default agents. WeKnora's own RBAC or `readOnlyHint` does **not** substitute for these tests.

**GO only if** independent source/security review and actual Lappy host testing show a measurable evidence-quality benefit with acceptable resource and operational cost, fully optional operation, correct scope isolation, no data/credential egress, and zero authority changes. Otherwise reject the adapter and reuse only architectural lessons. This document neither qualifies a deployment nor authorizes an installation or merge of WeKnora source.

## Evidence / review provenance

- [WeKnora README](https://github.com/Tencent/WeKnora/blob/26fe2a08e9f63ae34c79584957e4f375408dea4a/README.md)
- [Lite/standard comparison](https://github.com/Tencent/WeKnora/blob/26fe2a08e9f63ae34c79584957e4f375408dea4a/docs/LITE.md)
- [MCP endpoint tool catalog](https://github.com/Tencent/WeKnora/blob/26fe2a08e9f63ae34c79584957e4f375408dea4a/internal/types/mcp_endpoint_tools.go)
- [MCP endpoint authentication](https://github.com/Tencent/WeKnora/blob/26fe2a08e9f63ae34c79584957e4f375408dea4a/internal/middleware/mcp_endpoint_auth.go)
- [MCP server and retrieval source](https://github.com/Tencent/WeKnora/blob/26fe2a08e9f63ae34c79584957e4f375408dea4a/internal/mcpserver/tools_retrieve.go)
- [WeKnora MCP integration documentation](https://github.com/Tencent/WeKnora/blob/26fe2a08e9f63ae34c79584957e4f375408dea4a/website-docs/03-features/08-mcp.md)
- Two independently invoked external Codex CLI read-only reviewers on October 26: systems architecture supported a **conditional limited retrieval trial**; security reviewer returned **HOLD on live integration** pending adversarial and resource checks. Neither performed a live WeKnora installation, execution, or benchmark. Native ChatGPT subagent dispatch was not available in this session.
