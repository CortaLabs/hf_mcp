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


def _child_pythonpath() -> str:
    source_path = SRC_PATH.resolve()
    overlays = []
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry)
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        candidate = candidate.resolve()
        if candidate == source_path:
            continue
        required_packages = (
            candidate / "jsonschema" / "__init__.py",
            candidate / "referencing" / "__init__.py",
            candidate / "jsonschema_specifications" / "__init__.py",
        )
        if all(package_file.is_file() for package_file in required_packages):
            overlays.append(str(candidate))
    return os.pathsep.join([str(source_path), *overlays])


def _schema_dependency_facts() -> dict[str, dict[str, str]]:
    from importlib.metadata import version

    import jsonschema
    import jsonschema_specifications
    import referencing

    modules = {
        "jsonschema": jsonschema,
        "referencing": referencing,
        "jsonschema-specifications": jsonschema_specifications,
    }
    return {
        name: {
            "version": version(name),
            "origin": str(Path(module.__file__).resolve()),
        }
        for name, module in modules.items()
    }


def _assert_no_nested_hf_envelope_text(content: list[dict[str, object]]) -> None:
    for item in content:
        if item.get("type") != "text" or not isinstance(item.get("text"), str):
            continue
        try:
            parsed = json.loads(item["text"])
        except json.JSONDecodeError:
            continue
        assert not (
            isinstance(parsed, dict)
            and isinstance(parsed.get("content"), list)
            and isinstance(parsed.get("structuredContent"), dict)
        ), "nested HF result envelope found in text content"

# No config file, live token store, credentials or network client is consulted.
SERVER = '''
import json
import socket

network_attempts = []
real_socket = socket.socket
class OfflineSocket(real_socket):
    def connect(self, *args, **kwargs):
        network_attempts.append("connect")
        raise AssertionError("network disabled in stdio child")
    def connect_ex(self, *args, **kwargs):
        network_attempts.append("connect_ex")
        raise AssertionError("network disabled in stdio child")
socket.socket = OfflineSocket
def deny_connection(*args, **kwargs):
    network_attempts.append("create_connection")
    raise AssertionError("network disabled in stdio child")
socket.create_connection = deny_connection

from hf_mcp.config import HFMCPSettings
from hf_mcp.dispatcher import RuntimeBundle
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport
import hf_mcp.server as server
from importlib.metadata import version
from pathlib import Path
import jsonschema
import jsonschema_specifications
import referencing

dependency_modules = {
    "jsonschema": jsonschema,
    "referencing": referencing,
    "jsonschema-specifications": jsonschema_specifications,
}
dependency_facts = {
    name: {"version": version(name), "origin": str(Path(module.__file__).resolve())}
    for name, module in dependency_modules.items()
}

class OfflineTokens:
    calls = []
    def require_bundle(self):
        self.calls.append(True)
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
        "offline_token_reads": len(OfflineTokens.calls),
        "offline_network_attempts": len(network_attempts),
        "offline_dependency_facts_json": json.dumps(dependency_facts),
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

WIRE_PROBE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "wire_probe",
    "type": "object",
    "$defs": {"choice": {"type": "string", "enum": ["allowed", "blocked"]}},
    "properties": {
        "selector_a": {"type": "string", "default": "A"},
        "selector_b": {"type": "string", "default": "B"},
        "count": {"type": "integer"},
        "confirmed": {"type": "boolean", "const": True},
        "choice": {"$ref": "#/$defs/choice"},
        "flag": {"type": "boolean"},
        "mode": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"code": {"type": "string", "pattern": "^[a-z]+$"}},
                "required": ["code"],
                "additionalProperties": False,
            },
        },
        "details": {
            "type": "object",
            "properties": {"label": {"type": "string", "minLength": 1}},
            "required": ["label"],
            "additionalProperties": False,
        },
        "numbers": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        "nullable": {"type": ["string", "null"]},
        "text": {"type": "string", "minLength": 1},
        "timestamp": {"type": "string", "format": "date-time"},
        "defaulted": {"type": "array", "items": {"type": "string"}, "default": ["safe"]},
    },
    "required": ["count", "confirmed", "flag", "items", "details", "numbers", "text"],
    "additionalProperties": False,
    "anyOf": [{"required": ["selector_a"]}, {"required": ["selector_b"]}],
    "oneOf": [
        {"required": ["flag"]},
        {"required": ["flag", "mode"], "properties": {"mode": {"const": "x"}}},
    ],
    "allOf": [{"properties": {"count": {"minimum": 1, "maximum": 3}}}],
    "not": {"properties": {"choice": {"const": "blocked"}}, "required": ["choice"]},
    "x-hf-reference-example": {"$ref": "https://example.invalid/annotation-only"},
}

WRITE_SERVER_TEMPLATE = '''
import json
import socket
import urllib.request

network_attempts = []
real_socket = socket.socket
class OfflineSocket(real_socket):
    def connect(self, *args, **kwargs):
        network_attempts.append("connect")
        raise AssertionError("network disabled in stdio child")
    def connect_ex(self, *args, **kwargs):
        network_attempts.append("connect_ex")
        raise AssertionError("network disabled in stdio child")
socket.socket = OfflineSocket
def deny_network(*args, **kwargs):
    network_attempts.append("create_connection")
    raise AssertionError("network disabled in stdio child")
socket.create_connection = deny_network
urllib.request.urlopen = deny_network

from importlib.metadata import version
from pathlib import Path
import jsonschema
import jsonschema_specifications
import referencing
dependency_modules = {
    "jsonschema": jsonschema,
    "referencing": referencing,
    "jsonschema-specifications": jsonschema_specifications,
}
dependency_facts = {
    name: {"version": version(name), "origin": str(Path(module.__file__).resolve())}
    for name, module in dependency_modules.items()
}

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.registry import get_tool_spec, mcp_tool_name
from hf_mcp.schemas import build_tool_output_schema, build_tool_schema
import hf_mcp.server as server_module
import hf_mcp.dispatcher as dispatcher_module
import hf_mcp.formatting_engine as formatting_engine
import hf_mcp.tools.drafts as drafts_module
import hf_mcp.transport as transport_module
from hf_mcp.server import _MCPServerToolAdapter
from mcp.server.mcpserver import MCPServer

probe_schema = json.loads(PROBE_SCHEMA_JSON)
capabilities = {"bytes.deposit", "bytes.withdraw", "posts.reply", "drafts.delete", "drafts.update"}
families = {"confirm.live", "writes.bytes", "selectors.thread", "writes.content", "drafts.selector", "drafts.confirm_delete", "drafts.metadata"}
policy = CapabilityPolicy(HFMCPSettings(
    profile="custom",
    enabled_capabilities=frozenset(capabilities),
    enabled_parameter_families=frozenset(families),
))
app = MCPServer(name="hf-mcp-offline-write-probe")
adapter = _MCPServerToolAdapter(app)
effects = {"handlers": {}, "transport_calls": 0, "draft_writes": 0, "config_loads": 0, "token_loads": 0}

def _deny_effect(counter_name):
    def deny(*args, **kwargs):
        effects[counter_name] += 1
        raise AssertionError(f"forbidden child effect: {counter_name}")
    return deny

server_module.load_settings = _deny_effect("config_loads")
server_module.resolve_runtime_bundle = _deny_effect("config_loads")
dispatcher_module.load_token_store = _deny_effect("token_loads")
for method_name in ("read", "read_raw", "write", "_post_json"):
    setattr(transport_module.HFTransport, method_name, _deny_effect("transport_calls"))
for module, function_names in (
    (formatting_engine, ("write_draft_artifact", "update_draft_metadata", "delete_draft_artifact")),
    (drafts_module, ("update_draft_metadata", "delete_draft_artifact")),
):
    for function_name in function_names:
        setattr(module, function_name, _deny_effect("draft_writes"))

def _envelope(name, arguments):
    calls = effects["handlers"].setdefault(name, [])
    calls.append(dict(arguments))
    return {
        "content": [{"type": "text", "text": f"safe sentinel {name}"}],
        "structuredContent": {
            "tool": name,
            "handler_calls": len(calls),
            "handler_counts": {tool: len(tool_calls) for tool, tool_calls in effects["handlers"].items()},
            "arguments": arguments,
            "transport_calls": effects["transport_calls"],
            "draft_writes": effects["draft_writes"],
            "config_loads": effects["config_loads"],
            "token_loads": effects["token_loads"],
            "network_attempts": len(network_attempts),
            "dependency_facts_json": json.dumps(dependency_facts),
        },
    }

def _capture(name):
    def handler(**kwargs):
        return _envelope(name, kwargs)
    return handler

def posts_reply_handler(*, tid, confirm_live, message=None, source_path=None,
                        message_format="mycode", draft_id=None, draft_path=None):
    return _envelope("posts.reply", {
        "tid": tid,
        "confirm_live": confirm_live,
        "message": message,
        "source_path": source_path,
        "message_format": message_format,
        "draft_id": draft_id,
        "draft_path": draft_path,
    })

def wire_probe_handler(*, selector_a, selector_b, count, confirmed, flag,
                       items, details, numbers, text, choice=None, mode=None,
                       nullable=None, timestamp=None, defaulted):
    return _envelope("wire_probe", locals())

handlers = {
    "bytes.deposit": _capture("bytes.deposit"),
    "bytes.withdraw": _capture("bytes.withdraw"),
    "posts.reply": posts_reply_handler,
    "drafts.delete": _capture("drafts.delete"),
    "drafts.update": _capture("drafts.update"),
}
for tool_name, handler in handlers.items():
    spec = get_tool_spec(tool_name)
    adapter.register_tool(
        name=mcp_tool_name(tool_name),
        description=f"Offline schema probe for {tool_name}",
        input_schema=build_tool_schema(spec, policy),
        annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
        handler=handler,
        output_schema=build_tool_output_schema(spec),
    )
adapter.register_tool(
    name="wire_probe",
    description="Local synthetic adapter schema probe",
    input_schema=probe_schema,
    annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True},
    handler=wire_probe_handler,
)
app.run(transport="stdio")
'''


@pytest.mark.core
@pytest.mark.parametrize("modern", [False, True], ids=["legacy", "modern"])
def test_normal_stdio_read_surface_and_pagination_on_actual_wire(modern: bool) -> None:
    env = {"PATH": os.defpath, "PYTHONPATH": _child_pythonpath(), "PYTHONUNBUFFERED": "1"}
    expected_dependency_facts = _schema_dependency_facts()
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
        stderr=subprocess.PIPE,
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
                assert minimal["structuredContent"]["offline_token_reads"] == str(calls)
                assert minimal["structuredContent"]["offline_network_attempts"] == "0"
                assert json.loads(minimal["structuredContent"]["offline_dependency_facts_json"]) == expected_dependency_facts
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
                        {**selector, "unexpected": "UNTRUSTED-MESSAGE-DO-NOT-ECHO"},
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
                        assert "UNTRUSTED-MESSAGE-DO-NOT-ECHO" not in serialized_error
                for page, per_page in ((1, 1), (2, 30)):
                    result = send("tools/call", {"name": name, "arguments": {**selector, "page": page, "per_page": per_page, "output_mode": "raw", "include_raw_payload": True}})
                    calls += 1
                    assert not result.get("isError", False), result
                    assert result["structuredContent"]["offline_calls"] == str(calls)
                    assert result["structuredContent"]["offline_token_reads"] == str(calls)
                    assert result["structuredContent"]["offline_network_attempts"] == "0"
                    assert result["structuredContent"]["_hf_flow"]["version"] == 1
                    canonical_name = name.replace("_", ".")
                    assert result["content"][0] == {
                        "type": "text",
                        "text": f"{canonical_name} returned 1 row(s).",
                    }
                    resources = [part for part in result["content"] if part["type"] == "resource"]
                    assert len(resources) == 1
                    resource = resources[0]["resource"]
                    assert resource["uri"] == f"hf-mcp://raw/{canonical_name}"
                    assert resource["mimeType"] == "application/json"
                    raw_payload = json.loads(resource["text"])
                    root = "forums" if name.startswith("forums") else "threads" if name.startswith("threads") else "posts"
                    expected_raw_payload = {
                        root: [{"fid": 123, "tid": 456, "pid": 789, "subject": "Offline fixture"}],
                        "offline_calls": calls,
                        "offline_token_reads": calls,
                        "offline_network_attempts": 0,
                        "offline_dependency_facts_json": json.dumps(expected_dependency_facts),
                        "offline_page": page,
                        "offline_per_page": per_page,
                    }
                    assert raw_payload == expected_raw_payload
                    assert resource["text"] == json.dumps(expected_raw_payload, ensure_ascii=False)
                    _assert_no_nested_hf_envelope_text(result["content"])
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
        assert process.stderr is not None
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        assert "Traceback" not in stderr
        assert "UNTRUSTED-MESSAGE-DO-NOT-ECHO" not in stderr


@pytest.mark.core
@pytest.mark.registry
@pytest.mark.parametrize("modern", [False, True], ids=["legacy", "modern"])
def test_write_and_composition_schema_matrix_on_actual_stdio(
    modern: bool,
    tmp_path: Path,
) -> None:
    draft_dir = tmp_path / "drafts"
    draft_dir.mkdir()
    server_probe = WRITE_SERVER_TEMPLATE.replace(
        "PROBE_SCHEMA_JSON",
        repr(json.dumps(WIRE_PROBE_SCHEMA)),
    )
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": _child_pythonpath(),
        "PYTHONUNBUFFERED": "1",
        "HF_MCP_CONFIG": str(tmp_path / "unused-config.yaml"),
        "HF_MCP_TOKEN_PATH": str(tmp_path / "unused-token.json"),
        "HF_MCP_DRAFT_DIR": str(draft_dir),
    }
    capabilities = frozenset(
        {"bytes.deposit", "bytes.withdraw", "posts.reply", "drafts.delete", "drafts.update"}
    )
    parameter_families = frozenset(
        {
            "confirm.live",
            "writes.bytes",
            "selectors.thread",
            "writes.content",
            "drafts.selector",
            "drafts.confirm_delete",
            "drafts.metadata",
        }
    )
    policy = CapabilityPolicy(
        HFMCPSettings(
            profile="custom",
            enabled_capabilities=capabilities,
            enabled_parameter_families=parameter_families,
        )
    )
    expected_dependency_facts = _schema_dependency_facts()
    with subprocess.Popen(
        [sys.executable, "-c", server_probe],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=PRODUCT_ROOT,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        sequence = 0

        def send(method: str, params: dict) -> dict:
            nonlocal sequence
            sequence += 1
            if modern:
                params = {
                    **params,
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                }
            message = {"jsonrpc": "2.0", "method": method, "params": params, "id": sequence}
            process.stdin.write((json.dumps(message) + "\n").encode())
            process.stdin.flush()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=10), "stdio response timed out"
                line = process.stdout.readline()
            assert line, f"stdio server exited ({process.poll()})"
            response = json.loads(line)
            assert response["id"] == sequence
            return response["result"] if "result" in response else {"jsonrpcError": response["error"]}

        try:
            if not modern:
                initialized = send(
                    "initialize",
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "offline-write-test", "version": "1"},
                    },
                )
                assert initialized["protocolVersion"] == "2025-11-25"
                sequence += 1
                process.stdin.write(
                    (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n").encode()
                )
                process.stdin.flush()

            tool_rows = {tool["name"]: tool for tool in send("tools/list", {})["tools"]}
            canonical_names = (
                "bytes.deposit",
                "bytes.withdraw",
                "posts.reply",
                "drafts.delete",
                "drafts.update",
            )
            expected_wire_names = {get_tool_spec(name).tool_name.replace(".", "_") for name in canonical_names}
            expected_wire_names |= {"wire_probe"}
            assert set(tool_rows) == expected_wire_names
            assert "hf_doctor" not in tool_rows
            for canonical_name in canonical_names:
                spec = get_tool_spec(canonical_name)
                expected_schema = build_tool_schema(spec, policy)
                if "title" not in expected_schema:
                    expected_schema["title"] = tool_rows[canonical_name.replace(".", "_")]["inputSchema"]["title"]
                published = tool_rows[canonical_name.replace(".", "_")]["inputSchema"]
                for key, value in tuple(expected_schema.items()):
                    if key.startswith("x-hf-") and value is None and key not in published:
                        expected_schema.pop(key)
                assert published == expected_schema
            assert tool_rows["wire_probe"]["inputSchema"] == WIRE_PROBE_SCHEMA
            titles = [tool["inputSchema"]["title"] for tool in tool_rows.values()]
            assert len(set(titles)) == len(titles)

            expected_handler_calls = {name: 0 for name in (*canonical_names, "wire_probe")}
            id_value = "0123456789abcdef0123456789abcdef"
            valid_arguments = {
                "bytes.deposit": {"amount": 100, "confirm_live": True},
                "bytes.withdraw": {"amount": 100, "confirm_live": True},
                "posts.reply": {"tid": 456, "message": "safe reply", "confirm_live": True},
                "drafts.delete": {"draft_id": id_value, "confirm_delete": True},
                "drafts.update": {"draft_id": id_value, "status": "draft", "title": "safe title"},
                "wire_probe": {
                    "selector_b": "chosen-b",
                    "count": 1,
                    "confirmed": True,
                    "flag": True,
                    "items": [{"code": "valid"}],
                    "details": {"label": "valid"},
                    "numbers": [1],
                    "text": "valid",
                    "choice": "allowed",
                    "nullable": None,
                    "timestamp": "not-validated-as-a-date-time-annotation",
                },
            }

            def wire_name(canonical_name: str) -> str:
                return canonical_name.replace(".", "_")

            def valid_call(canonical_name: str, arguments: dict) -> dict:
                result = send(
                    "tools/call",
                    {"name": wire_name(canonical_name), "arguments": arguments},
                )
                assert not result.get("isError", False), result
                structured = result["structuredContent"]
                expected_handler_calls[canonical_name] += 1
                assert structured["handler_calls"] == expected_handler_calls[canonical_name]
                assert structured["tool"] == canonical_name
                assert structured["transport_calls"] == 0
                assert structured["draft_writes"] == 0
                assert structured["config_loads"] == 0
                assert structured["token_loads"] == 0
                assert structured["network_attempts"] == 0
                assert json.loads(structured["dependency_facts_json"]) == expected_dependency_facts
                assert ("resultType" in result) is modern
                return structured

            def invalid_without_effect(
                canonical_name: str,
                arguments: dict,
                constraint: str,
                argument_path: str,
                untrusted_marker: str | None = None,
            ) -> None:
                result = send(
                    "tools/call",
                    {"name": wire_name(canonical_name), "arguments": arguments},
                )
                assert result.get("isError") is True, result
                assert "jsonrpcError" not in result
                error_text = json.dumps(result)
                assert f"Error executing tool {wire_name(canonical_name)}" in error_text
                assert constraint in error_text
                assert argument_path in error_text
                assert "UnexpectedToolError" not in error_text
                if untrusted_marker is not None:
                    assert untrusted_marker not in error_text
                control = valid_call(canonical_name, valid_arguments[canonical_name])
                assert control["handler_calls"] == expected_handler_calls[canonical_name]

            for canonical_name in canonical_names:
                valid_call(canonical_name, valid_arguments[canonical_name])

            # Product-generated Bytes schemas preserve the 100-unit lower bound and strict JSON types.
            for canonical_name in ("bytes.deposit", "bytes.withdraw"):
                valid_call(canonical_name, {"amount": 100.0, "confirm_live": True})
                invalid_without_effect(canonical_name, {"amount": 99, "confirm_live": True}, "minimum", "$.amount")
                invalid_without_effect(canonical_name, {"amount": True, "confirm_live": True}, "type", "$.amount")
                invalid_without_effect(canonical_name, {"amount": "100", "confirm_live": True}, "type", "$.amount")
                invalid_without_effect(canonical_name, {"amount": 100.5, "confirm_live": True}, "type", "$.amount")
                invalid_without_effect(canonical_name, {"amount": 100, "confirm_live": False}, "const", "$.confirm_live")
                invalid_without_effect(canonical_name, {"amount": 100, "confirm_live": 1}, "type", "$.confirm_live")
                invalid_without_effect(canonical_name, {"amount": 100, "confirm_live": "true"}, "type", "$.confirm_live")
                invalid_without_effect(canonical_name, {"amount": 100}, "required", "$")
                invalid_without_effect(canonical_name, {"confirm_live": True}, "required", "$")
                invalid_without_effect(
                    canonical_name,
                    {"amount": 100, "confirm_live": True, "unknown": "UNTRUSTED-MESSAGE-DO-NOT-ECHO"},
                    "additionalProperties",
                    "$",
                    untrusted_marker="UNTRUSTED-MESSAGE-DO-NOT-ECHO",
                )

            # posts.reply supplies each anyOf selector alone and accepts selector combinations.
            for arguments in (
                {"tid": 456, "message": "draft body", "confirm_live": True},
                {"tid": 456, "draft_id": id_value, "confirm_live": True},
                {"tid": 456, "draft_path": str(draft_dir / "cached.json"), "confirm_live": True},
                {"tid": 456, "message": "both selectors", "draft_id": id_value, "confirm_live": True},
            ):
                output = valid_call("posts.reply", arguments)
                assert output["arguments"]["message_format"] == "mycode"
            invalid_without_effect("posts.reply", {"tid": "456", "message": "valid", "confirm_live": True}, "type", "$.tid")
            invalid_without_effect("posts.reply", {"tid": True, "message": "valid", "confirm_live": True}, "type", "$.tid")
            invalid_without_effect("posts.reply", {"tid": 456, "message": "", "confirm_live": True}, "minLength", "$.message")
            invalid_without_effect("posts.reply", {"tid": 456, "message_format": "invalid", "message": "valid", "confirm_live": True}, "enum", "$.message_format")
            invalid_without_effect("posts.reply", {"tid": 456, "draft_id": "not-a-valid-draft-id", "confirm_live": True}, "pattern", "$.draft_id")
            invalid_without_effect("posts.reply", {"tid": 456, "draft_id": id_value, "confirm_live": False}, "const", "$.confirm_live")
            invalid_without_effect("posts.reply", {"tid": 456, "draft_id": id_value, "confirm_live": 1}, "type", "$.confirm_live")
            invalid_without_effect("posts.reply", {"tid": 456, "draft_id": id_value, "confirm_live": "true"}, "type", "$.confirm_live")
            invalid_without_effect("posts.reply", {"tid": 456, "message": "valid"}, "required", "$")
            invalid_without_effect("posts.reply", {"tid": 456, "confirm_live": True}, "anyOf", "$")
            invalid_without_effect("posts.reply", {"tid": 456, "message": "valid", "confirm_live": True, "subject": "removed field"}, "additionalProperties", "$")

            # Local draft tools remain no-I/O sentinels while exercising draft status, selector, and confirmation schemas.
            for status in ("draft", "ready", "approved", "archived"):
                valid_call("drafts.update", {"draft_id": id_value, "status": status, "title": "safe title"})
            valid_call("drafts.update", {"draft_path": str(draft_dir / "metadata.json"), "status": "ready"})
            invalid_without_effect("drafts.update", {**valid_arguments["drafts.update"], "status": "unknown"}, "enum", "$.status")
            invalid_without_effect("drafts.update", {**valid_arguments["drafts.update"], "status": None}, "type", "$.status")
            invalid_without_effect("drafts.update", {**valid_arguments["drafts.update"], "draft_id": "invalid-id"}, "pattern", "$.draft_id")
            valid_call("drafts.delete", {"draft_path": str(draft_dir / "delete.json"), "confirm_delete": True})
            invalid_without_effect("drafts.delete", {"draft_id": id_value, "confirm_delete": False}, "const", "$.confirm_delete")
            invalid_without_effect("drafts.delete", {"draft_id": id_value, "confirm_delete": 1}, "type", "$.confirm_delete")
            invalid_without_effect("drafts.delete", {"draft_id": id_value, "confirm_delete": "true"}, "type", "$.confirm_delete")
            invalid_without_effect("drafts.delete", {"draft_id": id_value}, "required", "$")
            invalid_without_effect("drafts.delete", {"confirm_delete": True}, "anyOf", "$")

            # The local synthetic probe covers composed schemas, nested objects/items, and defaults on the actual SDK wire.
            probe_args = valid_arguments["wire_probe"]
            wire_probe_result = valid_call("wire_probe", probe_args)
            assert wire_probe_result["arguments"]["selector_a"] == "A"
            assert wire_probe_result["arguments"]["defaulted"] == ["safe"]
            assert wire_probe_result["arguments"]["timestamp"] == "not-validated-as-a-date-time-annotation"
            assert wire_probe_result["arguments"]["nullable"] is None
            selector_a_only = {**probe_args, "selector_a": "explicit-a"}
            selector_a_only.pop("selector_b")
            selector_a_result = valid_call("wire_probe", selector_a_only)
            assert selector_a_result["arguments"]["selector_b"] == "B"
            valid_call("wire_probe", {**probe_args, "selector_a": "explicit-a", "selector_b": "explicit-b"})
            valid_call("wire_probe", {**probe_args, "count": 1.0})
            invalid_without_effect("wire_probe", {**probe_args, "count": True}, "type", "$.count")
            invalid_without_effect("wire_probe", {**probe_args, "count": "1"}, "type", "$.count")
            invalid_without_effect("wire_probe", {**probe_args, "count": 1.5}, "type", "$.count")
            invalid_without_effect("wire_probe", {**probe_args, "count": 0}, "minimum", "$.count")
            invalid_without_effect("wire_probe", {**probe_args, "count": 4}, "maximum", "$.count")
            invalid_without_effect("wire_probe", {**probe_args, "items": [{"code": "UPPER"}]}, "pattern", "$.items[0].code")
            invalid_without_effect("wire_probe", {**probe_args, "items": [{"code": "valid", "extra": 1}]}, "additionalProperties", "$.items[0]")
            invalid_without_effect("wire_probe", {**probe_args, "details": "{}"}, "type", "$.details")
            invalid_without_effect("wire_probe", {**probe_args, "details": {"label": ""}}, "minLength", "$.details.label")
            invalid_without_effect("wire_probe", {**probe_args, "details": {"label": "valid", "extra": 1}}, "additionalProperties", "$.details")
            invalid_without_effect("wire_probe", {**probe_args, "numbers": "[1]"}, "type", "$.numbers")
            invalid_without_effect("wire_probe", {**probe_args, "numbers": [True]}, "type", "$.numbers[0]")
            invalid_without_effect("wire_probe", {**probe_args, "text": ""}, "minLength", "$.text")
            invalid_without_effect("wire_probe", {**probe_args, "text": None}, "type", "$.text")
            invalid_without_effect("wire_probe", {**probe_args, "choice": "unlisted"}, "enum", "$.choice")
            invalid_without_effect("wire_probe", {**probe_args, "choice": "blocked"}, "not", "$")
            invalid_without_effect("wire_probe", {**probe_args, "mode": "x"}, "oneOf", "$")
            invalid_without_effect("wire_probe", {key: value for key, value in probe_args.items() if key not in {"selector_a", "selector_b"}}, "anyOf", "$")
            invalid_without_effect("wire_probe", {**probe_args, "confirmed": False}, "const", "$.confirmed")
            invalid_without_effect("wire_probe", {**probe_args, "confirmed": 1}, "type", "$.confirmed")
            invalid_without_effect("wire_probe", {**probe_args, "confirmed": "true"}, "type", "$.confirmed")
            invalid_without_effect("wire_probe", {**probe_args, "unknown": "UNTRUSTED-MESSAGE-DO-NOT-ECHO"}, "additionalProperties", "$", untrusted_marker="UNTRUSTED-MESSAGE-DO-NOT-ECHO")

        finally:
            process.stdin.close()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        assert process.stderr is not None
        stderr = process.stderr.read().decode("utf-8", errors="replace")
        assert "Traceback" not in stderr
        assert "UNTRUSTED-MESSAGE-DO-NOT-ECHO" not in stderr
