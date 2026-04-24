from __future__ import annotations

import json
import inspect
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings, PRESET_CAPABILITIES, PRESET_PARAMETER_FAMILIES
from hf_mcp.dispatcher import RuntimeBundle, register_tools
from hf_mcp.metadata import get_tool_specs
from hf_mcp.registry import mcp_tool_name
from hf_mcp.server import _FastMCPToolAdapter
from hf_mcp.server import create_server, serve_stdio
from hf_mcp.token_store import TokenBundle
from hf_mcp.tools.read_core import build_core_read_handlers
from hf_mcp.tools.read_extended import build_extended_read_handlers
from hf_mcp.transport import HFTransport


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
    def read(self, *, asks: dict[str, Any], helper: str) -> dict[str, Any]:
        del asks
        if helper == "me":
            return {"me": [{"uid": "5", "username": "forge"}]}
        if helper == "sigmarket/order":
            return {"sigmarket/order": [{"oid": "17", "uid": "5"}]}
        raise AssertionError(f"unexpected helper: {helper}")

    def read_raw(self, *, asks: dict[str, Any], helper: str) -> dict[str, Any]:
        del asks
        if helper == "me":
            return {"me": [{"uid": "5", "username": "forge", "raw": True}]}
        if helper == "sigmarket/order":
            return {"sigmarket/order": [{"oid": "17", "uid": "5", "raw": True}]}
        raise AssertionError(f"unexpected helper: {helper}")


def _runtime_bundle() -> RuntimeBundle:
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    return RuntimeBundle(
        transport=transport,
        auth_context=TokenBundle(access_token="token", token_type="Bearer", scope=frozenset({"read"})),
    )


def _policy(*, enabled_capabilities: set[str], enabled_parameter_families: set[str]) -> CapabilityPolicy:
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


def test_nested_envelope_json_in_text_content_is_rejected_by_validator() -> None:
    import mcp.types as mcp_types

    nested_json = json.dumps({"content": [{"type": "text", "text": "legacy"}], "structuredContent": {"me": []}})
    result = mcp_types.CallToolResult(
        content=[mcp_types.TextContent(type="text", text=nested_json)],
        structuredContent={"me": []},
    )

    with pytest.raises(AssertionError, match="Nested envelope JSON detected"):
        _assert_rejects_nested_envelope_json_text(result)


def test_fastmcp_adapter_converts_hf_envelope_dict_to_protocol_call_tool_result() -> None:
    import mcp.types as mcp_types

    class _FakeApp:
        def __init__(self) -> None:
            self._handler: Any | None = None

        def add_tool(
            self,
            handler: Any,
            *,
            name: str,
            description: str,
            annotations: object | None = None,
            structured_output: bool | None = None,
        ) -> None:
            del name
            del description
            del annotations
            del structured_output
            self._handler = handler

    envelope = {
        "content": [
            {"type": "text", "text": "me.read returned 1 row(s)."},
            {
                "type": "resource",
                "resource": {
                    "uri": "hf-mcp://raw/me.read",
                    "mimeType": "application/json",
                    "text": "{\"me\":[{\"uid\":\"5\"}]}",
                },
            },
        ],
        "structuredContent": {"me": [{"uid": "5"}]},
    }

    fake_app = _FakeApp()
    adapter = _FastMCPToolAdapter(fake_app)
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

    assert fake_app._handler is not None
    normalized = fake_app._handler()
    assert isinstance(normalized, mcp_types.CallToolResult)
    assert normalized.structuredContent == {"me": [{"uid": "5"}]}
    assert len(normalized.content) == 2
    assert isinstance(normalized.content[0], mcp_types.TextContent)
    assert isinstance(normalized.content[1], mcp_types.EmbeddedResource)
    assert str(normalized.content[1].resource.uri) == "hf-mcp://raw/me.read"


def test_runtime_stdio_client_session_returns_protocol_structured_content_and_raw_resource() -> None:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    server_probe = """
import sys
from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.dispatcher import RuntimeBundle, register_tools
from hf_mcp.server import _FastMCPToolAdapter
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport
from mcp.server.fastmcp import FastMCP

class _ProbeTokenStore:
    def require_bundle(self):
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset({"read"}))

def _stub_read(*, asks, helper):
    del asks
    if helper != "me":
        raise RuntimeError(f"unexpected helper: {helper}")
    return {"me": [{"uid": "5", "username": "forge"}]}

def _stub_read_raw(*, asks, helper):
    del asks
    if helper != "me":
        raise RuntimeError(f"unexpected helper: {helper}")
    return {"me": [{"uid": "5", "username": "forge", "raw": True}]}

transport = HFTransport(token_store=_ProbeTokenStore(), base_url="https://example.test")
transport.read = _stub_read
transport.read_raw = _stub_read_raw

settings = HFMCPSettings(
    profile="test",
    enabled_capabilities=frozenset({"me.read"}),
    enabled_parameter_families=frozenset({"fields.me.basic", "selectors.user"}),
)
policy = CapabilityPolicy(settings)
app = FastMCP(name="hf-mcp-probe")
adapter = _FastMCPToolAdapter(app)
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
        assert result.structuredContent is not None
        assert result.structuredContent["me"][0]["uid"] == "5"
        assert any(getattr(item, "type", None) == "resource" for item in result.content)
        _assert_rejects_nested_envelope_json_text(result)

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
    handler = build_extended_read_handlers(policy, _StubReadTransport())["sigmarket.order.read"]

    result = handler(oid=17, output_mode="raw", include_raw_payload=True)

    assert isinstance(result, dict)
    assert isinstance(result.get("content"), list)
    assert isinstance(result.get("structuredContent"), dict)
    assert "sigmarket/order" in result["structuredContent"]


def test_dispatcher_registers_only_policy_allowed_registry_rows() -> None:
    policy = _policy(
        enabled_capabilities={"threads.read", "posts.reply"},
        enabled_parameter_families={"selectors.thread", "writes.content", "confirm.live"},
    )

    server = _CaptureServer()
    register_tools(server, policy, RuntimeBundle())

    assert set(server.tools) == {mcp_tool_name("threads.read"), mcp_tool_name("posts.reply")}


def test_dispatcher_excludes_disabled_capabilities_even_when_registry_contains_rows() -> None:
    policy = _policy(
        enabled_capabilities={"threads.read"},
        enabled_parameter_families={"selectors.thread"},
    )

    server = _CaptureServer()
    register_tools(server, policy, RuntimeBundle())

    assert mcp_tool_name("threads.read") in server.tools
    assert mcp_tool_name("posts.reply") not in server.tools
    assert mcp_tool_name("admin.high_risk.write") not in server.tools


def test_metadata_and_annotations_are_remote_tier4_and_operation_honest() -> None:
    policy = _policy(
        enabled_capabilities={"threads.read", "posts.reply"},
        enabled_parameter_families={"selectors.thread", "writes.content", "confirm.live"},
    )

    specs = get_tool_specs(policy)
    assert [spec.tool_name for spec in specs] == ["threads.read", "posts.reply"]

    server = _CaptureServer()
    register_tools(server, policy, RuntimeBundle())

    read_annotations = server.tools[mcp_tool_name("threads.read")]["annotations"]
    assert read_annotations["readOnlyHint"] is True
    assert read_annotations["destructiveHint"] is False
    assert read_annotations["openWorldHint"] is True
    assert read_annotations["_meta"]["x-hf-locality"] == "remote"
    assert read_annotations["_meta"]["x-hf-runtime-tier"] == 4
    assert read_annotations["_meta"]["x-hf-operation"] == "read"
    assert read_annotations["_meta"]["x-hf-output-default"] == "readable"
    assert read_annotations["_meta"]["x-hf-output-readable"] == "additive"
    assert (
        read_annotations["_meta"]["x-hf-output-field-bundles"] == "separate_from_rendering"
    )
    assert server.tools[mcp_tool_name("threads.read")]["output_schema"] is not None

    write_annotations = server.tools[mcp_tool_name("posts.reply")]["annotations"]
    assert write_annotations["readOnlyHint"] is False
    assert write_annotations["destructiveHint"] is True
    assert write_annotations["openWorldHint"] is True
    assert write_annotations["_meta"]["x-hf-locality"] == "remote"
    assert write_annotations["_meta"]["x-hf-runtime-tier"] == 4
    assert write_annotations["_meta"]["x-hf-operation"] == "write"
    assert write_annotations["_meta"]["x-hf-output-default"] == "structured"
    assert write_annotations["_meta"]["x-hf-output-readable"] == "additive"
    assert (
        write_annotations["_meta"]["x-hf-output-field-bundles"] == "separate_from_rendering"
    )
    assert server.tools[mcp_tool_name("posts.reply")]["output_schema"] is None


def test_create_server_uses_dispatcher_as_single_registration_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )

    monkeypatch.setattr("hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle())
    server = create_server(settings)

    assert hasattr(server, "tools")
    assert set(server.tools) == {mcp_tool_name("threads.read")}


def test_create_server_full_api_registers_extended_reads_concretely_and_retains_write_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HFMCPSettings(
        profile="full_api",
        enabled_capabilities=PRESET_CAPABILITIES["full_api"],
        enabled_parameter_families=PRESET_PARAMETER_FAMILIES["full_api"],
    )

    monkeypatch.setattr("hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle())
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
        assert server.tools[public_name].handler.__name__ != "_handler"

    retained_write_rows = (
        "contracts.write",
        "sigmarket.write",
        "admin.high_risk.write",
    )
    for name in retained_write_rows:
        public_name = mcp_tool_name(name)
        assert public_name in server.tools
        assert server.tools[public_name].handler.__name__ == "_handler"

    contracts_schema = server.tools[mcp_tool_name("contracts.read")].input_schema
    disputes_schema = server.tools[mcp_tool_name("disputes.read")].input_schema
    bratings_schema = server.tools[mcp_tool_name("bratings.read")].input_schema
    market_schema = server.tools[mcp_tool_name("sigmarket.market.read")].input_schema
    orders_schema = server.tools[mcp_tool_name("sigmarket.order.read")].input_schema

    for schema in (contracts_schema, disputes_schema, bratings_schema, market_schema, orders_schema):
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


def test_core_and_extended_read_rows_register_concrete_handlers_when_transport_is_available() -> None:
    policy = _policy(
        enabled_capabilities={"me.read", "bytes.read"},
        enabled_parameter_families={"selectors.user", "fields.me.basic", "selectors.bytes", "fields.bytes.amount"},
    )
    server = _CaptureServer()
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    register_tools(server, policy, RuntimeBundle(transport=transport))

    me_handler = server.tools[mcp_tool_name("me.read")]["handler"]
    bytes_handler = server.tools[mcp_tool_name("bytes.read")]["handler"]
    assert me_handler.__name__ != "_handler"
    assert bytes_handler.__name__ != "_handler"


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
            }
        ),
    )

    monkeypatch.setattr("hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle())
    server = create_server(settings)

    me_schema = server.tools[mcp_tool_name("me.read")].input_schema
    threads_schema = server.tools[mcp_tool_name("threads.read")].input_schema
    posts_schema = server.tools[mcp_tool_name("posts.read")].input_schema

    assert "uid" not in me_schema["properties"]
    assert "uid" not in me_schema.get("required", [])
    assert me_schema["properties"]["include_basic_fields"]["default"] is True
    assert me_schema["properties"]["include_advanced_fields"]["default"] is False
    assert set(me_schema["properties"]["output_mode"]["enum"]) == {"readable", "structured", "raw"}
    assert me_schema["properties"]["output_mode"]["default"] == "readable"
    assert me_schema["properties"]["include_raw_payload"]["default"] is False

    assert threads_schema["properties"]["page"]["default"] == 1
    assert threads_schema["properties"]["per_page"]["default"] == 30
    assert set(threads_schema["properties"]["output_mode"]["enum"]) == {"readable", "structured", "raw"}
    assert threads_schema["properties"]["output_mode"]["default"] == "readable"
    assert threads_schema["properties"]["include_raw_payload"]["default"] is False
    assert set(threads_schema.get("required", [])) == {"fid"}

    assert posts_schema["properties"]["page"]["default"] == 1
    assert posts_schema["properties"]["per_page"]["default"] == 30
    assert posts_schema["properties"]["include_post_body"]["default"] is True
    assert set(posts_schema["properties"]["output_mode"]["enum"]) == {"readable", "structured", "raw"}
    assert posts_schema["properties"]["include_raw_payload"]["type"] == "boolean"
    assert set(posts_schema.get("required", [])) == {"tid"}

    assert server.tools[mcp_tool_name("me.read")].output_schema is not None
    assert server.tools[mcp_tool_name("threads.read")].output_schema is not None
    assert server.tools[mcp_tool_name("posts.read")].output_schema is not None


def test_core_write_rows_register_concrete_handlers_while_later_rows_remain_placeholders() -> None:
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
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    register_tools(server, policy, RuntimeBundle(transport=transport))

    for name in ["threads.create", "posts.reply", "bytes.transfer", "bytes.deposit", "bytes.withdraw", "bytes.bump"]:
        assert server.tools[mcp_tool_name(name)]["handler"].__name__ != "_handler"
    assert server.tools[mcp_tool_name("contracts.write")]["handler"].__name__ == "_handler"
    assert server.tools[mcp_tool_name("sigmarket.write")]["handler"].__name__ == "_handler"
    assert server.tools[mcp_tool_name("admin.high_risk.write")]["handler"].__name__ == "_handler"


def test_register_tools_uses_placeholder_handlers_when_runtime_bundle_has_no_transport() -> None:
    policy = _policy(
        enabled_capabilities={"threads.read", "posts.reply"},
        enabled_parameter_families={"selectors.thread", "writes.content", "confirm.live"},
    )
    server = _CaptureServer()
    register_tools(server, policy, RuntimeBundle())

    assert server.tools[mcp_tool_name("threads.read")]["handler"].__name__ == "_handler"
    assert server.tools[mcp_tool_name("posts.reply")]["handler"].__name__ == "_handler"


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
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    register_tools(server, policy, RuntimeBundle(transport=transport))

    expected_parameter_names: dict[str, set[str]] = {
        "threads.create": {"fid", "subject", "message", "confirm_live"},
        "posts.reply": {"tid", "message", "confirm_live"},
        "bytes.transfer": {"target_uid", "amount", "confirm_live"},
        "bytes.deposit": {"amount", "confirm_live"},
        "bytes.withdraw": {"amount", "confirm_live"},
        "bytes.bump": {"tid", "confirm_live"},
    }

    for tool_name, expected_names in expected_parameter_names.items():
        schema = server.tools[mcp_tool_name(tool_name)]["input_schema"]
        assert set(schema["properties"].keys()) == expected_names


def test_register_tools_does_not_perform_implicit_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _policy(
        enabled_capabilities={"threads.read"},
        enabled_parameter_families={"selectors.thread"},
    )
    server = _CaptureServer()

    def _fail_load_token_store(*_: object, **__: object) -> object:
        raise AssertionError("register_tools must not call load_token_store implicitly")

    monkeypatch.setattr("hf_mcp.dispatcher.load_token_store", _fail_load_token_store)
    register_tools(server, policy, RuntimeBundle())

    assert set(server.tools) == {mcp_tool_name("threads.read")}


def test_create_server_fails_closed_when_runtime_secrets_are_missing() -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )

    with pytest.raises(ValueError, match="Missing required environment variable: HF_MCP_CLIENT_ID"):
        create_server(settings)


def test_create_server_fails_closed_when_token_bundle_is_missing(tmp_path: Path) -> None:
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

    with pytest.raises(RuntimeError, match="No access token found"):
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

    with pytest.raises(RuntimeError, match="No access token found"):
        serve_stdio(settings)


def test_serve_stdio_publishes_dispatcher_contract_for_live_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                "contracts.write",
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
            }
        ),
    )

    class _FakeFastMCP:
        instances: list["_FakeFastMCP"] = []

        def __init__(self, name: str) -> None:
            self.name = name
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
            self.registered_tools[name] = {
                "handler": handler,
                "description": description,
                "annotations": annotations,
                "meta": meta,
                "output_schema": output_schema,
            }

        def run(self, *, transport: str) -> None:
            self.run_calls.append(transport)

    monkeypatch.setattr("hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle())
    monkeypatch.setattr("hf_mcp.server._load_fastmcp_class", lambda: _FakeFastMCP)

    expected_server = create_server(settings)
    serve_stdio(settings)

    assert len(_FakeFastMCP.instances) == 1
    app = _FakeFastMCP.instances[0]
    assert app.run_calls == ["stdio"]

    for tool_name in (
        "me.read",
        "threads.read",
        "posts.read",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
        "contracts.write",
    ):
        public_tool_name = mcp_tool_name(tool_name)
        expected_tool = expected_server.tools[public_tool_name]
        published = app.registered_tools[public_tool_name]
        published_signature = inspect.signature(published["handler"])
        published_parameters = tuple(published_signature.parameters.values())
        expected_parameter_names = tuple(expected_tool.input_schema.get("properties", {}).keys())

        assert tuple(parameter.name for parameter in published_parameters) == expected_parameter_names
        assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in published_parameters)
        assert "kwargs" not in published_signature.parameters

        published_annotations = published["annotations"]
        if hasattr(published_annotations, "model_dump"):
            published_annotations = published_annotations.model_dump(exclude_none=True)
        assert published_annotations == expected_tool.annotations
        assert published["output_schema"] == expected_tool.output_schema

    me_signature = inspect.signature(app.registered_tools[mcp_tool_name("me.read")]["handler"])
    assert "uid" not in me_signature.parameters
    assert me_signature.parameters["include_basic_fields"].default is True
    assert me_signature.parameters["include_advanced_fields"].default is False
    assert me_signature.parameters["output_mode"].default is None
    assert me_signature.parameters["include_raw_payload"].default is None

    threads_signature = inspect.signature(app.registered_tools[mcp_tool_name("threads.read")]["handler"])
    assert threads_signature.parameters["fid"].default is inspect.Parameter.empty
    assert threads_signature.parameters["tid"].default is None
    assert threads_signature.parameters["page"].default == 1
    assert threads_signature.parameters["per_page"].default == 30
    assert threads_signature.parameters["output_mode"].default is None
    assert threads_signature.parameters["include_raw_payload"].default is None

    posts_signature = inspect.signature(app.registered_tools[mcp_tool_name("posts.read")]["handler"])
    assert posts_signature.parameters["tid"].default is inspect.Parameter.empty
    assert posts_signature.parameters["pid"].default is None
    assert posts_signature.parameters["page"].default == 1
    assert posts_signature.parameters["per_page"].default == 30
    assert posts_signature.parameters["include_post_body"].default is True
    assert posts_signature.parameters["output_mode"].default is None
    assert posts_signature.parameters["include_raw_payload"].default is None

    reply_signature = inspect.signature(app.registered_tools[mcp_tool_name("posts.reply")]["handler"])
    assert set(reply_signature.parameters.keys()) == {"tid", "message", "confirm_live"}
    assert "subject" not in reply_signature.parameters

    transfer_signature = inspect.signature(app.registered_tools[mcp_tool_name("bytes.transfer")]["handler"])
    assert set(transfer_signature.parameters.keys()) == {"target_uid", "amount", "confirm_live"}
    assert "note" not in transfer_signature.parameters

    deposit_signature = inspect.signature(app.registered_tools[mcp_tool_name("bytes.deposit")]["handler"])
    assert set(deposit_signature.parameters.keys()) == {"amount", "confirm_live"}
    assert "target_uid" not in deposit_signature.parameters
    assert "note" not in deposit_signature.parameters

    withdraw_signature = inspect.signature(app.registered_tools[mcp_tool_name("bytes.withdraw")]["handler"])
    assert set(withdraw_signature.parameters.keys()) == {"amount", "confirm_live"}
    assert "target_uid" not in withdraw_signature.parameters
    assert "note" not in withdraw_signature.parameters

    bump_signature = inspect.signature(app.registered_tools[mcp_tool_name("bytes.bump")]["handler"])
    assert tuple(bump_signature.parameters.keys()) == ("confirm_live", "tid")
    assert "target_uid" not in bump_signature.parameters
    assert "amount" not in bump_signature.parameters
    assert "note" not in bump_signature.parameters

    contracts_signature = inspect.signature(app.registered_tools[mcp_tool_name("contracts.read")]["handler"])
    assert contracts_signature.parameters["cid"].default is None
    assert contracts_signature.parameters["uid"].default is None
    assert contracts_signature.parameters["page"].default == 1
    assert contracts_signature.parameters["per_page"].default == 30
    assert "contract_id" not in contracts_signature.parameters

    disputes_signature = inspect.signature(app.registered_tools[mcp_tool_name("disputes.read")]["handler"])
    assert disputes_signature.parameters["cdid"].default is None
    assert disputes_signature.parameters["uid"].default is None
    assert disputes_signature.parameters["page"].default == 1
    assert disputes_signature.parameters["per_page"].default == 30
    assert "did" not in disputes_signature.parameters
    assert "dispute_id" not in disputes_signature.parameters

    bratings_signature = inspect.signature(app.registered_tools[mcp_tool_name("bratings.read")]["handler"])
    assert bratings_signature.parameters["uid"].default is None
    assert bratings_signature.parameters["page"].default == 1
    assert bratings_signature.parameters["per_page"].default == 30

    market_signature = inspect.signature(app.registered_tools[mcp_tool_name("sigmarket.market.read")]["handler"])
    assert market_signature.parameters["uid"].default is None
    assert market_signature.parameters["page"].default == 1
    assert market_signature.parameters["per_page"].default == 30
    assert "listing_id" not in market_signature.parameters

    order_signature = inspect.signature(app.registered_tools[mcp_tool_name("sigmarket.order.read")]["handler"])
    assert order_signature.parameters["oid"].default is None
    assert order_signature.parameters["uid"].default is None
    assert order_signature.parameters["page"].default == 1
    assert order_signature.parameters["per_page"].default == 30
    assert "listing_id" not in order_signature.parameters


def test_serve_stdio_runs_stdio_runtime_once_without_restart_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )

    run_calls: list[str] = []
    registered_names: list[str] = []

    class _FakeFastMCP:
        def __init__(self, name: str) -> None:
            self.name = name

        def add_tool(
            self,
            handler: Any,
            *,
            name: str,
            description: str,
            annotations: object | None = None,
            meta: dict[str, object] | None = None,
        ) -> None:
            del handler
            registered_names.append(name)
            del description
            del annotations
            del meta

        def run(self, *, transport: str) -> None:
            run_calls.append(transport)

    monkeypatch.setattr("hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle())
    monkeypatch.setattr("hf_mcp.server._load_fastmcp_class", lambda: _FakeFastMCP)

    serve_stdio(settings)

    assert run_calls == ["stdio"]
    assert registered_names == [mcp_tool_name("threads.read")]


def test_serve_stdio_does_not_retry_when_stdio_is_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"threads.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
    )

    run_calls: list[str] = []

    class _FakeFastMCP:
        def __init__(self, name: str) -> None:
            self.name = name

        def add_tool(
            self,
            handler: Any,
            *,
            name: str,
            description: str,
            annotations: object | None = None,
            meta: dict[str, object] | None = None,
        ) -> None:
            del handler
            del name
            del description
            del annotations
            del meta

        def run(self, *, transport: str) -> None:
            run_calls.append(transport)
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr("hf_mcp.server.resolve_runtime_bundle", lambda _: _runtime_bundle())
    monkeypatch.setattr("hf_mcp.server._load_fastmcp_class", lambda: _FakeFastMCP)

    with pytest.raises(ValueError, match="closed file"):
        serve_stdio(settings)
    assert run_calls == ["stdio"]
