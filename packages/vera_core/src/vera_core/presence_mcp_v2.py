"""Fixed, dormant stdio-only MCP SDK 2.x transport for Presence V2.

No executable, network, path, plugin, consent, model, or configuration routing.
The production ``main`` is permanently synthetic-proposal-disabled. Tests may
construct an in-process, non-effectful fixture server; MCP callers cannot.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .presence_v2 import presence_capabilities_v2, presence_propose_v2


SCHEMA = "vera.presence.v2"
MAX_INPUT_BYTES = 512
MAX_OUTPUT_BYTES = 4096
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_KINDS = frozenset({"PENDING_WORK", "NO_PENDING_WORK"})
_FIELDS = {
    "presence_v2_capabilities": frozenset(),
    "presence_v2_propose": frozenset({"kind", "event_id"}),
}
_SCHEMAS = {
    "presence_v2_capabilities": {
        "type": "object", "properties": {}, "required": [], "additionalProperties": False,
    },
    "presence_v2_propose": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["PENDING_WORK", "NO_PENDING_WORK"]},
            "event_id": {
                "type": "string", "minLength": 1, "maxLength": 64,
                "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$",
            },
        },
        "required": ["kind", "event_id"],
        "additionalProperties": False,
    },
}
_SOURCE_ROWS = (
    ("pre_active_observation", "pre-active", "e306c251a4da44125ee58c311a35120084da8e4b"),
    ("conations_appraisal", "conations", "73295039e7a1710c5bb73666e665cef80c40aa5d"),
)


def _error(code: str, *, status: str = "ERROR") -> dict[str, Any]:
    return {
        "schema": SCHEMA, "status": status,
        "error": {"code": code, "automatic_retry": False},
        "effect": "NONE", "authority": "NONE", "persistence": "NONE",
    }


def _valid_call(name: Any, arguments: Any) -> bool:
    if type(name) is not str or name not in _FIELDS or type(arguments) is not dict:
        return False
    if any(type(key) is not str for key in arguments):
        return False
    if arguments.keys() != _FIELDS[name]:
        return False
    if name == "presence_v2_propose":
        if type(arguments["kind"]) is not str or arguments["kind"] not in _KINDS:
            return False
        event = arguments["event_id"]
        if type(event) is not str or _EVENT_ID.fullmatch(event) is None:
            return False
    try:
        return len(json.dumps(arguments, ensure_ascii=True, allow_nan=False).encode("ascii")) <= MAX_INPUT_BYTES
    except (TypeError, ValueError, UnicodeError):
        return False


def _exact(actual: Any, expected: Any) -> bool:
    """No equal-but-differently-typed claims or unexpected internal fields."""
    if type(actual) is not type(expected):
        return False
    if type(expected) is dict:
        return actual.keys() == expected.keys() and all(
            _exact(actual[key], value) for key, value in expected.items()
        )
    if type(expected) is list:
        return len(actual) == len(expected) and all(
            _exact(value, reference) for value, reference in zip(actual, expected)
        )
    return actual == expected


def _valid_output(name: str, arguments: dict[str, Any], value: Any) -> bool:
    if name == "presence_v2_capabilities":
        expected = {
            "schema": SCHEMA, "host_binding": "NOT_INSTALLED", "effect_authority": "NONE",
            "capabilities": [
                {
                    "capability_id": capability_id,
                    "source_repository_slug": repo,
                    "source_git_commit": commit,
                    "source_status": "SOURCE_INSPECTED",
                    "installed": "UNKNOWN", "active": "UNKNOWN",
                    "runtime_probed": "UNKNOWN", "behavior_qualified": "UNKNOWN",
                    "available_to_route": False, "effect_authority": "NONE",
                }
                for capability_id, repo, commit in _SOURCE_ROWS
            ],
        }
        return _exact(value, expected)
    if name != "presence_v2_propose":
        return False
    if _exact(value, _error("SYNTHETIC_MODE_DISABLED", status="DENIED")):
        return True
    pending = arguments["kind"] == "PENDING_WORK"
    expected = {
        "schema": SCHEMA,
        "status": "PROPOSED_ONLY" if pending else "NO_PROPOSAL",
        "event_id": arguments["event_id"],
        "subject": "Vera",
        "candidate": "REQUEST_HOST_REVIEW_OF_WORK_FRONTIER" if pending else None,
        "appraisal": "SYNTHETIC_ONLY_NOT_CONATIONS_STATE",
        "effect": "NONE", "authority": "NONE", "consent": "NOT_GIVEN_OR_INFERRED",
        "persistence": "NONE", "runtime_binding": "NONE",
    }
    return _exact(value, expected)


def _result(value: dict[str, Any]) -> CallToolResult:
    try:
        if type(value) is not dict or value.get("schema") != SCHEMA:
            raise ValueError("invalid result shape")
        text = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        if len(text.encode("ascii")) > MAX_OUTPUT_BYTES:
            raise ValueError("bounded result exceeded")
    except (TypeError, ValueError, UnicodeError):
        value = _error("V2_OUTCOME_UNKNOWN")
        text = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=value,
        is_error=value.get("status") in {"ERROR", "DENIED"},
    )


class _FixedServer(MCPServer):
    async def list_tools(self):  # type: ignore[override]
        tools = await super().list_tools()
        for tool in tools:
            # Never inherit permissive SDK schema defaults.
            tool.input_schema = deepcopy(_SCHEMAS[tool.name])
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any], context=None):  # type: ignore[override]
        if not _valid_call(name, arguments):
            return _result(_error("INVALID_TOOL_REQUEST"))
        try:
            output = await super().call_tool(name, arguments, context)
            if not isinstance(output, CallToolResult) or type(output.structured_content) is not dict:
                return _result(_error("V2_OUTCOME_UNKNOWN"))
            if not _valid_output(name, arguments, output.structured_content):
                return _result(_error("V2_OUTCOME_UNKNOWN"))
            return _result(output.structured_content)
        except Exception:
            return _result(_error("V2_OUTCOME_UNKNOWN"))

    def run(self, transport: str = "stdio", **kwargs):  # type: ignore[override]
        if transport != "stdio" or kwargs:
            raise ValueError("Presence V2 permits only default local stdio")
        return super().run(transport="stdio")


def create_server(*, synthetic_mode_enabled: bool = False) -> MCPServer:
    """Private factory toggle for deterministic host-owned test fixtures only.

    This is not discoverable as an MCP argument, CLI flag, or environment knob.
    The packaged entrypoint always constructs the denied/default server.
    """
    if type(synthetic_mode_enabled) is not bool:
        raise TypeError("synthetic_mode_enabled must be an exact bool")
    server = _FixedServer("vera-presence-v2-source-only")

    @server.tool(
        name="presence_v2_capabilities",
        description="List fixed inspected source candidates; no host installation or runtime authority.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
        structured_output=True,
    )
    async def presence_v2_capabilities() -> dict[str, Any]:
        return presence_capabilities_v2()

    @server.tool(
        name="presence_v2_propose",
        description="Synthetic-only, no-effect fixture proposal; host test mode is disabled by default.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
        structured_output=True,
    )
    async def presence_v2_propose(kind: str, event_id: str) -> dict[str, Any]:
        if not synthetic_mode_enabled:
            return _error("SYNTHETIC_MODE_DISABLED", status="DENIED")
        return presence_propose_v2(
            {
                "origin": "SYNTHETIC_TEST_FIXTURE", "subject": "Vera",
                "kind": kind, "event_id": event_id,
            },
            opt_in=True,
        )

    return server


def main(argv: list[str] | None = None) -> int:
    # No CLI or environment configuration; main never enables synthetic mode.
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        return 2
    create_server().run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
