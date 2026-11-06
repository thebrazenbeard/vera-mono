# Fixed stdio MCP Presence V2 — isolated transport candidate

This is a **source/build/test candidate**, not a registered ChatGPT MCP, Project tool, deployed service, runtime consumer, Conations owner, or persistence mechanism. The fixed Presence V1 stdio ABI remains unchanged in its separate owner checkout.

## Public surface (MCP SDK 2.x)

Production entrypoint: `python -P -m vera_core.presence_mcp_v2` with no flags. Only `stdio` transport is accepted. There is no socket/HTTP fallback, CLI/env enablement, dynamic import, executable, command, path, URL, model, host, plugin, consent, or repository argument.

| Tool | Exact MCP arguments | Result |
| --- | --- | --- |
| `presence_v2_capabilities` | `{}` | Static inspected-source manifest, provider install/activation/runtime/qualification `UNKNOWN`, router `NOT_INSTALLED`, route unavailable. |
| `presence_v2_propose` | `{ "kind": "PENDING_WORK" \| "NO_PENDING_WORK", "event_id": "bounded-opaque-id" }` | **Production always DENIED**, `SYNTHETIC_MODE_DISABLED`; no client opt-in field exists. |

The Python factory `create_server(synthetic_mode_enabled=True)` exists **only for a host-owned inert test fixture**, callable by tests that launch a separate local process. It is not an authorization, install, runtime admission, or standing desire. In that isolated mode, a fixture proposal has `authority=NONE`, `effect=NONE`, `persistence=NONE`, `runtime_binding=NONE`, and `consent=NOT_GIVEN_OR_INFERRED`. A model-provided `opt_in=true` is always rejected. The production `main()` always uses `False` and rejects all flags.

Both tool schemas have `additionalProperties=false`; dispatch additionally checks exact argument types, keys, fixed signal enumerations, opaque ID constraints, and a 512-byte input budget. JSON tool responses are bounded to 4096 bytes, emit safe fixed error codes, and are verified against exact source-only semantic shapes: no internal drift may promote install/authority/effects, leak extra fields, substitute Brigit, or spoof another event. Stdout is reserved for MCP JSON-RPC.

## Evidence classes and qualification

- `SOURCE_INSPECTED`: pre-active pinned `e306c251a4da44125ee58c311a35120084da8e4b`, Conations **main** pinned `73295039e7a1710c5bb73666e665cef80c40aa5d`; Conations Draft PR #12 is unmerged and unbound.
- `BUILD`: Python package/wheel may include the adapter, but this alone grants no native endpoint.
- `TEST`: SDK2 client initializes, lists exactly two tools, receives read-only capabilities, receives denied production proposal, rejects injected fields, and exercises inert synthetic proposal through a separate test-owned process; repeated sessions test no state carry-over.
- `INSTALL / ACTIVE / RUNTIME_PROBED / BEHAVIOR_QUALIFIED`: **not established**; the manifest never derives these from code, a model, a passing test, or an MCP handshake.

Run with Python 3.12 and MCP SDK 2.x (tested with `mcp==2.3.0`):

```bash
python -m pytest -q tests/test_presence_v2.py tests/test_presence_mcp_v2.py
```

The root `vera-mono` distribution declares an **optional** extra,
`presence-v2-mcp = ["mcp>=2.2,<3"]`, and the fixed console entrypoint
`vera-presence-v2-mcp = vera_core.presence_mcp_v2:main`. These are packaging
dependencies and a local stdio executable, **not native Project registration**.
An isolated installation may request the extra explicitly:

```bash
python -m pip install ".[presence-v2-mcp]"
```

The ordinary base installation remains usable without the MCP extra. The
console script must run only in a separately qualified host environment;
the fixed entrypoint is always default-denied and cannot enable synthetic
proposals by CLI or environment arguments. Qualification of a native route
still requires an exact release-bound owner, provider registration, process
identity, installed-content digest, live invocation and independent effect
evidence. **No native ChatGPT MCP registration is present here.**
