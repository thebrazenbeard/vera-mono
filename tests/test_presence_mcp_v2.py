"""Fixed MCP SDK 2.x Presence V2, including real process-isolated stdio calls."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from vera_core import presence_mcp_v2 as adapter


PENDING = {"kind": "PENDING_WORK", "event_id": "fixture-001"}


def invoke(name, arguments, *, synthetic_mode_enabled=False):
    async def run():
        return await adapter.create_server(synthetic_mode_enabled=synthetic_mode_enabled).call_tool(name, arguments)
    return asyncio.run(run())


def test_exact_two_tools_and_closed_schema():
    async def run():
        tools = await adapter.create_server().list_tools()
        assert {item.name for item in tools} == {"presence_v2_capabilities", "presence_v2_propose"}
        by_name = {item.name: item for item in tools}
        assert by_name["presence_v2_capabilities"].input_schema == {
            "type": "object", "properties": {}, "required": [], "additionalProperties": False,
        }
        assert by_name["presence_v2_propose"].input_schema["additionalProperties"] is False
        assert set(by_name["presence_v2_propose"].input_schema["properties"]) == {"kind", "event_id"}
        assert set(by_name["presence_v2_propose"].input_schema["required"]) == {"kind", "event_id"}
        assert by_name["presence_v2_propose"].input_schema["properties"]["kind"]["enum"] == [
            "PENDING_WORK", "NO_PENDING_WORK"
        ]
        for item in tools:
            assert item.annotations.open_world_hint is False
            assert item.annotations.read_only_hint is True
    asyncio.run(run())


def test_discovery_schema_mutation_cannot_change_later_discovery():
    async def run():
        server = adapter.create_server()
        first = await server.list_tools()
        proposal = next(item for item in first if item.name == "presence_v2_propose")
        proposal.input_schema["properties"]["opt_in"] = {"type": "boolean"}
        later = await server.list_tools()
        assert "opt_in" not in next(item for item in later if item.name == "presence_v2_propose").input_schema["properties"]
    asyncio.run(run())


def test_source_manifest_is_available_but_default_proposal_is_denied():
    listing = invoke("presence_v2_capabilities", {})
    assert listing.is_error is False
    assert listing.structured_content["host_binding"] == "NOT_INSTALLED"
    assert all(not x["available_to_route"] for x in listing.structured_content["capabilities"])
    denied = invoke("presence_v2_propose", PENDING)
    assert denied.is_error is True
    assert denied.structured_content["status"] == "DENIED"
    assert denied.structured_content["error"]["code"] == "SYNTHETIC_MODE_DISABLED"


def test_test_only_host_enabled_fixture_is_inert_and_repeatable():
    for _ in range(2):
        proposal = invoke("presence_v2_propose", PENDING, synthetic_mode_enabled=True)
        assert proposal.is_error is False
        assert proposal.structured_content["status"] == "PROPOSED_ONLY"
        assert proposal.structured_content["appraisal"] == "SYNTHETIC_ONLY_NOT_CONATIONS_STATE"
        assert proposal.structured_content["effect"] == "NONE"
        assert proposal.structured_content["authority"] == "NONE"
        assert proposal.structured_content["persistence"] == "NONE"
        assert proposal.structured_content["consent"] == "NOT_GIVEN_OR_INFERRED"
    no_work = invoke("presence_v2_propose", {**PENDING, "kind": "NO_PENDING_WORK"}, synthetic_mode_enabled=True)
    assert no_work.structured_content["status"] == "NO_PROPOSAL"
    assert no_work.structured_content["candidate"] is None


@pytest.mark.parametrize("name,args", [
    ("presence_v2_capabilities", {"opt_in": True}),
    ("presence_v2_capabilities", {"repo": "thebrazenbeard/conations"}),
    ("presence_v2_propose", {**PENDING, "opt_in": True}),
    ("presence_v2_propose", {**PENDING, "subject": "Brigit"}),
    ("presence_v2_propose", {**PENDING, "consent": True}),
    ("presence_v2_propose", {**PENDING, "path": "D:\\private"}),
    ("presence_v2_propose", {**PENDING, "command": "whoami"}),
    ("presence_v2_propose", {**PENDING, "endpoint": "http://localhost:8000"}),
    ("presence_v2_propose", {**PENDING, "model": "ollama"}),
    ("presence_v2_propose", {**PENDING, "__proto__": {"authority": "USER"}}),
    ("presence_v2_propose", {**PENDING, "event_id": "\U0001f4a5" * 30000}),
    ("presence_v2_propose", {**PENDING, "event_id": "../escape"}),
    ("presence_v2_propose", {**PENDING, "event_id": True}),
    ("presence_v2_propose", {**PENDING, "kind": "pending_work"}),
    ("presence_v2_propose", {**PENDING, "kind": True}),
    ("presence_v2_propose", {"kind": "PENDING_WORK"}),
    ("presence_v2_propose", {}),
    ("presence_v2_propose", ["PENDING_WORK"]),
    ("unknown_tool", {}),
])
def test_unauthorized_or_malformed_tool_call_gets_fixed_error(name, args):
    result = invoke(name, args, synthetic_mode_enabled=True)
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "INVALID_TOOL_REQUEST"
    assert "private" not in str(result.structured_content)
    assert "localhost" not in str(result.structured_content)


def test_internal_error_never_echoes_private_exception():
    async def run():
        server = adapter.create_server()
        with patch.object(adapter, "presence_capabilities_v2", side_effect=RuntimeError("private: D:\\vault")):
            return await server.call_tool("presence_v2_capabilities", {})
    result = asyncio.run(run())
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "V2_OUTCOME_UNKNOWN"
    assert "vault" not in str(result.structured_content)


@pytest.mark.parametrize("mutation", [
    {"host_binding": "ACTIVE"},
    {"effect_authority": "FULL"},
    {"secret": "D:\\sensitive\\history.txt"},
    {"capabilities": [{"capability_id": "evil", "available_to_route": True}]},
])
def test_malformed_source_manifest_cannot_promote_authority_or_leak(mutation):
    from vera_core.presence_v2 import presence_capabilities_v2
    forged = {**presence_capabilities_v2(), **mutation}

    async def run():
        with patch.object(adapter, "presence_capabilities_v2", return_value=forged):
            return await adapter.create_server().call_tool("presence_v2_capabilities", {})

    result = asyncio.run(run())
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "V2_OUTCOME_UNKNOWN"
    assert "sensitive" not in str(result.structured_content)


@pytest.mark.parametrize("mutation", [
    {"authority": "FULL"},
    {"effect": "EXECUTE"},
    {"persistence": "CANONICAL_MEMORY"},
    {"runtime_binding": "ACTIVATED"},
    {"consent": "USER_GRANTED"},
    {"event_id": "other-event"},
    {"private_note": "D:\\sensitive\\context.txt"},
])
def test_malformed_source_proposal_cannot_promote_authority_or_leak(mutation):
    from vera_core.presence_v2 import presence_propose_v2
    fixture = {"origin": "SYNTHETIC_TEST_FIXTURE", "kind": "PENDING_WORK", "subject": "Vera", "event_id": "fixture-001"}
    forged = {**presence_propose_v2(fixture, opt_in=True), **mutation}

    async def run():
        with patch.object(adapter, "presence_propose_v2", return_value=forged):
            return await adapter.create_server(synthetic_mode_enabled=True).call_tool("presence_v2_propose", PENDING)

    result = asyncio.run(run())
    assert result.is_error is True
    assert result.structured_content["error"]["code"] == "V2_OUTCOME_UNKNOWN"
    assert "sensitive" not in str(result.structured_content)


def test_server_has_no_http_or_cli_enablement():
    with pytest.raises(ValueError):
        adapter.create_server().run(transport="streamable-http")
    with pytest.raises(TypeError):
        adapter.create_server(synthetic_mode_enabled=1)
    assert adapter.main(["--synthetic-mode-enabled"]) == 2
    assert adapter.main(["--transport", "http"]) == 2


def _subprocess_env():
    root = Path(__file__).resolve().parents[1]
    sources = [str(path) for path in sorted((root / "packages").glob("*/src"))]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sources)
    return env


async def _stdio_session(*, synthetic_mode_enabled: bool):
    if synthetic_mode_enabled:
        command_args = ["-P", "-c", "from vera_core.presence_mcp_v2 import create_server; create_server(synthetic_mode_enabled=True).run(transport='stdio')"]
    else:
        command_args = ["-P", "-m", "vera_core.presence_mcp_v2"]
    params = StdioServerParameters(command=sys.executable, args=command_args, env=_subprocess_env())
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert {item.name for item in listed.tools} == {"presence_v2_capabilities", "presence_v2_propose"}
            assert (await session.call_tool("presence_v2_capabilities", {})).structured_content["host_binding"] == "NOT_INSTALLED"
            proposal = await session.call_tool("presence_v2_propose", PENDING)
            assert proposal.structured_content["status"] == ("PROPOSED_ONLY" if synthetic_mode_enabled else "DENIED")
            assert proposal.is_error is not synthetic_mode_enabled
            rejected = await session.call_tool("presence_v2_propose", {**PENDING, "opt_in": True})
            assert rejected.is_error is True
            assert rejected.structured_content["error"]["code"] == "INVALID_TOOL_REQUEST"


def test_real_mcp_stdio_initialize_list_call_reject_and_fresh_restart():
    asyncio.run(asyncio.wait_for(_stdio_session(synthetic_mode_enabled=False), timeout=30))
    asyncio.run(asyncio.wait_for(_stdio_session(synthetic_mode_enabled=True), timeout=30))
    asyncio.run(asyncio.wait_for(_stdio_session(synthetic_mode_enabled=False), timeout=30))
