"""Offline regression coverage for the normal stdio entrypoint, on both wires."""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.metadata import build_tool_meta
from hf_mcp.registry import get_tool_spec
from hf_mcp.schemas import build_tool_output_schema, build_tool_schema

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"

# No config file, live token store, credentials or network client is consulted.
SERVER = '''
from hf_mcp.config import HFMCPSettings
from hf_mcp.dispatcher import RuntimeBundle
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport
import hf_mcp.server as server

class OfflineTokens:
    def require_bundle(self):
        return TokenBundle(access_token="offline", token_type="Bearer", scope=frozenset({"read"}))

calls = []
def offline_post(route, payload, headers):
    calls.append(payload["asks"])
    assert route == "/read", route
    assert headers["Authorization"] == "Bearer offline"
    asks = payload["asks"]
    root = next(iter(asks))
    assert root in {"forums", "threads", "posts"}
    assert 1 <= asks[root]["_page"]
    assert 1 <= asks[root]["_perpage"] <= 30
    assert type(asks[root]["_page"]) is int
    assert type(asks[root]["_perpage"]) is int
    return {
        root: [{"fid": 123, "tid": 456, "pid": 789, "subject": "Offline fixture"}],
        "offline_calls": len(calls),
        "offline_page": asks[root]["_page"],
        "offline_per_page": asks[root]["_perpage"],
    }

transport = HFTransport(token_store=OfflineTokens(), base_url="https://example.invalid")
transport._post_json = offline_post
settings = HFMCPSettings(
    profile="custom",
    enabled_capabilities=frozenset({"forums.index", "forums.read", "threads.read", "posts.read"}),
    enabled_parameter_families=frozenset({"selectors.forum", "selectors.thread", "selectors.post", "filters.pagination", "fields.posts.body"}),
)
server.resolve_runtime_bundle = lambda _: RuntimeBundle(transport=transport, settings=settings)
server.serve_stdio(settings)
'''


@pytest.mark.core
@pytest.mark.parametrize("modern", [False, True], ids=["legacy", "modern"])
def test_normal_stdio_read_surface_and_pagination_on_actual_wire(modern: bool) -> None:
    env = {"PATH": os.defpath, "PYTHONPATH": str(SRC_PATH), "PYTHONUNBUFFERED": "1"}
    policy = CapabilityPolicy(
        HFMCPSettings(
            profile="custom",
            enabled_capabilities=frozenset({"forums.index", "forums.read", "threads.read", "posts.read"}),
            enabled_parameter_families=frozenset(
                {
                    "selectors.forum",
                    "selectors.thread",
                    "selectors.post",
                    "filters.pagination",
                    "fields.posts.body",
                }
            ),
        )
    )
    with subprocess.Popen(
        [sys.executable, "-c", SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=PRODUCT_ROOT,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        sequence = 0

        def send(method: str, params: dict, *, notification: bool = False) -> dict:
            nonlocal sequence
            sequence += 1
            if modern:
                params = {**params, "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                }}
            message = {"jsonrpc": "2.0", "method": method, "params": params}
            if not notification:
                message["id"] = sequence
            process.stdin.write((json.dumps(message) + "\n").encode())
            process.stdin.flush()
            if notification:
                return {}
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=10), "stdio response timed out"
                line = process.stdout.readline()
            assert line, f"stdio server exited ({process.poll()})"
            response = json.loads(line)
            assert response["id"] == sequence
            assert "error" not in response, response
            return response["result"]

        try:
            if not modern:
                initialized = send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "offline-test", "version": "1"}})
                assert initialized["protocolVersion"] == "2025-11-25"
                send("notifications/initialized", {}, notification=True)

            tools = {tool["name"]: tool for tool in send("tools/list", {})["tools"]}
            assert set(tools) == {"forums_index", "forums_read", "threads_read", "posts_read"}
            for name, tool in tools.items():
                assert tool["annotations"]["readOnlyHint"] is True
                assert tool["annotations"]["destructiveHint"] is False
                spec = get_tool_spec(name.replace("_", "."))
                expected_input_schema = build_tool_schema(spec, policy)
                if "title" not in expected_input_schema:
                    expected_input_schema["title"] = tool["inputSchema"]["title"]
                for key, value in tuple(expected_input_schema.items()):
                    if key.startswith("x-hf-") and value is None and key not in tool["inputSchema"]:
                        expected_input_schema.pop(key)
                assert tool["inputSchema"] == expected_input_schema
                expected_meta = build_tool_meta(spec)
                assert set(tool["_meta"]) <= set(expected_meta)
                for key, value in expected_meta.items():
                    # SDK wire models may omit null extension values. The local
                    # catalog has no upstream helper; every populated value survives.
                    assert tool["_meta"].get(key) == value
                assert "_meta" not in tool["annotations"]
                expected_output_schema = build_tool_output_schema(spec)
                if "title" in tool["outputSchema"] and "title" not in expected_output_schema:
                    assert tool["outputSchema"]["title"] == "_StructuredOutput"
                    expected_output_schema["title"] = "_StructuredOutput"
                for key, value in tuple(expected_output_schema.items()):
                    if key.startswith("x-hf-") and value is None and key not in tool["outputSchema"]:
                        expected_output_schema.pop(key)
                assert tool["outputSchema"] == expected_output_schema
                if name != "forums_index":
                    properties = tool["inputSchema"]["properties"]
                    assert properties["page"]["minimum"] == 1
                    assert properties["per_page"]["minimum"] == 1
                    assert properties["per_page"]["maximum"] == 30

            titles = [tool["inputSchema"]["title"] for tool in tools.values()]
            assert len(set(titles)) == len(titles)

            catalog = send("tools/call", {"name": "forums_index", "arguments": {}})
            assert "structuredContent" in catalog
            assert not catalog.get("isError", False)
            calls = 0
            for name, selector in (("forums_read", {"fid": 123}), ("threads_read", {"fid": 123}), ("posts_read", {"tid": 456})):
                minimal = send("tools/call", {"name": name, "arguments": selector})
                calls += 1
                assert not minimal.get("isError", False), minimal
                assert minimal["structuredContent"]["offline_calls"] == str(calls)
                assert minimal["structuredContent"]["offline_page"] == "1"
                assert minimal["structuredContent"]["offline_per_page"] == "30"

                invalid_arguments = [
                    {**selector, "page": page, "per_page": per_page}
                    for page, per_page in ((0, 1), (-1, 1), (1, 0), (1, -1), (1, 31))
                ]
                invalid_arguments.extend(
                    [
                        {**selector, "page": "1"},
                        {**selector, "page": 1.5},
                        {**selector, "page": True},
                        {**selector, "per_page": "30"},
                        {**selector, "output_mode": "invalid"},
                        {**selector, "include_raw_payload": "true"},
                        {**selector, "unexpected": "must-not-be-dropped"},
                        {},
                    ]
                )
                if "fid" in selector:
                    invalid_arguments.append({"fid": "123"})
                for arguments in invalid_arguments:
                    invalid = send("tools/call", {"name": name, "arguments": arguments})
                    assert invalid["isError"] is True
                    if "unexpected" in arguments:
                        serialized_error = json.dumps(invalid)
                        assert "additionalProperties" in serialized_error
                        assert "$" in serialized_error
                        assert "must-not-be-dropped" not in serialized_error
                for page, per_page in ((1, 1), (2, 30)):
                    result = send("tools/call", {"name": name, "arguments": {**selector, "page": page, "per_page": per_page, "output_mode": "raw", "include_raw_payload": True}})
                    calls += 1
                    assert not result.get("isError", False), result
                    assert result["structuredContent"]["offline_calls"] == str(calls)
                    assert result["structuredContent"]["_hf_flow"]["version"] == 1
                    assert any(part["type"] == "resource" for part in result["content"])
                    assert ("resultType" in result) is modern
            denied = send("tools/call", {"name": "posts_reply", "arguments": {}})
            assert denied["isError"] is True
        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
