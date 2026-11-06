from __future__ import annotations

import json
import inspect
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest

import hf_mcp


from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings, PRESET_CAPABILITIES, PRESET_PARAMETER_FAMILIES
from hf_mcp.dispatcher import RuntimeBundle, register_tools
from hf_mcp.registry import get_specs, mcp_tool_name
from hf_mcp.server import _MCPServerToolAdapter, _with_schema_signature
from hf_mcp.server import create_server, serve_stdio
from hf_mcp.token_store import TokenBundle
from hf_mcp.tools.read_core import build_core_read_handlers
from hf_mcp.tools.read_extended import build_extended_read_handlers
from hf_mcp.transport import HFTransport
from hf_mcp.write_preflight import WritePreflightError

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"


class _CaptureServer:
    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        annotations: dict[str, Any],
        handler: Any,
        output_schema: dict[str, object] | None = None,
    ) -> None:
        self.tools[name] = {
            "description": description,
            "input_schema": input_schema,
            "annotations": annotations,
            "output_schema": output_schema,
            "handler": handler,
        }


class _StubTokenStore:
    def require_bundle(self) -> TokenBundle:
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset())


class _StubReadTransport:
    def read(
        self, *, asks: dict[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        if helper is None and "me" in asks:
            return {"me": [{"uid": "5", "username": "forge"}]}
        if helper == "sigmarket/order":
            return {"sigmarket/order": [{"oid": "17", "uid": "5"}]}
        raise AssertionError(f"unexpected helper: {helper}")

    def read_raw(
        self, *, asks: dict[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        if helper is None and "me" in asks:
            return {"me": [{"uid": "5", "username": "forge", "raw": True}]}
        if helper == "sigmarket/order":
            return {"sigmarket/order": [{"oid": "17", "uid": "5", "raw": True}]}
        raise AssertionError(f"unexpected helper: {helper}")


def _runtime_bundle() -> RuntimeBundle:
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    return RuntimeBundle(
        transport=transport,
        auth_context=TokenBundle(
            access_token="token", token_type="Bearer", scope=frozenset({"read"})
        ),
    )


def _policy(
    *, enabled_capabilities: set[str], enabled_parameter_families: set[str]
) -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset(enabled_capabilities),
            enabled_parameter_families=frozenset(enabled_parameter_families),
        )
    )


def _assert_rejects_nested_envelope_json_text(result: Any) -> None:
    for item in result.content:
        if getattr(item, "type", None) != "text":
            continue
        text_value = getattr(item, "text", None)
        if not isinstance(text_value, str):
            continue
        try:
            parsed = json.loads(text_value)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(parsed, dict)
            and isinstance(parsed.get("content"), list)
            and isinstance(parsed.get("structuredContent"), dict)
        ):
            raise AssertionError("Nested envelope JSON detected in text content")


def _assert_not_placeholder_handler(handler: Any) -> None:
    assert getattr(handler, "__name__", "") != "_handler"
    code = getattr(handler, "__code__", None)
    if code is None:
        return
    string_constants = [
        constant for constant in code.co_consts if isinstance(constant, str)
    ]
    assert all("not implemented yet" not in constant for constant in string_constants)


@pytest.mark.core
@pytest.mark.registry
def test_sdk_adapter_uses_defensive_original_schema_before_argument_coercion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.mcpserver import MCPServer
    from pydantic import ValidationError
    import jsonschema

    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Caller-owned title",
        "type": "object",
        "$defs": {"choice": {"type": "string", "enum": ["allowed", "blocked"]}},
        "properties": {
            "selector_a": {"type": "string", "default": "A"},
            "selector_b": {"type": "string", "default": "B"},
            "choice": {"$ref": "#/$defs/choice"},
            "count": {"type": "integer"},
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
            "array_numbers": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
            },
            "text": {"type": "string", "minLength": 1},
            "flag": {"type": "boolean"},
            "mode": {"type": "string"},
            "nullable": {"type": ["string", "null"]},
            "timestamp": {"type": "string", "format": "date-time"},
            "defaulted": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["safe"],
            },
            "confirmed": {"type": "boolean", "const": True},
        },
        "required": ["confirmed", "count", "items", "details", "array_numbers", "text"],
        "additionalProperties": False,
        "anyOf": [{"required": ["selector_a"]}, {"required": ["selector_b"]}],
        "oneOf": [
            {"required": ["flag"]},
            {"required": ["flag", "mode"], "properties": {"mode": {"const": "x"}}},
        ],
        "allOf": [{"properties": {"count": {"minimum": 1, "maximum": 3}}}],
        "not": {"properties": {"choice": {"const": "blocked"}}, "required": ["choice"]},
        "x-hf-probe": {"complete": True},
    }
    calls: list[dict[str, Any]] = []

    def handler(
        *,
        selector_a: str,
        selector_b: str,
        choice: str | None = None,
        count: int,
        items: list[dict[str, str]],
        details: dict[str, str],
        array_numbers: list[int],
        text: str,
        flag: bool,
        mode: str | None = None,
        nullable: str | None = None,
        timestamp: str | None = None,
        defaulted: list[str],
        confirmed: bool,
    ) -> dict[str, Any]:
        result = {
            "selector_a": selector_a,
            "selector_b": selector_b,
            "choice": choice,
            "count": count,
            "items": items,
            "details": details,
            "array_numbers": array_numbers,
            "text": text,
            "flag": flag,
            "mode": mode,
            "nullable": nullable,
            "timestamp": timestamp,
            "defaulted": defaulted,
            "confirmed": confirmed,
        }
        calls.append(result)
        return result

    compiled_tool_schemas = 0
    draft_validator = jsonschema.Draft202012Validator

    def _count_validator_construction(
        schema_to_compile: Any, *args: Any, **kwargs: Any
    ) -> Any:
        nonlocal compiled_tool_schemas
        if (
            isinstance(schema_to_compile, dict)
            and schema_to_compile.get("title") == "Caller-owned title"
        ):
            compiled_tool_schemas += 1
        return draft_validator(schema_to_compile, *args, **kwargs)

    _count_validator_construction.check_schema = draft_validator.check_schema
    monkeypatch.setattr(
        jsonschema, "Draft202012Validator", _count_validator_construction
    )
    app = MCPServer(name="hf-mcp-adapter-probe")
    adapter = _MCPServerToolAdapter(app)
    adapter.register_tool(
        name="wire_probe",
        description="Strict adapter probe",
        input_schema=schema,
        annotations={"title": "wire_probe", "readOnlyHint": True},
        handler=handler,
    )
    schema["$defs"]["choice"]["enum"] = ["caller-mutated"]
    schema["properties"]["selector_a"]["default"] = "caller-mutated"
    schema["properties"]["defaulted"]["default"].append("caller-mutated")
    schema["x-hf-probe"]["complete"] = False

    tool = app._tool_manager.get_tool("wire_probe")
    assert tool is not None
    published_schema = tool.parameters
    assert published_schema["title"] == "Caller-owned title"
    assert published_schema["$defs"]["choice"]["enum"] == ["allowed", "blocked"]
    assert published_schema["properties"]["selector_a"]["default"] == "A"
    assert published_schema["x-hf-probe"] == {"complete": True}
    assert published_schema["properties"]["timestamp"]["format"] == "date-time"
    validator = tool.fn_metadata._input_validator
    assert validator is not None

    valid_arguments = {
        "selector_a": "explicit-a",
        "selector_b": "explicit-b",
        "choice": "allowed",
        "count": 1,
        "items": [{"code": "valid"}],
        "details": {"label": "valid"},
        "array_numbers": [1],
        "text": "valid",
        "flag": True,
        "nullable": None,
        "timestamp": "not-validated-as-a-date-time-annotation",
        "confirmed": True,
    }
    validated = tool.fn_metadata.validate_arguments(valid_arguments)
    assert validated == {**valid_arguments, "defaulted": ["safe"]}
    assert type(validated["count"]) is int
    assert compiled_tool_schemas == 1
    assert tool.fn_metadata._input_validator is validator

    without_selector_a = {**valid_arguments}
    without_selector_a.pop("selector_a")
    defaulted_selector = tool.fn_metadata.validate_arguments(without_selector_a)
    assert defaulted_selector["selector_a"] == "A"
    without_selectors = {
        key: value
        for key, value in valid_arguments.items()
        if key not in {"selector_a", "selector_b"}
    }
    invalid_cases = (
        (
            "boolean is not an integer",
            {**valid_arguments, "count": True},
            "type",
            "$.count",
        ),
        (
            "numeric strings are not integers",
            {**valid_arguments, "count": "1"},
            "type",
            "$.count",
        ),
        (
            "fractional integers reject",
            {**valid_arguments, "count": 1.5},
            "type",
            "$.count",
        ),
        ("allOf minimum", {**valid_arguments, "count": 0}, "minimum", "$.count"),
        ("allOf maximum", {**valid_arguments, "count": 4}, "maximum", "$.count"),
        (
            "enum rejects",
            {**valid_arguments, "choice": "unlisted-choice"},
            "enum",
            "$.choice",
        ),
        ("not rejects", {**valid_arguments, "choice": "blocked"}, "not", "$"),
        ("oneOf rejects double match", {**valid_arguments, "mode": "x"}, "oneOf", "$"),
        (
            "nested pattern",
            {**valid_arguments, "items": [{"code": "UPPER"}]},
            "pattern",
            "$.items[0].code",
        ),
        (
            "nested closed object",
            {**valid_arguments, "items": [{"code": "valid", "extra": 1}]},
            "additionalProperties",
            "$.items[0]",
        ),
        (
            "encoded object string",
            {**valid_arguments, "details": "{}"},
            "type",
            "$.details",
        ),
        (
            "encoded array string",
            {**valid_arguments, "array_numbers": "[1]"},
            "type",
            "$.array_numbers",
        ),
        (
            "array item bool",
            {**valid_arguments, "array_numbers": [True]},
            "type",
            "$.array_numbers[0]",
        ),
        ("nonnullable null", {**valid_arguments, "text": None}, "type", "$.text"),
        (
            "additional root property",
            {**valid_arguments, "unknown": "secret-value"},
            "additionalProperties",
            "$",
        ),
        (
            "const false",
            {**valid_arguments, "confirmed": False},
            "const",
            "$.confirmed",
        ),
        ("const numeric", {**valid_arguments, "confirmed": 1}, "type", "$.confirmed"),
        (
            "const string",
            {**valid_arguments, "confirmed": "true"},
            "type",
            "$.confirmed",
        ),
        (
            "missing required confirmation",
            {
                key: value
                for key, value in valid_arguments.items()
                if key != "confirmed"
            },
            "required",
            "$",
        ),
        ("selector defaults cannot satisfy anyOf", without_selectors, "anyOf", "$"),
    )
    for case_name, invalid, constraint, path in invalid_cases:
        with pytest.raises(ValidationError) as error:
            tool.fn_metadata.validate_arguments(invalid)
        error_text = str(error.value)
        assert constraint in error_text, case_name
        assert path in error_text, case_name
        assert "secret-value" not in error_text
    with pytest.raises(ValidationError):
        tool.fn_metadata.validate_arguments(["must-be-an-object"])
    assert compiled_tool_schemas == 1
    assert calls == []

    async def invoke(arguments_to_call: dict[str, Any]) -> Any:
        raw_validated = tool.fn_metadata.validate_arguments(arguments_to_call)
        return await tool.fn_metadata.call_fn(tool.fn, tool.is_async, raw_validated)

    result = anyio.run(invoke, without_selector_a)
    assert result["count"] == 1
    assert result["selector_a"] == "A"
    assert result["nullable"] is None
    assert result["timestamp"] == "not-validated-as-a-date-time-annotation"
    assert result["defaulted"] == ["safe"]
    assert result["confirmed"] is True
    result["defaulted"].append("call-mutated")
    repeat_validation = tool.fn_metadata.validate_arguments(without_selector_a)
    assert repeat_validation["defaulted"] == ["safe"]

    float_result = anyio.run(invoke, {**valid_arguments, "count": 1.0})
    assert type(float_result["count"]) is float
    assert float_result["count"] == 1.0
    assert calls == [result, float_result]
    assert compiled_tool_schemas == 1


@pytest.mark.core
@pytest.mark.registry
def test_sdk_adapter_rejects_incompatible_registry_before_tool_exposure() -> None:
    class _IncompatibleApp:
        def add_tool(self, handler: Any, **kwargs: Any) -> None:
            del handler, kwargs

    adapter = _MCPServerToolAdapter(_IncompatibleApp())
    with pytest.raises(RuntimeError, match="tool manager.*metadata capability"):
        adapter.register_tool(
            name="unsupported_probe",
            description="Unsupported SDK probe",
            input_schema={"type": "object", "properties": {}},
            annotations={},
            handler=lambda: None,
        )


@pytest.mark.parametrize(
    "schema",
    [
        {
            "type": "object",
            "properties": {"value": {"type": "integer", "minimum": "low"}},
        },
        {
            "type": "object",
            "properties": {"value": {"$ref": "https://example.invalid/schema"}},
        },
        {"type": "object", "properties": {"value": {"$ref": "#/$defs/missing"}}},
        {
            "type": "object",
            "properties": {
                "value": {"$dynamicRef": "https://example.invalid/no-fetch"}
            },
        },
        {"type": "object", "properties": {"value": {"$dynamicRef": "#/$defs/missing"}}},
    ],
    ids=[
        "invalid-draft-schema",
        "nonlocal-reference",
        "unresolved-local-reference",
        "nonlocal-dynamic-reference",
        "unresolved-local-dynamic-reference",
    ],
)
@pytest.mark.core
@pytest.mark.registry
def test_sdk_adapter_rejects_invalid_or_remote_schema_before_tool_exposure(
    schema: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import http.client
    from mcp.server.mcpserver import MCPServer

    network_attempts: list[str] = []

    def _deny_network(self: Any) -> None:
        network_attempts.append(type(self).__name__)
        raise AssertionError("schema reference resolution attempted network access")

    monkeypatch.setattr(http.client.HTTPConnection, "connect", _deny_network)
    monkeypatch.setattr(http.client.HTTPSConnection, "connect", _deny_network)
    app = MCPServer(name="hf-mcp-schema-probe")
    adapter = _MCPServerToolAdapter(app)
    with pytest.raises(ValueError, match="Invalid Draft 2020-12 input schema"):
        adapter.register_tool(
            name="invalid_schema_probe",
            description="Invalid schema probe",
            input_schema=schema,
            annotations={},
            handler=lambda **kwargs: kwargs,
        )
    assert app._tool_manager.get_tool("invalid_schema_probe") is None
    assert network_attempts == []


@pytest.mark.core
@pytest.mark.registry
def test_sdk_adapter_keeps_resolvable_local_dynamic_reference() -> None:
    from mcp.server.mcpserver import MCPServer
    from pydantic import ValidationError

    app = MCPServer(name="hf-mcp-dynamic-reference-probe")
    adapter = _MCPServerToolAdapter(app)
    adapter.register_tool(
        name="dynamic_reference_probe",
        description="Local dynamic reference probe",
        input_schema={
            "type": "object",
            "$id": "https://example.invalid/schema-root",
            "$defs": {
                "nested": {
                    "$id": "nested",
                    "type": "object",
                    "$defs": {
                        "choice": {
                            "$dynamicAnchor": "choice",
                            "type": "string",
                            "enum": ["allowed"],
                        }
                    },
                    "properties": {"value": {"$dynamicRef": "#choice"}},
                    "required": ["value"],
                    "additionalProperties": False,
                }
            },
            "x-hf-reference-example": {
                "$ref": "https://example.invalid/annotation-only"
            },
            "properties": {"nested": {"$ref": "#/$defs/nested"}},
            "required": ["nested"],
            "additionalProperties": False,
        },
        annotations={},
        handler=lambda *, value: {"value": value},
    )
    tool = app._tool_manager.get_tool("dynamic_reference_probe")
    assert tool is not None
    assert tool.parameters["x-hf-reference-example"] == {
        "$ref": "https://example.invalid/annotation-only"
    }
    assert tool.fn_metadata.validate_arguments({"nested": {"value": "allowed"}}) == {
        "nested": {"value": "allowed"}
    }
    with pytest.raises(ValidationError):
        tool.fn_metadata.validate_arguments({"nested": {"value": "rejected"}})


@pytest.mark.core
@pytest.mark.registry
def test_sdk_adapter_checks_inserted_schema_default_against_its_property_schema() -> (
    None
):
    from mcp.server.mcpserver import MCPServer
    from pydantic import ValidationError

    calls: list[int] = []

    def handler(*, value: int) -> dict[str, int]:
        calls.append(value)
        return {"value": value}

    app = MCPServer(name="hf-mcp-default-probe")
    adapter = _MCPServerToolAdapter(app)
    adapter.register_tool(
        name="default_probe",
        description="Default validation probe",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "integer", "default": "1"}},
            "additionalProperties": False,
        },
        annotations={},
        handler=handler,
    )
    tool = app._tool_manager.get_tool("default_probe")
    assert tool is not None
    with pytest.raises(ValidationError) as error:
        tool.fn_metadata.validate_arguments({})
    assert "input_value='1'" not in str(error.value)
    assert calls == []


@pytest.mark.core
@pytest.mark.registry
def test_sdk_adapter_preserves_async_handler_execution_after_validation() -> None:
    from mcp.server.mcpserver import MCPServer
    from pydantic import ValidationError

    calls: list[str] = []

    async def handler(*, value: str) -> dict[str, str]:
        calls.append(value)
        return {"value": value}

    app = MCPServer(name="hf-mcp-async-adapter-probe")
    adapter = _MCPServerToolAdapter(app)
    adapter.register_tool(
        name="async_probe",
        description="Async adapter probe",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string", "minLength": 1}},
            "required": ["value"],
            "additionalProperties": False,
        },
        annotations={},
        handler=handler,
    )
    tool = app._tool_manager.get_tool("async_probe")
    assert tool is not None and tool.is_async is True

    with pytest.raises(ValidationError):
        tool.fn_metadata.validate_arguments({"value": ""})
    assert calls == []

    async def invoke() -> Any:
        validated = tool.fn_metadata.validate_arguments({"value": "accepted"})
        return await tool.fn_metadata.call_fn(tool.fn, tool.is_async, validated)

    result = anyio.run(invoke)
    assert result == {"value": "accepted"}
    assert calls == ["accepted"]


def test_nested_envelope_json_in_text_content_is_rejected_by_validator() -> None:
    import mcp.types as mcp_types

    nested_json = json.dumps(
        {
            "content": [{"type": "text", "text": "legacy"}],
            "structuredContent": {"me": []},
        }
    )
    result = mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=nested_json)],
        structuredContent={"me": []},
    )

    with pytest.raises(AssertionError, match="Nested envelope JSON detected"):
        _assert_rejects_nested_envelope_json_text(result)


def test_fastmcp_adapter_converts_hf_envelope_dict_to_protocol_call_tool_result() -> (
    None
):
    import mcp.types as mcp_types
    from mcp.server.mcpserver import MCPServer

    envelope = {
        "content": [
            {"type": "text", "text": "me.read returned 1 row(s)."},
            {
                "type": "resource",
                "resource": {
                    "uri": "hf-mcp://raw/me.read",
                    "mimeType": "application/json",
                    "text": '{"me":[{"uid":"5"}]}',
                },
            },
        ],
        "structuredContent": {
            "me": [{"uid": "5"}],
            "_hf_flow": {
                "version": 1,
                "server": {"name": "hf-mcp", "version": hf_mcp.__version__},
                "entry_tool": "me.read",
                "breadcrumbs": ["me"],
                "entities": {
                    "forum_ids": [],
                    "thread_ids": [],
                    "post_ids": [],
                    "user_ids": [5],
                },
                "next_actions": [],
            },
        },
    }

    app = MCPServer(name="hf-mcp-envelope-probe")
    adapter = _MCPServerToolAdapter(app)
    adapter.register_tool(
        name="me.read",
        description="Read me",
        input_schema={"type": "object", "properties": {}},
        annotations={
            "title": "me.read",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
        handler=lambda **_: envelope,
        output_schema={"type": "object"},
    )

    tool = app._tool_manager.get_tool("me.read")
    assert tool is not None
    normalized = tool.fn()
    assert isinstance(normalized, mcp_types.CallToolResult)
    assert normalized.structured_content["me"] == [{"uid": "5"}]
    assert normalized.structured_content["_hf_flow"]["version"] == 1
    assert isinstance(normalized.structured_content["_hf_flow"]["next_actions"], list)
    assert len(normalized.content) == 2
    assert isinstance(normalized.content[0], mcp_types.TextContent)
    assert normalized.content[0].text == "me.read returned 1 row(s)."
    assert isinstance(normalized.content[1], mcp_types.EmbeddedResource)
    raw_resource = normalized.content[1].resource.model_dump(
        by_alias=True, exclude_none=True
    )
    assert raw_resource == {
        "uri": "hf-mcp://raw/me.read",
        "mimeType": "application/json",
        "text": '{"me":[{"uid":"5"}]}',
    }


def test_runtime_stdio_client_session_returns_protocol_structured_content_and_raw_resource() -> (
    None
):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server_probe = """
import sys
from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.dispatcher import RuntimeBundle, register_tools
from hf_mcp.server import _MCPServerToolAdapter
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport
from mcp.server.mcpserver import MCPServer

class _ProbeTokenStore:
    def require_bundle(self):
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset({"read"}))

def _stub_read(*, asks, helper):
    if helper is not None or "me" not in asks:
        raise RuntimeError(f"unexpected helper: {helper}")
    return {"me": [{"uid": "5", "username": "forge"}]}

def _stub_read_raw(*, asks, helper):
    if helper is not None or "me" not in asks:
        raise RuntimeError(f"unexpected helper: {helper}")
    return {"me": [{"uid": "5", "username": "forge", "raw": True}]}

transport = HFTransport(token_store=_ProbeTokenStore(), base_url="https://example.test")
transport.read = _stub_read
transport.read_raw = _stub_read_raw

settings = HFMCPSettings(
    profile="test",
    enabled_capabilities=frozenset({"me.read"}),
    enabled_parameter_families=frozenset({"fields.me.basic", "selectors.user", "output.options"}),
)
policy = CapabilityPolicy(settings)
app = MCPServer(name="hf-mcp-probe")
adapter = _MCPServerToolAdapter(app)
register_tools(adapter, policy, RuntimeBundle(transport=transport))
app.run(transport="stdio")
"""

    async def _run_probe() -> None:
        env = dict(os.environ)
        pythonpath = env.get("PYTHONPATH")
        src_path = str(SRC_PATH)
        env["PYTHONPATH"] = f"{src_path}:{pythonpath}" if pythonpath else src_path
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", server_probe],
            env=env,
            cwd=str(PRODUCT_ROOT),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    "me_read",
                    {"output_mode": "raw", "include_raw_payload": True},
                )
        assert result.structured_content is not None
        assert result.structured_content["me"][0]["uid"] == "5"
        assert any(getattr(item, "type", None) == "resource" for item in result.content)
        _assert_rejects_nested_envelope_json_text(result)

    anyio.run(_run_probe)


def test_runtime_stdio_tool_list_has_unique_input_schema_titles_for_extended_reads() -> (
    None
):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server_probe = """
from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings, PRESET_PARAMETER_FAMILIES
from hf_mcp.dispatcher import RuntimeBundle, register_tools
from hf_mcp.server import _MCPServerToolAdapter
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport
from mcp.server.mcpserver import MCPServer

class _ProbeTokenStore:
    def require_bundle(self):
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset({"read"}))

transport = HFTransport(token_store=_ProbeTokenStore(), base_url="https://example.test")
settings = HFMCPSettings(
    profile="test",
    enabled_capabilities=frozenset({
        "bytes.read",
        "contracts.read",
        "disputes.read",
        "bratings.read",
        "sigmarket.market.read",
        "sigmarket.order.read",
        "admin.high_risk.read",
    }),
    enabled_parameter_families=PRESET_PARAMETER_FAMILIES["full_api"],
)
policy = CapabilityPolicy(settings)
app = MCPServer(name="hf-mcp-probe")
adapter = _MCPServerToolAdapter(app)
register_tools(adapter, policy, RuntimeBundle(transport=transport))
app.run(transport="stdio")
"""

    async def _run_probe() -> None:
        env = dict(os.environ)
        pythonpath = env.get("PYTHONPATH")
        src_path = str(SRC_PATH)
        env["PYTHONPATH"] = f"{src_path}:{pythonpath}" if pythonpath else src_path
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", server_probe],
            env=env,
            cwd=str(PRODUCT_ROOT),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()

        titles = {
            tool.name: (tool.input_schema or {}).get("title") for tool in result.tools
        }
        assert titles["bytes_read"] == "bytes_read_handlerArguments"
        assert titles["contracts_read"] == "contracts_read_handlerArguments"
        assert titles["disputes_read"] == "disputes_read_handlerArguments"
        assert titles["bratings_read"] == "bratings_read_handlerArguments"
        assert (
            titles["sigmarket_market_read"] == "sigmarket_market_read_handlerArguments"
        )
        assert titles["sigmarket_order_read"] == "sigmarket_order_read_handlerArguments"
        assert titles["admin_high_risk_read"] == "admin_high_risk_read_handlerArguments"
        assert len(set(titles.values())) == len(titles)

    anyio.run(_run_probe)


def test_core_read_handler_contract_stays_internal_envelope_dict() -> None:
    policy = _policy(
        enabled_capabilities={"me.read"},
        enabled_parameter_families={"fields.me.basic", "selectors.user"},
    )
    handler = build_core_read_handlers(policy, _StubReadTransport())["me.read"]

    result = handler(output_mode="structured", include_raw_payload=False)

    assert isinstance(result, dict)
    assert isinstance(result.get("content"), list)
    assert isinstance(result.get("structuredContent"), dict)
    assert "me" in result["structuredContent"]


def test_extended_read_handler_contract_stays_internal_envelope_dict() -> None:
    policy = _policy(
        enabled_capabilities={"sigmarket.order.read"},
        enabled_parameter_families={"selectors.sigmarket", "filters.pagination"},
    )
    handler = build_extended_read_handlers(policy, _StubReadTransport())[
        "sigmarket.order.read"
    ]

    result = handler(oid=17, output_mode="raw", include_raw_payload=True)

    assert isinstance(result, dict)
    assert isinstance(result.get("content"), list)
    assert isinstance(result.get("structuredContent"), dict)
    assert "sigmarket/order" in result["structuredContent"]


def test_dispatcher_registers_only_policy_allowed_registry_rows() -> None:
    policy = _policy(
        enabled_capabilities={"threads.read", "posts.reply"},
        enabled_parameter_families={
            "selectors.thread",
            "writes.content",
            "confirm.live",
        },
    )

    server = _CaptureServer()
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    register_tools(server, policy, RuntimeBundle(transport=transport))

    assert set(server.tools) == {
        mcp_tool_name("threads.read"),
        mcp_tool_name("posts.reply"),
    }


def test_dispatcher_excludes_disabled_capabilities_even_when_registry_contains_rows() -> (
    None
):
    policy = _policy(
        enabled_capabilities={"threads.read"},
        enabled_parameter_families={"selectors.thread"},
    )

    server = _CaptureServer()
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    register_tools(server, policy, RuntimeBundle(transport=transport))

    assert mcp_tool_name("threads.read") in server.tools
    assert mcp_tool_name("posts.reply") not in server.tools
    assert mcp_tool_name("admin.high_risk.write") not in server.tools


def test_annotations_are_remote_and_operation_honest() -> None:
    policy = _policy(
        enabled_capabilities={"threads.read", "posts.reply"},
        enabled_parameter_families={
            "selectors.thread",
            "writes.content",
            "confirm.live",
        },
    )

    server = _CaptureServer()
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    register_tools(server, policy, RuntimeBundle(transport=transport))
    assert list(server.tools) == [
        mcp_tool_name("threads.read"),
        mcp_tool_name("posts.reply"),
    ]

    read_tool = server.tools[mcp_tool_name("threads.read")]
    assert read_tool["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    assert read_tool["output_schema"] == {
        "type": "object",
        "additionalProperties": True,
    }

    write_tool = server.tools[mcp_tool_name("posts.reply")]
    assert write_tool["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
    assert write_tool["output_schema"] is None


def test_annotations_mark_local_draft_tools_truthfully() -> None:
    policy = _policy(
        enabled_capabilities={"formatting.preflight", "drafts.read", "drafts.write"},
        enabled_parameter_families={
            "formatting.content",
            "drafts.selector",
            "drafts.filters",
            "drafts.metadata",
            "drafts.confirm_delete",
        },
    )

    server = _CaptureServer()
    register_tools(server, policy, RuntimeBundle())

    def flags(name: str) -> tuple[bool, bool, bool, bool]:
        annotations = server.tools[mcp_tool_name(name)]["annotations"]
        assert "_meta" not in annotations
        return (
            annotations["readOnlyHint"],
            annotations["destructiveHint"],
            annotations["idempotentHint"],
            annotations["openWorldHint"],
        )

    assert flags("drafts.list") == (True, False, True, False)
    assert flags("drafts.read") == (True, False, True, False)
    assert flags("formatting.preflight") == (False, False, False, False)
    assert flags("drafts.update") == (False, False, False, False)
    assert flags("drafts.delete") == (False, True, False, False)


def test_create_server_uses_dispatcher_as_single_registration_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )

    monkeypatch.setattr(
        "hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle()
    )
    server = create_server(settings)

    assert hasattr(server, "tools")
    assert set(server.tools) == {mcp_tool_name("threads.read")}


def test_create_server_full_api_registers_extended_reads_concretely_and_omits_placeholder_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HFMCPSettings(
        profile="full_api",
        enabled_capabilities=PRESET_CAPABILITIES["full_api"],
        enabled_parameter_families=PRESET_PARAMETER_FAMILIES["full_api"],
    )

    monkeypatch.setattr(
        "hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle()
    )
    server = create_server(settings)

    assert "transport.read" not in server.tools
    assert "transport.write" not in server.tools

    concrete_read_rows = (
        "bytes.read",
        "contracts.read",
        "disputes.read",
        "bratings.read",
        "sigmarket.market.read",
        "sigmarket.order.read",
        "admin.high_risk.read",
    )
    for name in concrete_read_rows:
        public_name = mcp_tool_name(name)
        assert public_name in server.tools
        _assert_not_placeholder_handler(server.tools[public_name].handler)

    omitted_write_rows = (
        "contracts.write",
        "sigmarket.write",
        "admin.high_risk.write",
    )
    for name in omitted_write_rows:
        public_name = mcp_tool_name(name)
        assert public_name not in server.tools

    contracts_schema = server.tools[mcp_tool_name("contracts.read")].input_schema
    disputes_schema = server.tools[mcp_tool_name("disputes.read")].input_schema
    bratings_schema = server.tools[mcp_tool_name("bratings.read")].input_schema
    market_schema = server.tools[mcp_tool_name("sigmarket.market.read")].input_schema
    orders_schema = server.tools[mcp_tool_name("sigmarket.order.read")].input_schema

    for schema in (
        contracts_schema,
        disputes_schema,
        bratings_schema,
        market_schema,
        orders_schema,
    ):
        assert schema["properties"]["page"]["default"] == 1
        assert schema["properties"]["per_page"]["default"] == 30
        assert "required" not in schema

    assert "cid" in contracts_schema["properties"]
    assert "uid" in contracts_schema["properties"]
    assert "contract_id" not in contracts_schema["properties"]

    assert "cdid" in disputes_schema["properties"]
    assert "uid" in disputes_schema["properties"]
    assert "did" not in disputes_schema["properties"]
    assert "dispute_id" not in disputes_schema["properties"]

    assert "uid" in market_schema["properties"]
    assert "listing_id" not in market_schema["properties"]

    assert "oid" in orders_schema["properties"]
    assert "uid" in orders_schema["properties"]
    assert "listing_id" not in orders_schema["properties"]


def test_documented_write_specs_omit_unproven_later_lane_writes() -> None:
    specs = get_specs("write")
    assert {spec.name for spec in specs} == {
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
    }


def test_core_and_extended_read_rows_register_concrete_handlers_when_transport_is_available() -> (
    None
):
    policy = _policy(
        enabled_capabilities={"me.read", "bytes.read"},
        enabled_parameter_families={
            "selectors.user",
            "fields.me.basic",
            "selectors.bytes",
            "fields.bytes.amount",
        },
    )
    server = _CaptureServer()
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )

    register_tools(server, policy, RuntimeBundle(transport=transport))

    me_handler = server.tools[mcp_tool_name("me.read")]["handler"]
    bytes_handler = server.tools[mcp_tool_name("bytes.read")]["handler"]
    _assert_not_placeholder_handler(me_handler)
    _assert_not_placeholder_handler(bytes_handler)


def test_create_server_publishes_truthful_core_read_input_schemas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"me.read", "threads.read", "posts.read"}),
        enabled_parameter_families=frozenset(
            {
                "selectors.user",
                "selectors.forum",
                "selectors.thread",
                "selectors.post",
                "filters.pagination",
                "fields.me.basic",
                "fields.me.advanced",
                "fields.posts.body",
                "output.options",
            }
        ),
    )

    monkeypatch.setattr(
        "hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle()
    )
    server = create_server(settings)

    me_schema = server.tools[mcp_tool_name("me.read")].input_schema
    threads_schema = server.tools[mcp_tool_name("threads.read")].input_schema
    posts_schema = server.tools[mcp_tool_name("posts.read")].input_schema

    assert "uid" not in me_schema["properties"]
    assert "uid" not in me_schema.get("required", [])
    assert me_schema["properties"]["include_basic_fields"]["default"] is True
    assert me_schema["properties"]["include_advanced_fields"]["default"] is False
    assert set(me_schema["properties"]["output_mode"]["enum"]) == {
        "readable",
        "structured",
        "raw",
    }
    assert me_schema["properties"]["output_mode"]["default"] == "readable"
    assert me_schema["properties"]["include_raw_payload"]["default"] is False
    assert me_schema["properties"]["body_format"]["default"] == "markdown"
    assert set(me_schema["properties"]["body_format"]["enum"]) == {
        "raw",
        "clean",
        "markdown",
    }

    assert threads_schema["properties"]["page"]["default"] == 1
    assert threads_schema["properties"]["per_page"]["default"] == 30
    assert set(threads_schema["properties"]["output_mode"]["enum"]) == {
        "readable",
        "structured",
        "raw",
    }
    assert threads_schema["properties"]["output_mode"]["default"] == "readable"
    assert threads_schema["properties"]["include_raw_payload"]["default"] is False
    assert threads_schema["properties"]["body_format"]["default"] == "markdown"
    assert threads_schema.get("required", []) == []
    assert {tuple(item["required"]) for item in threads_schema.get("anyOf", [])} == {
        ("fid",),
        ("tid",),
        ("uid",),
    }

    assert posts_schema["properties"]["page"]["default"] == 1
    assert posts_schema["properties"]["per_page"]["default"] == 30
    assert posts_schema["properties"]["include_post_body"]["default"] is True
    assert set(posts_schema["properties"]["output_mode"]["enum"]) == {
        "readable",
        "structured",
        "raw",
    }
    assert posts_schema["properties"]["include_raw_payload"]["type"] == "boolean"
    assert set(posts_schema["properties"]["body_format"]["enum"]) == {
        "raw",
        "clean",
        "markdown",
    }
    assert posts_schema.get("required", []) == []
    assert {tuple(item["required"]) for item in posts_schema.get("anyOf", [])} == {
        ("pid",),
        ("tid",),
        ("uid",),
    }

    assert server.tools[mcp_tool_name("me.read")].output_schema is not None
    assert server.tools[mcp_tool_name("threads.read")].output_schema is not None
    assert server.tools[mcp_tool_name("posts.read")].output_schema is not None


def test_core_write_rows_register_concrete_handlers_and_omit_placeholder_rows() -> None:
    policy = _policy(
        enabled_capabilities={
            "threads.create",
            "posts.reply",
            "bytes.transfer",
            "bytes.deposit",
            "bytes.withdraw",
            "bytes.bump",
            "contracts.write",
            "sigmarket.write",
            "admin.high_risk.write",
        },
        enabled_parameter_families={
            "selectors.forum",
            "selectors.thread",
            "selectors.bytes",
            "selectors.contract",
            "selectors.sigmarket",
            "writes.content",
            "writes.bytes",
            "confirm.live",
        },
    )
    server = _CaptureServer()
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )

    register_tools(server, policy, RuntimeBundle(transport=transport))

    for name in [
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
    ]:
        _assert_not_placeholder_handler(server.tools[mcp_tool_name(name)]["handler"])
    assert mcp_tool_name("contracts.write") not in server.tools
    assert mcp_tool_name("sigmarket.write") not in server.tools
    assert mcp_tool_name("admin.high_risk.write") not in server.tools


def test_register_tools_passes_runtime_draft_dir_into_write_handlers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(
        enabled_capabilities={"threads.read"},
        enabled_parameter_families={"selectors.thread"},
    )
    server = _CaptureServer()
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    runtime = RuntimeBundle(
        transport=transport,
        settings=HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset({"threads.read"}),
            enabled_parameter_families=frozenset({"selectors.thread"}),
            draft_dir=tmp_path,
        ),
    )
    captured: dict[str, object] = {}

    def _fake_build_write_handlers(
        policy_arg: CapabilityPolicy,
        transport_arg: HFTransport,
        *,
        draft_dir: Path | str | None = None,
    ) -> dict[str, Any]:
        captured["policy"] = policy_arg
        captured["transport"] = transport_arg
        captured["draft_dir"] = draft_dir
        return {}

    monkeypatch.setattr(
        "hf_mcp.dispatcher.build_write_handlers", _fake_build_write_handlers
    )
    register_tools(server, policy, runtime)

    assert captured["policy"] is policy
    assert captured["transport"] is transport
    assert captured["draft_dir"] == tmp_path


def test_register_tools_omits_remote_rows_when_runtime_bundle_has_no_transport() -> (
    None
):
    policy = _policy(
        enabled_capabilities={"threads.read", "posts.reply"},
        enabled_parameter_families={
            "selectors.thread",
            "writes.content",
            "confirm.live",
        },
    )
    server = _CaptureServer()
    register_tools(server, policy, RuntimeBundle())

    assert mcp_tool_name("threads.read") not in server.tools
    assert mcp_tool_name("posts.reply") not in server.tools


def test_formatting_preflight_registers_local_handler_without_transport(
    tmp_path: Path,
) -> None:
    policy = _policy(
        enabled_capabilities={"formatting.preflight"},
        enabled_parameter_families={"formatting.content"},
    )
    server = _CaptureServer()
    runtime = RuntimeBundle(
        settings=HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset({"formatting.preflight"}),
            enabled_parameter_families=frozenset({"formatting.content"}),
            draft_dir=tmp_path,
        )
    )

    register_tools(server, policy, runtime)

    tool = server.tools[mcp_tool_name("formatting.preflight")]
    assert tool["handler"].__name__ == "_preflight_handler"
    assert tool["annotations"]["readOnlyHint"] is False
    assert tool["annotations"]["destructiveHint"] is False
    assert set(tool["input_schema"]["properties"]) == {
        "message",
        "source_path",
        "message_format",
    }
    assert tool["input_schema"]["anyOf"] == [
        {"required": ["message"]},
        {"required": ["source_path"]},
    ]
    result = tool["handler"](
        message='```json\n{"tool":"posts.reply"}\n```', message_format="markdown"
    )
    assert result["structuredContent"]["draft_id"]
    assert result["structuredContent"]["path"].endswith(".json")
    assert result["structuredContent"]["integrity"] < 1.0
    assert any(
        issue["code"] == "json_code_block_lossy_medium"
        for issue in result["structuredContent"]["issues"]
    )


def test_dispatcher_registers_concrete_local_draft_handlers_without_transport(
    tmp_path: Path,
) -> None:
    capabilities = {"formatting.preflight", "drafts.read", "drafts.write"}
    families = {
        "formatting.content",
        "drafts.selector",
        "drafts.filters",
        "drafts.metadata",
        "drafts.confirm_delete",
    }
    policy = _policy(
        enabled_capabilities=capabilities,
        enabled_parameter_families=families,
    )
    runtime = RuntimeBundle(
        settings=HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset(capabilities),
            enabled_parameter_families=frozenset(families),
            draft_dir=tmp_path,
        )
    )
    server = _CaptureServer()

    register_tools(server, policy, runtime)

    for tool_name in ("drafts.list", "drafts.read", "drafts.update", "drafts.delete"):
        _assert_not_placeholder_handler(
            server.tools[mcp_tool_name(tool_name)]["handler"]
        )

    preflight = server.tools[mcp_tool_name("formatting.preflight")]["handler"]
    created = preflight(message="Local draft body", message_format="markdown")
    draft_id = created["structuredContent"]["draft_id"]

    list_tool = server.tools[mcp_tool_name("drafts.list")]["handler"]
    listed = list_tool(limit=10, offset=0)
    assert listed["count"] >= 1
    assert any(
        item["draft_id"] == draft_id for item in listed["structuredContent"]["drafts"]
    )

    read_tool = server.tools[mcp_tool_name("drafts.read")]["handler"]
    read_result = read_tool(draft_id=draft_id)
    assert read_result["structuredContent"]["draft_id"] == draft_id

    update_tool = server.tools[mcp_tool_name("drafts.update")]["handler"]
    updated = update_tool(draft_id=draft_id, title="Updated title", status="ready")
    assert updated["structuredContent"]["metadata"]["title"] == "Updated title"
    assert updated["structuredContent"]["metadata"]["status"] == "ready"
    assert updated["structuredContent"]["draft_id"] == draft_id

    delete_tool = server.tools[mcp_tool_name("drafts.delete")]["handler"]
    with pytest.raises(ValueError, match="confirm_delete=True"):
        delete_tool(draft_id=draft_id)

    deleted = delete_tool(draft_id=draft_id, confirm_delete=True)
    assert deleted["structuredContent"]["deleted"] is True
    assert deleted["structuredContent"]["draft_id"] == draft_id


def test_forums_index_registers_local_handler_without_transport_and_keeps_structured_content_contract() -> (
    None
):
    policy = _policy(
        enabled_capabilities={"forums.read"},
        enabled_parameter_families={"selectors.forum", "filters.pagination"},
    )
    server = _CaptureServer()

    register_tools(server, policy, RuntimeBundle())

    assert mcp_tool_name("forums.index") in server.tools
    assert mcp_tool_name("forums.read") not in server.tools
    tool = server.tools[mcp_tool_name("forums.index")]
    assert tool["annotations"]["readOnlyHint"] is True
    assert "_meta" not in tool["annotations"]
    assert tool["annotations"]["openWorldHint"] is False

    result = tool["handler"]()
    assert isinstance(result, dict)
    assert isinstance(result.get("content"), list)
    assert isinstance(result.get("structuredContent"), dict)
    assert "_hf_flow" in result["structuredContent"]
    assert isinstance(result["structuredContent"]["_hf_flow"].get("next_actions"), list)


def test_dispatcher_extended_read_handler_includes_hf_flow_structured_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_read(
        self: HFTransport, *, asks: dict[str, Any], helper: str
    ) -> dict[str, Any]:
        del asks
        assert helper == "sigmarket/order"
        return {"sigmarket/order": [{"smid": "17", "buyer": "2047020", "seller": "1"}]}

    monkeypatch.setattr(HFTransport, "read", _fake_read)

    policy = _policy(
        enabled_capabilities={"sigmarket.order.read"},
        enabled_parameter_families={"selectors.sigmarket", "filters.pagination"},
    )
    server = _CaptureServer()
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    register_tools(server, policy, RuntimeBundle(transport=transport))

    tool = server.tools[mcp_tool_name("sigmarket.order.read")]
    assert tool["output_schema"] == {"type": "object", "additionalProperties": True}
    result = tool["handler"](oid=17)
    assert "_hf_flow" in result["structuredContent"]
    assert (
        result["structuredContent"]["_hf_flow"]["entry_tool"] == "sigmarket.order.read"
    )
    assert isinstance(result["structuredContent"]["_hf_flow"]["next_actions"], list)


def test_dispatcher_publishes_truthful_core_write_input_schemas() -> None:
    policy = _policy(
        enabled_capabilities={
            "threads.create",
            "posts.reply",
            "bytes.transfer",
            "bytes.deposit",
            "bytes.withdraw",
            "bytes.bump",
        },
        enabled_parameter_families={
            "selectors.forum",
            "selectors.thread",
            "selectors.bytes",
            "writes.content",
            "writes.bytes",
            "confirm.live",
        },
    )
    server = _CaptureServer()
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )

    register_tools(server, policy, RuntimeBundle(transport=transport))

    expected_parameter_names: dict[str, set[str]] = {
        "threads.create": {
            "fid",
            "subject",
            "message",
            "draft_id",
            "draft_path",
            "message_format",
            "confirm_live",
        },
        "posts.reply": {
            "tid",
            "message",
            "draft_id",
            "draft_path",
            "message_format",
            "confirm_live",
        },
        "bytes.transfer": {"target_uid", "amount", "confirm_live"},
        "bytes.deposit": {"amount", "confirm_live"},
        "bytes.withdraw": {"amount", "confirm_live"},
        "bytes.bump": {"tid", "confirm_live"},
    }

    for tool_name, expected_names in expected_parameter_names.items():
        schema = server.tools[mcp_tool_name(tool_name)]["input_schema"]
        assert set(schema["properties"].keys()) == expected_names


def test_register_tools_does_not_perform_implicit_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(
        enabled_capabilities={"threads.read"},
        enabled_parameter_families={"selectors.thread"},
    )
    server = _CaptureServer()

    def _fail_load_token_store(*_: object, **__: object) -> object:
        raise AssertionError("register_tools must not call load_token_store implicitly")

    monkeypatch.setattr("hf_mcp.dispatcher.load_token_store", _fail_load_token_store)
    register_tools(server, policy, RuntimeBundle())

    assert server.tools == {}


def test_create_server_fails_closed_when_runtime_secrets_are_missing() -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )

    with pytest.raises(
        ValueError, match="Missing required environment variable: HF_MCP_CLIENT_ID"
    ):
        create_server(settings)


def test_create_server_fails_closed_when_token_bundle_is_missing(
    tmp_path: Path,
) -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
        token_path=tmp_path / "token.json",
        runtime_env={
            "HF_MCP_CLIENT_ID": "client",
            "HF_MCP_CLIENT_SECRET": "secret",
            "HF_MCP_TOKEN_PATH": str((tmp_path / "token.json").resolve()),
        },
    )

    with pytest.raises(RuntimeError, match="No usable Hack Forums access token"):
        create_server(settings)


def test_serve_stdio_fails_closed_when_token_bundle_is_missing(tmp_path: Path) -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
        token_path=tmp_path / "token.json",
        runtime_env={
            "HF_MCP_CLIENT_ID": "client",
            "HF_MCP_CLIENT_SECRET": "secret",
            "HF_MCP_TOKEN_PATH": str((tmp_path / "token.json").resolve()),
        },
    )

    with pytest.raises(RuntimeError, match="No usable Hack Forums access token"):
        serve_stdio(settings)


def test_serve_stdio_publishes_dispatcher_contract_for_live_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.mcpserver import MCPServer

    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset(
            {
                "me.read",
                "threads.read",
                "posts.read",
                "posts.reply",
                "bytes.transfer",
                "bytes.deposit",
                "bytes.withdraw",
                "bytes.bump",
                "contracts.read",
                "disputes.read",
                "bratings.read",
                "sigmarket.market.read",
                "sigmarket.order.read",
            }
        ),
        enabled_parameter_families=frozenset(
            {
                "selectors.user",
                "selectors.forum",
                "selectors.thread",
                "selectors.post",
                "filters.pagination",
                "fields.me.basic",
                "fields.me.advanced",
                "fields.posts.body",
                "selectors.bytes",
                "selectors.contract",
                "selectors.dispute",
                "selectors.sigmarket",
                "writes.bytes",
                "writes.content",
                "confirm.live",
                "output.options",
            }
        ),
    )

    class _FakeFastMCP:
        instances: list["_FakeFastMCP"] = []

        def __init__(self, name: str, version: str = "") -> None:
            self.name = name
            self.version = version
            self._tool_manager = MCPServer(name=name)._tool_manager
            self.registered_tools: dict[str, dict[str, Any]] = {}
            self.run_calls: list[str] = []
            _FakeFastMCP.instances.append(self)

        def add_tool(
            self,
            handler: Any,
            *,
            name: str,
            description: str,
            annotations: object | None = None,
            meta: dict[str, object] | None = None,
            output_schema: dict[str, object] | None = None,
            **_: object,
        ) -> None:
            self._tool_manager.add_tool(
                handler,
                name=name,
                description=description,
                annotations=annotations,
                meta=meta,
            )
            self.registered_tools[name] = {
                "handler": handler,
                "description": description,
                "annotations": annotations,
                "meta": meta,
                "output_schema": output_schema,
            }

        def run(self, *, transport: str) -> None:
            self.run_calls.append(transport)

    monkeypatch.setattr(
        "hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle()
    )
    monkeypatch.setattr("hf_mcp.server._load_mcpserver_class", lambda: _FakeFastMCP)

    expected_server = create_server(settings)
    serve_stdio(settings)

    assert len(_FakeFastMCP.instances) == 1
    app = _FakeFastMCP.instances[0]
    assert app.run_calls == ["stdio"]
    assert app.version == hf_mcp.__version__

    for tool_name in (
        "me.read",
        "threads.read",
        "posts.read",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
        "contracts.read",
    ):
        public_tool_name = mcp_tool_name(tool_name)
        expected_tool = expected_server.tools[public_tool_name]
        published = app.registered_tools[public_tool_name]
        _assert_not_placeholder_handler(published["handler"])
        assert published["handler"].__name__ == f"{public_tool_name}_handler"
        published_signature = inspect.signature(published["handler"])
        published_parameters = tuple(published_signature.parameters.values())
        expected_parameter_names = tuple(
            expected_tool.input_schema.get("properties", {}).keys()
        )

        assert (
            tuple(parameter.name for parameter in published_parameters)
            == expected_parameter_names
        )
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in published_parameters
        )
        assert "kwargs" not in published_signature.parameters

        published_annotations = published["annotations"]
        if hasattr(published_annotations, "model_dump"):
            published_annotations = published_annotations.model_dump(
                by_alias=True, exclude_none=True
            )
        assert published_annotations == expected_tool.annotations
        assert published["meta"] is None
        assert published["output_schema"] == expected_tool.output_schema

    assert mcp_tool_name("contracts.write") not in app.registered_tools
    assert mcp_tool_name("sigmarket.write") not in app.registered_tools
    assert mcp_tool_name("admin.high_risk.write") not in app.registered_tools
    assert len(
        {tool["handler"].__name__ for tool in app.registered_tools.values()}
    ) == len(app.registered_tools)

    me_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("me.read")]["handler"]
    )
    assert "uid" not in me_signature.parameters
    assert me_signature.parameters["include_basic_fields"].default is True
    assert me_signature.parameters["include_advanced_fields"].default is False
    assert me_signature.parameters["output_mode"].default is None
    assert me_signature.parameters["include_raw_payload"].default is None
    assert me_signature.parameters["body_format"].default is None

    threads_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("threads.read")]["handler"]
    )
    assert threads_signature.parameters["fid"].default is None
    assert threads_signature.parameters["tid"].default is None
    assert threads_signature.parameters["uid"].default is None
    assert threads_signature.parameters["page"].default == 1
    assert threads_signature.parameters["per_page"].default == 30
    assert threads_signature.parameters["output_mode"].default is None
    assert threads_signature.parameters["include_raw_payload"].default is None
    assert threads_signature.parameters["body_format"].default is None

    posts_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("posts.read")]["handler"]
    )
    assert posts_signature.parameters["tid"].default is None
    assert posts_signature.parameters["pid"].default is None
    assert posts_signature.parameters["uid"].default is None
    assert posts_signature.parameters["page"].default == 1
    assert posts_signature.parameters["per_page"].default == 30
    assert posts_signature.parameters["include_post_body"].default is True
    assert posts_signature.parameters["output_mode"].default is None
    assert posts_signature.parameters["include_raw_payload"].default is None
    assert posts_signature.parameters["body_format"].default is None

    reply_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("posts.reply")]["handler"]
    )
    assert set(reply_signature.parameters.keys()) == {
        "tid",
        "message",
        "message_format",
        "draft_id",
        "draft_path",
        "confirm_live",
    }
    assert reply_signature.parameters["message_format"].default == "mycode"
    assert "subject" not in reply_signature.parameters

    transfer_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("bytes.transfer")]["handler"]
    )
    assert set(transfer_signature.parameters.keys()) == {
        "target_uid",
        "amount",
        "confirm_live",
    }
    assert "note" not in transfer_signature.parameters

    deposit_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("bytes.deposit")]["handler"]
    )
    assert set(deposit_signature.parameters.keys()) == {"amount", "confirm_live"}
    assert "target_uid" not in deposit_signature.parameters
    assert "note" not in deposit_signature.parameters

    withdraw_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("bytes.withdraw")]["handler"]
    )
    assert set(withdraw_signature.parameters.keys()) == {"amount", "confirm_live"}
    assert "target_uid" not in withdraw_signature.parameters
    assert "note" not in withdraw_signature.parameters

    bump_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("bytes.bump")]["handler"]
    )
    assert set(bump_signature.parameters.keys()) == {"confirm_live", "tid"}
    assert "target_uid" not in bump_signature.parameters
    assert "amount" not in bump_signature.parameters
    assert "note" not in bump_signature.parameters

    contracts_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("contracts.read")]["handler"]
    )
    assert contracts_signature.parameters["cid"].default is None
    assert contracts_signature.parameters["uid"].default is None
    assert contracts_signature.parameters["page"].default == 1
    assert contracts_signature.parameters["per_page"].default == 30
    assert "contract_id" not in contracts_signature.parameters

    disputes_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("disputes.read")]["handler"]
    )
    assert disputes_signature.parameters["cdid"].default is None
    assert disputes_signature.parameters["uid"].default is None
    assert disputes_signature.parameters["page"].default == 1
    assert disputes_signature.parameters["per_page"].default == 30
    assert "did" not in disputes_signature.parameters
    assert "dispute_id" not in disputes_signature.parameters

    bratings_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("bratings.read")]["handler"]
    )
    assert bratings_signature.parameters["uid"].default is None
    assert bratings_signature.parameters["page"].default == 1
    assert bratings_signature.parameters["per_page"].default == 30

    market_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("sigmarket.market.read")]["handler"]
    )
    assert market_signature.parameters["uid"].default is None
    assert market_signature.parameters["page"].default == 1
    assert market_signature.parameters["per_page"].default == 30
    assert "listing_id" not in market_signature.parameters

    order_signature = inspect.signature(
        app.registered_tools[mcp_tool_name("sigmarket.order.read")]["handler"]
    )
    assert order_signature.parameters["oid"].default is None
    assert order_signature.parameters["uid"].default is None
    assert order_signature.parameters["page"].default == 1
    assert order_signature.parameters["per_page"].default == 30
    assert "listing_id" not in order_signature.parameters


def test_serve_stdio_runs_stdio_runtime_once_without_restart_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.mcpserver import MCPServer

    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )

    run_calls: list[str] = []
    registered_names: list[str] = []

    class _FakeFastMCP:
        def __init__(self, name: str, version: str = "") -> None:
            self.name = name
            self._tool_manager = MCPServer(name=name)._tool_manager

        def add_tool(
            self,
            handler: Any,
            *,
            name: str,
            description: str,
            annotations: object | None = None,
            meta: dict[str, object] | None = None,
        ) -> None:
            self._tool_manager.add_tool(
                handler,
                name=name,
                description=description,
                annotations=annotations,
                meta=meta,
            )
            del handler
            registered_names.append(name)
            del description
            del annotations
            del meta

        def run(self, *, transport: str) -> None:
            run_calls.append(transport)

    monkeypatch.setattr(
        "hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle()
    )
    monkeypatch.setattr("hf_mcp.server._load_mcpserver_class", lambda: _FakeFastMCP)

    serve_stdio(settings)

    assert run_calls == ["stdio"]
    assert registered_names == [mcp_tool_name("threads.read")]


def test_serve_stdio_does_not_retry_when_stdio_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp.server.mcpserver import MCPServer

    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )

    run_calls: list[str] = []

    class _FakeFastMCP:
        def __init__(self, name: str, version: str = "") -> None:
            self.name = name
            self._tool_manager = MCPServer(name=name)._tool_manager

        def add_tool(
            self,
            handler: Any,
            *,
            name: str,
            description: str,
            annotations: object | None = None,
            meta: dict[str, object] | None = None,
        ) -> None:
            self._tool_manager.add_tool(
                handler,
                name=name,
                description=description,
                annotations=annotations,
                meta=meta,
            )
            del handler
            del name
            del description
            del annotations
            del meta

        def run(self, *, transport: str) -> None:
            run_calls.append(transport)
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr(
        "hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle()
    )
    monkeypatch.setattr("hf_mcp.server._load_mcpserver_class", lambda: _FakeFastMCP)

    with pytest.raises(ValueError, match="closed file"):
        serve_stdio(settings)
    assert run_calls == ["stdio"]


def test_runtime_stdio_client_session_returns_error_v1_for_failed_read_and_write() -> (
    None
):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server_probe = """
import email.message
import io
import urllib.error
import hf_mcp.transport as hf_transport
from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings, PRESET_PARAMETER_FAMILIES
from hf_mcp.dispatcher import RuntimeBundle, register_tools
from hf_mcp.server import _MCPServerToolAdapter
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport
from mcp.server.mcpserver import MCPServer

class _ProbeTokenStore:
    def require_bundle(self):
        return TokenBundle(access_token="TOKENSEED", token_type="Bearer", scope=frozenset({"read"}))

class _FailingOpener:
    def open(self, request, timeout=None):
        if request.full_url.endswith("/write"):
            raise TimeoutError("WRITESEED upstream text")
        headers = email.message.Message()
        headers["Retry-After"] = "7"
        raise urllib.error.HTTPError(
            request.full_url, 503, "unavailable", headers, io.BytesIO(b"BODYSEED upstream text")
        )

hf_transport._OPENER = _FailingOpener()
transport = HFTransport(token_store=_ProbeTokenStore(), base_url="https://example.test")
settings = HFMCPSettings(
    profile="test",
    enabled_capabilities=frozenset({"me.read", "posts.reply"}),
    enabled_parameter_families=PRESET_PARAMETER_FAMILIES["full_api"],
)
policy = CapabilityPolicy(settings)
app = MCPServer(name="hf-mcp-probe")
adapter = _MCPServerToolAdapter(app)
register_tools(adapter, policy, RuntimeBundle(transport=transport))
app.run(transport="stdio")
"""

    async def _run_probe() -> tuple[Any, Any]:
        env = dict(os.environ)
        pythonpath = env.get("PYTHONPATH")
        src_path = str(SRC_PATH)
        env["PYTHONPATH"] = f"{src_path}:{pythonpath}" if pythonpath else src_path
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", server_probe],
            env=env,
            cwd=str(PRODUCT_ROOT),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                read_result = await session.call_tool(
                    "me_read", {"output_mode": "raw", "include_raw_payload": True}
                )
                write_result = await session.call_tool(
                    "posts_reply",
                    {"tid": 123, "message": "Hello there", "confirm_live": True},
                )
                return read_result, write_result

    read_result, write_result = anyio.run(_run_probe)

    expected_fields = {
        "code",
        "operation",
        "tool",
        "message",
        "http_status",
        "retry_after",
        "retryable",
        "correlation_id",
        "mutation_outcome",
    }
    cases = (
        (
            read_result,
            "me_read",
            {
                "code": "UPSTREAM_UNAVAILABLE",
                "operation": "read",
                "http_status": 503,
                "retry_after": 7,
                "retryable": True,
                "mutation_outcome": "not_attempted",
            },
        ),
        (
            write_result,
            "posts_reply",
            {
                "code": "WRITE_OUTCOME_UNKNOWN",
                "operation": "write",
                "http_status": None,
                "retry_after": None,
                "retryable": False,
                "mutation_outcome": "unknown",
            },
        ),
    )
    for result, tool_name, expected in cases:
        assert result.is_error is True
        assert result.structured_content is not None
        assert set(result.structured_content) == {"error"}
        error = result.structured_content["error"]
        assert set(error) == expected_fields
        assert error["tool"] == tool_name
        for key, value in expected.items():
            assert error[key] == value
        assert [part.type for part in result.content] == ["text"]
        assert result.content[0].text == f"{error['code']}: {error['message']}"
        dumped = result.model_dump_json(by_alias=True)
        for seed in ("TOKENSEED", "BODYSEED", "WRITESEED", "example.test"):
            assert seed not in dumped


def _validation_error() -> Exception:
    from pydantic import BaseModel, ValidationError

    class _Arguments(BaseModel):
        count: int

    try:
        _Arguments(count="SECRETSEED")  # type: ignore[arg-type]
    except ValidationError as error:
        return error
    raise AssertionError("expected a validation error")


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            WritePreflightError("Write body contains nested code blocks."),
            "FORMAT_NOT_READY",
            "Write body contains nested code blocks.",
        ),
        (
            ValueError("tid must be positive."),
            "INVALID_ARGUMENT",
            "tid must be positive.",
        ),
        (
            PermissionError("Tool requires confirm_live=True."),
            "INVALID_ARGUMENT",
            "Tool requires confirm_live=True.",
        ),
        (
            TypeError("SECRETSEED bad type"),
            "INVALID_ARGUMENT",
            "The request arguments are invalid.",
        ),
        (
            _validation_error(),
            "INVALID_ARGUMENT",
            "Invalid arguments: count",
        ),
        (
            RuntimeError("SECRETSEED /path"),
            "INTERNAL_ERROR",
            "An internal error occurred.",
        ),
    ],
)
def test_wrapped_handler_maps_every_exception_to_error_v1(
    caplog: pytest.LogCaptureFixture,
    is_async: bool,
    error: Exception,
    code: str,
    message: str,
) -> None:
    import logging

    if is_async:

        async def handler() -> dict[str, Any]:
            raise error

    else:

        def handler() -> dict[str, Any]:  # type: ignore[misc]
            raise error

    wrapped = _with_schema_signature(
        "posts_reply", handler, {"type": "object", "properties": {}}
    )
    caplog.set_level(logging.DEBUG)
    result = anyio.run(wrapped) if is_async else wrapped()

    assert result.is_error is True
    assert set(result.structured_content) == {"error"}
    data = result.structured_content["error"]
    assert set(data) == {
        "code",
        "operation",
        "tool",
        "message",
        "http_status",
        "retry_after",
        "retryable",
        "correlation_id",
        "mutation_outcome",
    }
    assert (data["code"], data["tool"], data["message"]) == (
        code,
        "posts_reply",
        message,
    )
    assert (data["operation"], data["retryable"], data["mutation_outcome"]) == (
        "local",
        False,
        "not_attempted",
    )
    assert [part.type for part in result.content] == ["text"]
    assert result.content[0].text == f"{code}: {message}"
    assert "SECRETSEED" not in result.model_dump_json(by_alias=True)
    assert "SECRETSEED" not in caplog.text
