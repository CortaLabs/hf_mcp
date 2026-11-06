from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Awaitable, Callable
from functools import partial
from pathlib import Path
from typing import Any

import anyio
import mcp.types as types
import pytest
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

import hf_mcp
from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings, PRESET_CAPABILITIES, PRESET_PARAMETER_FAMILIES
from hf_mcp.dispatcher import Handler, build_handlers
from hf_mcp.registry import MAX_MESSAGE_CHARS, TOOLS, get_specs, mcp_tool_name
from hf_mcp.server import build_server, create_server, serve_stdio
from hf_mcp.token_store import TokenBundle
from hf_mcp.tools.read_core import build_core_read_handlers
from hf_mcp.tools.read_extended import build_extended_read_handlers
from hf_mcp.transport import HFAPIError, HFTransport, build_error
from hf_mcp.write_preflight import WritePreflightError

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
ERROR_V1_FIELDS = {
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


class _CountingTransport(HFTransport):
    """A real HFTransport whose network seam is a counter and a canned reply."""

    def __init__(self) -> None:
        super().__init__(token_store=_StubTokenStore(), base_url="https://example.test")
        self.calls = 0

    def _post_json(self, route: str, payload: Any, headers: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "posts": [{"pid": "1", "tid": "1", "uid": "5", "message": "hello"}],
            "threads": [{"tid": "1", "fid": "2", "subject": "s"}],
            "me": [{"uid": "5", "username": "forge"}],
        }


def _transport() -> HFTransport:
    return HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")


def _settings(
    capabilities: set[str] | frozenset[str],
    families: set[str] | frozenset[str],
    **extra: Any,
) -> HFMCPSettings:
    return HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset(capabilities),
        enabled_parameter_families=frozenset(families),
        **extra,
    )


def _preset_settings(profile: str) -> HFMCPSettings:
    return HFMCPSettings(
        profile=profile,
        enabled_capabilities=PRESET_CAPABILITIES[profile],
        enabled_parameter_families=PRESET_PARAMETER_FAMILIES[profile],
    )


def _policy(
    *, enabled_capabilities: set[str], enabled_parameter_families: set[str]
) -> CapabilityPolicy:
    return CapabilityPolicy(_settings(enabled_capabilities, enabled_parameter_families))


def _handlers(
    settings: HFMCPSettings, transport: HFTransport | None = None
) -> dict[str, Handler]:
    return build_handlers(CapabilityPolicy(settings), settings, transport)


def _server(
    settings: HFMCPSettings,
    transport: HFTransport | None = None,
    handlers: dict[str, Handler] | None = None,
) -> Any:
    policy = CapabilityPolicy(settings)
    return build_server(
        policy,
        handlers
        if handlers is not None
        else build_handlers(policy, settings, transport),
    )


def _session(server: Any, scenario: Callable[[Client], Awaitable[Any]]) -> Any:
    """Run ``scenario`` against ``server`` through the SDK's in-memory client."""

    async def _run() -> Any:
        async with Client(server) as client:
            return await scenario(client)

    return anyio.run(_run)


def _listed(
    settings: HFMCPSettings, transport: HFTransport | None = None
) -> dict[str, types.Tool]:
    async def scenario(client: Client) -> dict[str, types.Tool]:
        return {tool.name: tool for tool in (await client.list_tools()).tools}

    return _session(_server(settings, transport), scenario)


def _call(server: Any, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
    async def scenario(client: Client) -> types.CallToolResult:
        return await client.call_tool(name, arguments)

    return _session(server, scenario)


def _annotation_flags(tool: types.Tool) -> dict[str, bool]:
    assert tool.annotations is not None
    return tool.annotations.model_dump(by_alias=True, exclude_none=True)


def _counting(
    handlers: dict[str, Handler], counter: dict[str, int]
) -> dict[str, Handler]:
    def wrap(name: str, handler: Handler) -> Handler:
        def counted(**kwargs: Any) -> Any:
            counter[name] = counter.get(name, 0) + 1
            return handler(**kwargs)

        return counted

    return {name: wrap(name, handler) for name, handler in handlers.items()}


def _assert_error(
    result: types.CallToolResult, code: str, tool: str | None = None
) -> dict[str, Any]:
    assert result.is_error is True
    assert result.structured_content is not None
    assert set(result.structured_content) == {"error"}
    error = result.structured_content["error"]
    assert set(error) == ERROR_V1_FIELDS
    assert error["code"] == code
    if tool is not None:
        assert error["tool"] == tool
    assert [part.type for part in result.content] == ["text"]
    assert result.content[0].text == f"{error['code']}: {error['message']}"
    return error


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


# ---------------------------------------------------------------- registration


@pytest.mark.core
@pytest.mark.registry
def test_dispatcher_registers_only_policy_allowed_registry_rows() -> None:
    settings = _settings(
        {"threads.read", "posts.reply"},
        {"selectors.thread", "writes.content", "confirm.live"},
    )

    handlers = _handlers(settings, _transport())

    assert list(handlers) == ["threads.read", "posts.reply"]
    assert list(_listed(settings, _transport())) == [
        mcp_tool_name("threads.read"),
        mcp_tool_name("posts.reply"),
    ]


@pytest.mark.core
@pytest.mark.registry
def test_dispatcher_excludes_disabled_capabilities_even_when_registry_contains_rows() -> (
    None
):
    handlers = _handlers(
        _settings({"threads.read"}, {"selectors.thread"}), _transport()
    )

    assert "threads.read" in handlers
    assert "posts.reply" not in handlers
    assert "admin.high_risk.write" not in handlers


@pytest.mark.core
@pytest.mark.registry
def test_annotations_are_remote_and_operation_honest() -> None:
    tools = _listed(
        _settings(
            {"threads.read", "posts.reply"},
            {"selectors.thread", "writes.content", "confirm.live"},
        ),
        _transport(),
    )

    read_tool = tools[mcp_tool_name("threads.read")]
    assert _annotation_flags(read_tool) == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
    assert read_tool.output_schema == {"type": "object", "additionalProperties": True}

    write_tool = tools[mcp_tool_name("posts.reply")]
    assert _annotation_flags(write_tool) == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }
    assert write_tool.output_schema is None


@pytest.mark.core
@pytest.mark.registry
def test_annotations_mark_local_draft_tools_truthfully() -> None:
    tools = _listed(
        _settings(
            {"formatting.preflight", "drafts.read", "drafts.write"},
            {
                "formatting.content",
                "drafts.selector",
                "drafts.filters",
                "drafts.metadata",
                "drafts.confirm_delete",
            },
        )
    )

    def flags(name: str) -> tuple[bool, bool, bool, bool]:
        annotations = _annotation_flags(tools[mcp_tool_name(name)])
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


@pytest.mark.core
@pytest.mark.registry
def test_create_server_uses_dispatcher_as_single_registration_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})
    monkeypatch.setattr("hf_mcp.server.resolve_transport", lambda _: _transport())

    server = create_server(settings)

    async def scenario(client: Client) -> list[str]:
        return [tool.name for tool in (await client.list_tools()).tools]

    assert _session(server, scenario) == [mcp_tool_name("threads.read")]


@pytest.mark.core
@pytest.mark.registry
def test_full_api_registers_extended_reads_concretely_and_omits_placeholder_writes() -> (
    None
):
    settings = _preset_settings("full_api")
    handlers = _handlers(settings, _transport())
    tools = _listed(settings, _transport())

    for name in (
        "bytes.read",
        "contracts.read",
        "disputes.read",
        "bratings.read",
        "sigmarket.market.read",
        "sigmarket.order.read",
        "admin.high_risk.read",
    ):
        assert mcp_tool_name(name) in tools
        _assert_not_placeholder_handler(handlers[name])
    for name in ("contracts.write", "sigmarket.write", "admin.high_risk.write"):
        assert name not in handlers
        assert mcp_tool_name(name) not in tools

    for name in (
        "contracts.read",
        "disputes.read",
        "bratings.read",
        "sigmarket.market.read",
        "sigmarket.order.read",
    ):
        schema = tools[mcp_tool_name(name)].input_schema
        assert schema["properties"]["page"]["default"] == 1
        assert schema["properties"]["per_page"]["default"] == 30
        assert "required" not in schema

    contracts = tools[mcp_tool_name("contracts.read")].input_schema["properties"]
    disputes = tools[mcp_tool_name("disputes.read")].input_schema["properties"]
    market = tools[mcp_tool_name("sigmarket.market.read")].input_schema["properties"]
    orders = tools[mcp_tool_name("sigmarket.order.read")].input_schema["properties"]
    assert "cid" in contracts and "uid" in contracts
    assert "contract_id" not in contracts
    assert "cdid" in disputes and "uid" in disputes
    assert "did" not in disputes and "dispute_id" not in disputes
    assert "uid" in market and "listing_id" not in market
    assert "oid" in orders and "uid" in orders and "listing_id" not in orders


@pytest.mark.core
@pytest.mark.registry
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


@pytest.mark.core
@pytest.mark.registry
def test_core_read_input_schemas_are_published_truthfully() -> None:
    tools = _listed(
        _settings(
            {"me.read", "threads.read", "posts.read"},
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
            },
        ),
        _transport(),
    )
    me = tools[mcp_tool_name("me.read")].input_schema
    threads = tools[mcp_tool_name("threads.read")].input_schema
    posts = tools[mcp_tool_name("posts.read")].input_schema

    assert "uid" not in me["properties"]
    assert me["properties"]["include_basic_fields"]["default"] is True
    assert me["properties"]["include_advanced_fields"]["default"] is False
    assert set(me["properties"]["output_mode"]["enum"]) == {
        "readable",
        "structured",
        "raw",
    }
    assert me["properties"]["output_mode"]["default"] == "readable"
    assert me["properties"]["include_raw_payload"]["default"] is False
    assert me["properties"]["body_format"]["default"] == "markdown"
    assert set(me["properties"]["body_format"]["enum"]) == {"raw", "clean", "markdown"}

    assert threads["properties"]["page"]["default"] == 1
    assert threads["properties"]["per_page"]["default"] == 30
    assert threads.get("required", []) == []
    assert {tuple(item["required"]) for item in threads["anyOf"]} == {
        ("fid",),
        ("tid",),
        ("uid",),
    }
    assert posts["properties"]["include_post_body"]["default"] is True
    assert posts["properties"]["include_raw_payload"]["type"] == "boolean"
    assert posts.get("required", []) == []
    assert {tuple(item["required"]) for item in posts["anyOf"]} == {
        ("pid",),
        ("tid",),
        ("uid",),
    }
    for name in ("me.read", "threads.read", "posts.read"):
        assert tools[mcp_tool_name(name)].output_schema is not None


@pytest.mark.core
@pytest.mark.registry
def test_core_write_rows_register_concrete_handlers_and_omit_placeholder_rows() -> None:
    settings = _settings(
        {
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
        {
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
    handlers = _handlers(settings, _transport())

    for name in (
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
    ):
        _assert_not_placeholder_handler(handlers[name])
    for name in ("contracts.write", "sigmarket.write", "admin.high_risk.write"):
        assert name not in handlers


@pytest.mark.core
@pytest.mark.registry
def test_core_write_input_schemas_publish_exactly_the_documented_parameters() -> None:
    tools = _listed(
        _settings(
            {
                "threads.create",
                "posts.reply",
                "bytes.transfer",
                "bytes.deposit",
                "bytes.withdraw",
                "bytes.bump",
            },
            {
                "selectors.forum",
                "selectors.thread",
                "selectors.bytes",
                "writes.content",
                "writes.bytes",
                "confirm.live",
            },
        ),
        _transport(),
    )
    expected: dict[str, set[str]] = {
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
    for name, names in expected.items():
        assert set(tools[mcp_tool_name(name)].input_schema["properties"]) == names


@pytest.mark.core
def test_build_handlers_passes_settings_draft_dir_into_write_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"}, draft_dir=tmp_path)
    policy = CapabilityPolicy(settings)
    transport = _transport()
    captured: dict[str, object] = {}

    def _fake_build_write_handlers(
        policy_arg: CapabilityPolicy,
        transport_arg: HFTransport,
        *,
        draft_dir: Path | str | None = None,
    ) -> dict[str, Any]:
        captured.update(policy=policy_arg, transport=transport_arg, draft_dir=draft_dir)
        return {}

    monkeypatch.setattr(
        "hf_mcp.dispatcher.build_write_handlers", _fake_build_write_handlers
    )
    build_handlers(policy, settings, transport)

    assert captured == {"policy": policy, "transport": transport, "draft_dir": tmp_path}


@pytest.mark.core
def test_build_handlers_omits_remote_rows_when_there_is_no_transport() -> None:
    handlers = _handlers(
        _settings(
            {"threads.read", "posts.reply"},
            {"selectors.thread", "writes.content", "confirm.live"},
        )
    )

    assert handlers == {}


@pytest.mark.core
def test_build_handlers_does_not_perform_implicit_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_load_token_store(*_: object, **__: object) -> object:
        raise AssertionError("build_handlers must not call load_token_store")

    monkeypatch.setattr("hf_mcp.dispatcher.load_token_store", _fail_load_token_store)

    assert _handlers(_settings({"threads.read"}, {"selectors.thread"})) == {}


@pytest.mark.core
def test_core_and_extended_read_rows_register_concrete_handlers_when_transport_is_available() -> (
    None
):
    handlers = _handlers(
        _settings(
            {"me.read", "bytes.read"},
            {
                "selectors.user",
                "fields.me.basic",
                "selectors.bytes",
                "fields.bytes.amount",
            },
        ),
        _transport(),
    )

    _assert_not_placeholder_handler(handlers["me.read"])
    _assert_not_placeholder_handler(handlers["bytes.read"])


@pytest.mark.core
@pytest.mark.formatting
def test_formatting_preflight_registers_local_handler_without_transport(
    tmp_path: Path,
) -> None:
    settings = _settings(
        {"formatting.preflight"}, {"formatting.content"}, draft_dir=tmp_path
    )
    handler = _handlers(settings)["formatting.preflight"]
    tool = _listed(settings)[mcp_tool_name("formatting.preflight")]

    assert handler.__name__ == "_preflight_handler"
    flags = _annotation_flags(tool)
    assert flags["readOnlyHint"] is False
    assert flags["destructiveHint"] is False
    assert set(tool.input_schema["properties"]) == {
        "message",
        "source_path",
        "message_format",
    }
    assert tool.input_schema["anyOf"] == [
        {"required": ["message"]},
        {"required": ["source_path"]},
    ]
    result = handler(
        message='```json\n{"tool":"posts.reply"}\n```', message_format="markdown"
    )
    assert result["structuredContent"]["draft_id"]
    assert result["structuredContent"]["path"].endswith(".json")
    assert result["structuredContent"]["integrity"] < 1.0
    assert any(
        issue["code"] == "json_code_block_lossy_medium"
        for issue in result["structuredContent"]["issues"]
    )


@pytest.mark.core
@pytest.mark.formatting
def test_dispatcher_registers_concrete_local_draft_handlers_without_transport(
    tmp_path: Path,
) -> None:
    handlers = _handlers(
        _settings(
            {"formatting.preflight", "drafts.read", "drafts.write"},
            {
                "formatting.content",
                "drafts.selector",
                "drafts.filters",
                "drafts.metadata",
                "drafts.confirm_delete",
            },
            draft_dir=tmp_path,
        )
    )
    for name in ("drafts.list", "drafts.read", "drafts.update", "drafts.delete"):
        _assert_not_placeholder_handler(handlers[name])

    created = handlers["formatting.preflight"](
        message="Local draft body", message_format="markdown"
    )
    draft_id = created["structuredContent"]["draft_id"]

    listed = handlers["drafts.list"](limit=10, offset=0)
    assert listed["count"] >= 1
    assert any(
        item["draft_id"] == draft_id for item in listed["structuredContent"]["drafts"]
    )
    read_result = handlers["drafts.read"](draft_id=draft_id)
    assert read_result["structuredContent"]["draft_id"] == draft_id
    updated = handlers["drafts.update"](
        draft_id=draft_id, title="Updated title", status="ready"
    )
    assert updated["structuredContent"]["metadata"]["title"] == "Updated title"
    assert updated["structuredContent"]["metadata"]["status"] == "ready"
    with pytest.raises(ValueError, match="confirm_delete=True"):
        handlers["drafts.delete"](draft_id=draft_id)
    deleted = handlers["drafts.delete"](draft_id=draft_id, confirm_delete=True)
    assert deleted["structuredContent"]["deleted"] is True
    assert deleted["structuredContent"]["draft_id"] == draft_id


@pytest.mark.core
def test_forums_index_registers_local_handler_without_transport_and_keeps_structured_content_contract() -> (
    None
):
    settings = _settings({"forums.read"}, {"selectors.forum", "filters.pagination"})
    handlers = _handlers(settings)
    tools = _listed(settings)

    assert list(handlers) == ["forums.index"]
    assert mcp_tool_name("forums.read") not in tools
    flags = _annotation_flags(tools[mcp_tool_name("forums.index")])
    assert flags["readOnlyHint"] is True
    assert flags["openWorldHint"] is False

    result = handlers["forums.index"]()
    assert isinstance(result.get("content"), list)
    assert isinstance(result["structuredContent"]["_hf_flow"]["next_actions"], list)


@pytest.mark.core
def test_extended_read_handler_includes_hf_flow_structured_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_read(
        self: HFTransport, *, asks: dict[str, Any], helper: str
    ) -> dict[str, Any]:
        del asks
        assert helper == "sigmarket/order"
        return {"sigmarket/order": [{"smid": "17", "buyer": "2047020", "seller": "1"}]}

    monkeypatch.setattr(HFTransport, "read_raw", _fake_read)
    settings = _settings(
        {"sigmarket.order.read"}, {"selectors.sigmarket", "filters.pagination"}
    )

    tool = _listed(settings, _transport())[mcp_tool_name("sigmarket.order.read")]
    result = _handlers(settings, _transport())["sigmarket.order.read"](oid=17)

    assert tool.output_schema == {"type": "object", "additionalProperties": True}
    flow = result["structuredContent"]["_hf_flow"]
    assert flow["entry_tool"] == "sigmarket.order.read"
    assert isinstance(flow["next_actions"], list)


@pytest.mark.core
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


@pytest.mark.core
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


@pytest.mark.core
def test_nested_envelope_json_in_text_content_is_rejected_by_validator() -> None:
    nested_json = json.dumps(
        {
            "content": [{"type": "text", "text": "legacy"}],
            "structuredContent": {"me": []},
        }
    )
    result = types.CallToolResult(
        content=[types.TextContent(type="text", text=nested_json)],
        structured_content={"me": []},
    )

    with pytest.raises(AssertionError, match="Nested envelope JSON detected"):
        _assert_rejects_nested_envelope_json_text(result)


# --------------------------------------------------------------- fail closed


@pytest.mark.core
def test_create_server_fails_closed_when_runtime_secrets_are_missing() -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})

    with pytest.raises(
        ValueError, match="Missing required environment variable: HF_MCP_CLIENT_ID"
    ):
        create_server(settings)


def _settings_without_token(tmp_path: Path) -> HFMCPSettings:
    return _settings(
        {"threads.read"},
        {"selectors.thread"},
        token_path=tmp_path / "token.json",
        runtime_env={
            "HF_MCP_CLIENT_ID": "client",
            "HF_MCP_CLIENT_SECRET": "secret",
            "HF_MCP_TOKEN_PATH": str((tmp_path / "token.json").resolve()),
        },
    )


@pytest.mark.core
def test_create_server_fails_closed_when_token_bundle_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="No usable Hack Forums access token"):
        create_server(_settings_without_token(tmp_path))


@pytest.mark.core
def test_serve_stdio_fails_closed_when_token_bundle_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="No usable Hack Forums access token"):
        serve_stdio(_settings_without_token(tmp_path))


# ------------------------------------------------------------ session surface


@pytest.mark.core
@pytest.mark.registry
@pytest.mark.parametrize(
    "profile", sorted(name for name, caps in PRESET_CAPABILITIES.items() if caps)
)
def test_tools_list_for_each_preset_equals_the_registry_contract(profile: str) -> None:
    settings = _preset_settings(profile)
    policy = CapabilityPolicy(settings)
    tools = _listed(settings, _transport())

    expected = [spec for spec in TOOLS if policy.can_register(spec.name)]
    assert expected, profile
    assert list(tools) == [spec.mcp_name for spec in expected]
    for spec in expected:
        tool = tools[spec.mcp_name]
        assert tool.description == spec.description
        assert tool.input_schema == policy.input_schema(spec)
        assert tool.output_schema == spec.output_schema
        assert _annotation_flags(tool) == spec.annotations
        # The published schema is itself a valid Draft 2020-12 schema.
        Draft202012Validator.check_schema(tool.input_schema)


@pytest.mark.core
@pytest.mark.registry
def test_every_published_tool_is_client_safe_and_carries_no_internal_metadata() -> None:
    tools = _listed(_preset_settings("full_api"), _transport())

    assert tools
    for name, tool in tools.items():
        assert name == tool.name
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name), name
        assert tool.meta is None, name
        dumped = json.dumps(
            tool.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        assert "x-hf-" not in dumped, name
        assert "_meta" not in dumped, name


@pytest.mark.core
@pytest.mark.registry
def test_output_options_gate_the_published_output_parameters() -> None:
    base = {"posts.read"}
    families = {"selectors.thread"}
    output_names = {"output_mode", "include_raw_payload", "body_format"}

    without = _listed(_settings(base, families), _transport())
    with_options = _listed(_settings(base, families | {"output.options"}), _transport())

    plain = set(without["posts_read"].input_schema["properties"])
    gated = set(with_options["posts_read"].input_schema["properties"])
    assert not plain & output_names
    assert output_names <= gated
    assert plain <= gated


@pytest.mark.core
def test_initialize_reports_server_name_and_package_version() -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})

    async def scenario(client: Client) -> Any:
        return client.server_info

    info = _session(_server(settings, _transport()), scenario)

    assert info.name == "hf-mcp"
    assert info.version == hf_mcp.__version__


@pytest.mark.core
def test_hf_envelope_is_converted_to_protocol_call_tool_result() -> None:
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
            "_hf_flow": {"version": 1, "next_actions": []},
        },
    }
    settings = _settings({"me.read"}, {"fields.me.basic", "selectors.user"})

    result = _call(
        _server(settings, handlers={"me.read": lambda **_: envelope}), "me_read", {}
    )

    assert result.is_error is False
    assert result.structured_content == envelope["structuredContent"]
    assert [part.type for part in result.content] == ["text", "resource"]
    assert result.content[0].text == "me.read returned 1 row(s)."
    raw = result.content[1].resource.model_dump(by_alias=True, exclude_none=True)
    assert raw == {
        "uri": "hf-mcp://raw/me.read",
        "mimeType": "application/json",
        "text": '{"me":[{"uid":"5"}]}',
    }
    _assert_rejects_nested_envelope_json_text(result)


@pytest.mark.core
def test_session_call_returns_structured_content_and_raw_resource_from_a_real_handler() -> (
    None
):
    transport = _CountingTransport()
    settings = _settings(
        {"me.read"}, {"fields.me.basic", "selectors.user", "output.options"}
    )

    result = _call(
        _server(settings, transport),
        "me_read",
        {"output_mode": "raw", "include_raw_payload": True},
    )

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["me"][0]["uid"] == "5"
    assert any(part.type == "resource" for part in result.content)
    _assert_rejects_nested_envelope_json_text(result)
    assert transport.calls == 1


@pytest.mark.core
def test_next_actions_name_only_registered_tools_and_no_write_under_reader() -> None:
    settings = _preset_settings("reader")
    write_names = {spec.name for spec in TOOLS if spec.operation == "write"}
    registered = set(_handlers(settings, _CountingTransport()))
    assert registered and not registered & write_names

    flows = 0
    server = _server(settings, _CountingTransport())
    for name, arguments in (
        ("threads_read", {"tid": 1}),
        ("posts_read", {"tid": 1}),
        ("me_read", {}),
        ("forums_index", {}),
    ):
        result = _call(server, name, arguments)
        assert result.is_error is False, (name, result.structured_content)
        assert result.structured_content is not None
        actions = result.structured_content["_hf_flow"]["next_actions"]
        flows += len(actions)
        for action in actions:
            assert action["tool"] in registered, (name, action)
            assert action["tool"] not in write_names, (name, action)
    assert flows > 0, "expected the reader reads to offer at least one next action"


@pytest.mark.core
def test_next_actions_are_pruned_to_the_registered_tool_set() -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})
    envelope = {
        "content": [{"type": "text", "text": "ok"}],
        "structuredContent": {
            "_hf_flow": {
                "next_actions": [
                    {"tool": "threads.read", "arguments": {"tid": 1}, "label": "a"},
                    {"tool": "posts.reply", "arguments": {"tid": 1}, "label": "b"},
                    {"tool": "nowhere.read", "arguments": {}, "label": "c"},
                ]
            }
        },
    }

    result = _call(
        _server(settings, handlers={"threads.read": lambda **_: envelope}),
        "threads_read",
        {"tid": 1},
    )

    actions = result.structured_content["_hf_flow"]["next_actions"]
    assert [action["tool"] for action in actions] == ["threads.read"]


# ------------------------------------------------- validation is authoritative


def _write_settings() -> HFMCPSettings:
    return _settings(
        {"posts.reply", "bytes.transfer", "bytes.withdraw"},
        {
            "selectors.thread",
            "selectors.bytes",
            "writes.content",
            "writes.bytes",
            "confirm.live",
        },
    )


def _validation_case(
    settings: HFMCPSettings,
    tool: str,
    arguments: dict[str, Any],
    *,
    message_has: tuple[str, ...] = (),
) -> str:
    """Send ``arguments`` expecting INVALID_ARGUMENT with zero handler and transport calls.

    Returns the error message.
    """
    transport = _CountingTransport()
    counter: dict[str, int] = {}
    handlers = _counting(_handlers(settings, transport), counter)

    result = _call(_server(settings, handlers=handlers), tool, arguments)

    error = _assert_error(result, "INVALID_ARGUMENT", tool)
    for fragment in message_has:
        assert fragment in error["message"], (fragment, error["message"])
    assert counter == {}, f"handler ran for rejected call {arguments!r}"
    assert transport.calls == 0, f"transport used for rejected call {arguments!r}"
    return str(error["message"])


@pytest.mark.core
@pytest.mark.regression
@pytest.mark.parametrize("value", [False, 1, "true", None, 0, "True", [], {}])
def test_confirm_live_const_rejects_everything_except_exact_true(value: Any) -> None:
    _validation_case(
        _write_settings(),
        "posts_reply",
        {"tid": 1, "message": "hello", "confirm_live": value},
        message_has=("confirm_live",),
    )


@pytest.mark.core
@pytest.mark.regression
def test_write_message_is_capped_at_the_shared_limit() -> None:
    settings = _write_settings()
    message = _validation_case(
        settings,
        "posts_reply",
        {
            "tid": 1,
            "message": "a" * (MAX_MESSAGE_CHARS + 1),
            "confirm_live": True,
        },
        message_has=("message",),
    )
    assert "a" * 50 not in message
    handlers = _handlers(settings, _CountingTransport())
    handlers["posts.reply"] = lambda **kwargs: {
        "content": [{"type": "text", "text": "ok"}],
        "structuredContent": {"length": len(kwargs["message"])},
    }
    result = _call(
        _server(settings, handlers=handlers),
        "posts_reply",
        {"tid": 1, "message": "a" * MAX_MESSAGE_CHARS, "confirm_live": True},
    )
    assert result.is_error is False
    assert result.structured_content == {"length": MAX_MESSAGE_CHARS}


@pytest.mark.core
@pytest.mark.regression
def test_confirm_live_exact_true_reaches_the_handler() -> None:
    settings = _write_settings()
    counter: dict[str, int] = {}
    handlers = _counting(_handlers(settings, _CountingTransport()), counter)
    handlers["posts.reply"] = lambda **kwargs: {
        "content": [{"type": "text", "text": "ok"}],
        "structuredContent": {"seen": sorted(kwargs)},
    }

    result = _call(
        _server(settings, handlers=handlers),
        "posts_reply",
        {"tid": 1, "message": "hello", "confirm_live": True},
    )

    assert result.is_error is False
    assert result.structured_content == {"seen": ["confirm_live", "message", "tid"]}


@pytest.mark.core
@pytest.mark.regression
def test_enum_has_positive_and_negative_controls() -> None:
    settings = _settings({"threads.read"}, {"selectors.thread", "output.options"})
    _validation_case(
        settings,
        "threads_read",
        {"tid": 1, "output_mode": "verbose"},
        message_has=("output_mode",),
    )
    transport = _CountingTransport()
    result = _call(
        _server(settings, transport),
        "threads_read",
        {"tid": 1, "output_mode": "structured"},
    )
    assert result.is_error is False
    assert transport.calls == 1


@pytest.mark.core
@pytest.mark.regression
@pytest.mark.parametrize("draft_id", ["not-a-draft", "A" * 32, "a" * 31, "a" * 33])
def test_pattern_has_positive_and_negative_controls(
    tmp_path: Path, draft_id: str
) -> None:
    settings = _settings({"drafts.read"}, {"drafts.selector"}, draft_dir=tmp_path)
    _validation_case(
        settings, "drafts_read", {"draft_id": draft_id}, message_has=("draft_id",)
    )
    # Positive: a well-formed id passes validation and reaches the handler.
    counter: dict[str, int] = {}
    handlers = _counting(_handlers(settings), counter)
    result = _call(
        _server(settings, handlers=handlers), "drafts_read", {"draft_id": "a" * 32}
    )
    assert counter == {"drafts.read": 1}
    assert result.is_error is True
    assert result.structured_content["error"]["code"] != "INVALID_ARGUMENT"


@pytest.mark.core
@pytest.mark.regression
@pytest.mark.parametrize(
    ("arguments", "name"),
    [
        ({"tid": 0}, "tid"),
        ({"tid": 1, "per_page": 0}, "per_page"),
        ({"tid": 1, "per_page": 31}, "per_page"),
        ({"tid": 1, "page": 0}, "page"),
        ({"tid": "7"}, "tid"),
        ({"tid": True}, "tid"),
        ({"tid": 1.5}, "tid"),
    ],
)
def test_minimum_maximum_and_type_have_negative_controls(
    arguments: dict[str, Any], name: str
) -> None:
    settings = _settings({"threads.read"}, {"selectors.thread", "filters.pagination"})
    _validation_case(settings, "threads_read", arguments, message_has=(name,))


@pytest.mark.core
@pytest.mark.regression
@pytest.mark.parametrize("per_page", [1, 30])
def test_minimum_and_maximum_boundaries_pass(per_page: int) -> None:
    settings = _settings({"threads.read"}, {"selectors.thread", "filters.pagination"})
    transport = _CountingTransport()

    result = _call(
        _server(settings, transport), "threads_read", {"tid": 1, "per_page": per_page}
    )

    assert result.is_error is False
    assert transport.calls == 1


@pytest.mark.core
@pytest.mark.regression
def test_any_of_selector_alternatives_have_positive_and_negative_controls() -> None:
    settings = _settings({"threads.read"}, {"selectors.thread", "selectors.forum"})
    _validation_case(settings, "threads_read", {}, message_has=("fid", "tid", "uid"))
    for selector in ({"fid": 2}, {"tid": 1}):
        transport = _CountingTransport()
        result = _call(_server(settings, transport), "threads_read", selector)
        assert result.is_error is False, selector
        assert transport.calls == 1


@pytest.mark.core
@pytest.mark.regression
def test_additional_properties_false_rejects_unknown_parameters() -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})
    _validation_case(
        settings,
        "threads_read",
        {"tid": 1, "include_everything": True},
        message_has=("include_everything",),
    )
    transport = _CountingTransport()
    result = _call(_server(settings, transport), "threads_read", {"tid": 1})
    assert result.is_error is False
    assert transport.calls == 1


@pytest.mark.core
@pytest.mark.regression
@pytest.mark.parametrize(
    ("name", "named"),
    [
        ("typo_param", True),
        ("a" + "b" * 63, True),
        ("a" + "b" * 64, False),
        ("Upper", False),
        ("9lives", False),
        ("has-dash", False),
        ("sp ace", False),
        ("naïve", False),
    ],
)
def test_unknown_parameter_is_named_only_when_it_looks_like_a_name(
    name: str, named: bool
) -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})
    secret = "test-UNTRUSTED-VALUE-DO-NOT-ECHO"
    transport = _CountingTransport()

    result = _call(
        _server(settings, transport), "threads_read", {"tid": 1, name: secret}
    )

    error = _assert_error(result, "INVALID_ARGUMENT", "threads_read")
    assert transport.calls == 0
    assert (name in error["message"]) is named
    assert ("(unknown parameter)" in error["message"]) is not named
    assert secret not in json.dumps(result.model_dump(mode="json"))


class _AsyncCallable:
    async def __call__(self, **arguments: Any) -> dict[str, Any]:
        await anyio.sleep(0)
        return _ok_envelope("async-callable-object")


async def _async_tool(label: str, **arguments: Any) -> dict[str, Any]:
    await anyio.sleep(0)
    return _ok_envelope(label)


def _ok_envelope(label: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": label}],
        "structuredContent": {"label": label},
    }


@pytest.mark.core
@pytest.mark.regression
@pytest.mark.parametrize(
    ("handler", "label"),
    [
        (_AsyncCallable(), "async-callable-object"),
        (partial(_async_tool, "partial-coroutine"), "partial-coroutine"),
        (lambda **_: _ok_envelope("sync"), "sync"),
    ],
    ids=["async-callable-object", "partial-of-coroutine-function", "plain-sync"],
)
def test_server_awaits_every_awaitable_handler_shape(
    handler: Handler, label: str
) -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})

    result = _call(
        _server(settings, handlers={"threads.read": handler}),
        "threads_read",
        {"tid": 1},
    )

    assert result.is_error is False
    assert result.structured_content == {"label": label}


@pytest.mark.core
@pytest.mark.regression
def test_required_names_the_missing_property_never_the_root_path() -> None:
    settings = _settings(
        {"drafts.write"},
        {"drafts.selector", "drafts.confirm_delete", "drafts.metadata"},
    )

    message = _validation_case(
        settings,
        "drafts_delete",
        {"draft_id": "a" * 32},
        message_has=("confirm_delete",),
    )

    assert "$" not in message
    assert message != "Invalid arguments: (arguments)"
    # Positive control: supplying the property reaches the handler.
    counter: dict[str, int] = {}
    handlers = _counting(_handlers(settings), counter)
    _call(
        _server(settings, handlers=handlers),
        "drafts_delete",
        {"draft_id": "a" * 32, "confirm_delete": True},
    )
    assert counter == {"drafts.delete": 1}


@pytest.mark.core
@pytest.mark.regression
def test_error_messages_name_parameter_paths_but_never_values() -> None:
    settings = _write_settings()
    secret = "test-SECRETVALUE" * 3
    for arguments in (
        {"tid": secret, "message": "m", "confirm_live": True},
        {"tid": 1, "message": "m", "confirm_live": secret},
        {"tid": 1, "message": "m", "confirm_live": True, secret: 1},
    ):
        result = _call(
            _server(settings, handlers=_handlers(settings, _CountingTransport())),
            "posts_reply",
            arguments,
        )
        error = _assert_error(result, "INVALID_ARGUMENT", "posts_reply")
        assert secret not in json.dumps(result.model_dump(by_alias=True, mode="json"))
        assert len(error["message"]) <= 200


@pytest.mark.core
@pytest.mark.regression
def test_unknown_tool_is_an_invalid_argument_error_result() -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})

    result = _call(_server(settings, _CountingTransport()), "posts_reply", {})

    _assert_error(result, "INVALID_ARGUMENT")


@pytest.mark.core
@pytest.mark.regression
@pytest.mark.parametrize(
    ("sent", "family"),
    [
        ({"tid": 1, "output_mode": "raw"}, "output.options"),
        ({"tid": 1, "include_raw_payload": True}, "output.options"),
        ({"tid": 1, "body_format": "raw"}, "output.options"),
    ],
)
def test_parameters_pruned_by_the_profile_are_rejected_when_sent_anyway(
    sent: dict[str, Any], family: str
) -> None:
    pruned = _settings({"posts.read"}, {"selectors.thread"})
    parameter = next(name for name in sent if name != "tid")
    _validation_case(pruned, "posts_read", sent, message_has=(parameter,))

    enabled = _settings({"posts.read"}, {"selectors.thread", family})
    transport = _CountingTransport()
    result = _call(_server(enabled, transport), "posts_read", sent)
    assert result.is_error is False, result.structured_content
    assert transport.calls == 1


@pytest.mark.core
@pytest.mark.regression
def test_selectors_from_a_disabled_family_are_rejected_until_it_is_enabled() -> None:
    pruned = _settings({"threads.read"}, {"selectors.thread"})
    _validation_case(pruned, "threads_read", {"tid": 1, "fid": 2}, message_has=("fid",))

    enabled = _settings({"threads.read"}, {"selectors.thread", "selectors.forum"})
    transport = _CountingTransport()
    result = _call(_server(enabled, transport), "threads_read", {"tid": 1, "fid": 2})
    assert result.is_error is False, result.structured_content
    assert transport.calls == 1


# ----------------------------------------------------------------- error maps


class _TokenSeedStore:
    def require_bundle(self) -> TokenBundle:
        return TokenBundle(
            access_token="test-TOKENSEED",
            token_type="Bearer",
            scope=frozenset({"read"}),
        )


@pytest.mark.core
@pytest.mark.regression
def test_hf_api_error_returns_error_v1_for_failed_read_and_write() -> None:
    read_error = HFAPIError(
        build_error(
            "UPSTREAM_UNAVAILABLE",
            operation="read",
            http_status=503,
            retry_after=7,
            retryable=True,
        )
    )
    write_error = HFAPIError(
        build_error(
            "WRITE_OUTCOME_UNKNOWN",
            operation="write",
            mutation_outcome="unknown",
        )
    )

    def failing_read(**_: Any) -> dict[str, Any]:
        raise read_error

    def failing_write(**_: Any) -> dict[str, Any]:
        raise write_error

    settings = _settings(
        {"me.read", "posts.reply"},
        PRESET_PARAMETER_FAMILIES["full_api"],
    )
    server = _server(
        settings, handlers={"me.read": failing_read, "posts.reply": failing_write}
    )

    read_result = _call(server, "me_read", {})
    write_result = _call(
        server, "posts_reply", {"tid": 123, "message": "Hello", "confirm_live": True}
    )

    read_data = _assert_error(read_result, "UPSTREAM_UNAVAILABLE", "me_read")
    assert (
        read_data["http_status"],
        read_data["retry_after"],
        read_data["retryable"],
    ) == (
        503,
        7,
        True,
    )
    write_data = _assert_error(write_result, "WRITE_OUTCOME_UNKNOWN", "posts_reply")
    assert (write_data["mutation_outcome"], write_data["retryable"]) == (
        "unknown",
        False,
    )
    for result in (read_result, write_result):
        assert "_hf_flow" not in (result.structured_content or {})
        assert all(part.type == "text" for part in result.content)


@pytest.mark.core
@pytest.mark.regression
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
            RuntimeError("SECRETSEED /path"),
            "INTERNAL_ERROR",
            "An internal error occurred.",
        ),
    ],
)
def test_handler_exceptions_map_to_error_v1_through_the_session(
    caplog: pytest.LogCaptureFixture,
    is_async: bool,
    error: Exception,
    code: str,
    message: str,
) -> None:
    if is_async:

        async def handler(**_: Any) -> dict[str, Any]:
            raise error

    else:

        def handler(**_: Any) -> dict[str, Any]:  # type: ignore[misc]
            raise error

    settings = _settings({"threads.read"}, {"selectors.thread"})
    caplog.set_level(logging.DEBUG)

    result = _call(
        _server(settings, handlers={"threads.read": handler}),
        "threads_read",
        {"tid": 1},
    )

    data = _assert_error(result, code, "threads_read")
    assert data["message"] == message
    assert (data["operation"], data["retryable"], data["mutation_outcome"]) == (
        "local",
        False,
        "not_attempted",
    )
    assert "SECRETSEED" not in result.model_dump_json(by_alias=True)
    assert "SECRETSEED" not in caplog.text


@pytest.mark.core
@pytest.mark.regression
def test_a_malformed_handler_result_is_an_internal_error_without_detail() -> None:
    settings = _settings({"threads.read"}, {"selectors.thread"})

    result = _call(
        _server(
            settings, handlers={"threads.read": lambda **_: {"oops": "SECRETSEED"}}
        ),
        "threads_read",
        {"tid": 1},
    )

    error = _assert_error(result, "INTERNAL_ERROR", "threads_read")
    assert error["message"] == "An internal error occurred."
    assert "SECRETSEED" not in result.model_dump_json(by_alias=True)


# --------------------------------------------------------------- stdio process


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    pythonpath = env.get("PYTHONPATH")
    src_path = str(SRC_PATH)
    env["PYTHONPATH"] = f"{src_path}:{pythonpath}" if pythonpath else src_path
    return env


def _run_stdio_probe(
    probe: str, scenario: Callable[[ClientSession], Awaitable[Any]]
) -> Any:
    async def _run() -> Any:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", probe],
            env=_child_env(),
            cwd=str(PRODUCT_ROOT),
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await scenario(session)

    return anyio.run(_run)


_PROBE_PRELUDE = """
import hf_mcp.server as server
from hf_mcp.config import HFMCPSettings, PRESET_PARAMETER_FAMILIES
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport

class _ProbeTokenStore:
    def require_bundle(self):
        return TokenBundle(access_token="test-TOKENSEED", token_type="Bearer", scope=frozenset({"read"}))
"""


@pytest.mark.core
def test_runtime_stdio_client_session_returns_protocol_structured_content_and_raw_resource() -> (
    None
):
    probe = (
        _PROBE_PRELUDE
        + """
transport = HFTransport(token_store=_ProbeTokenStore(), base_url="https://example.test")
transport.read = lambda *, asks, helper=None: {"me": [{"uid": "5", "username": "forge"}]}
transport.read_raw = lambda *, asks, helper=None: {"me": [{"uid": "5", "username": "forge", "raw": True}]}
settings = HFMCPSettings(
    profile="test",
    enabled_capabilities=frozenset({"me.read"}),
    enabled_parameter_families=frozenset({"fields.me.basic", "selectors.user", "output.options"}),
)
server.resolve_transport = lambda _: transport
server.serve_stdio(settings)
"""
    )

    async def scenario(session: ClientSession) -> Any:
        return await session.call_tool(
            "me_read", {"output_mode": "raw", "include_raw_payload": True}
        )

    result = _run_stdio_probe(probe, scenario)

    assert result.structured_content["me"][0]["uid"] == "5"
    assert any(getattr(item, "type", None) == "resource" for item in result.content)
    _assert_rejects_nested_envelope_json_text(result)


@pytest.mark.core
@pytest.mark.regression
def test_runtime_stdio_client_session_returns_error_v1_for_failed_read_and_write() -> (
    None
):
    probe = (
        _PROBE_PRELUDE
        + """
import email.message
import io
import urllib.error
import hf_mcp.transport as hf_transport

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
server.resolve_transport = lambda _: transport
server.serve_stdio(settings)
"""
    )

    async def scenario(session: ClientSession) -> tuple[Any, Any]:
        read_result = await session.call_tool(
            "me_read", {"output_mode": "raw", "include_raw_payload": True}
        )
        write_result = await session.call_tool(
            "posts_reply", {"tid": 123, "message": "Hello there", "confirm_live": True}
        )
        return read_result, write_result

    read_result, write_result = _run_stdio_probe(probe, scenario)

    read_data = _assert_error(read_result, "UPSTREAM_UNAVAILABLE", "me_read")
    assert (
        read_data["http_status"],
        read_data["retry_after"],
        read_data["retryable"],
    ) == (
        503,
        7,
        True,
    )
    write_data = _assert_error(write_result, "WRITE_OUTCOME_UNKNOWN", "posts_reply")
    assert write_data["mutation_outcome"] == "unknown"
    for result in (read_result, write_result):
        dumped = result.model_dump_json(by_alias=True)
        for seed in ("TOKENSEED", "BODYSEED", "WRITESEED", "example.test"):
            assert seed not in dumped


@pytest.mark.core
def test_runtime_stdio_tool_list_matches_the_registry_for_full_api() -> None:
    probe = (
        _PROBE_PRELUDE
        + """
transport = HFTransport(token_store=_ProbeTokenStore(), base_url="https://example.test")
from hf_mcp.config import PRESET_CAPABILITIES
settings = HFMCPSettings(
    profile="full_api",
    enabled_capabilities=PRESET_CAPABILITIES["full_api"],
    enabled_parameter_families=PRESET_PARAMETER_FAMILIES["full_api"],
)
server.resolve_transport = lambda _: transport
server.serve_stdio(settings)
"""
    )

    async def scenario(session: ClientSession) -> Any:
        return await session.list_tools()

    listed = _run_stdio_probe(probe, scenario)

    settings = _preset_settings("full_api")
    policy = CapabilityPolicy(settings)
    expected = {
        spec.mcp_name: policy.input_schema(spec)
        for spec in TOOLS
        if policy.can_register(spec.name)
    }
    assert {tool.name: tool.input_schema for tool in listed.tools} == expected


@pytest.mark.core
def test_serve_stdio_exits_cleanly_when_stdio_is_closed() -> None:
    probe = (
        _PROBE_PRELUDE
        + """
transport = HFTransport(token_store=_ProbeTokenStore(), base_url="https://example.test")
settings = HFMCPSettings(
    profile="test",
    enabled_capabilities=frozenset({"threads.read"}),
    enabled_parameter_families=frozenset({"selectors.thread"}),
)
server.resolve_transport = lambda _: transport
server.serve_stdio(settings)
print("SERVED-ONCE", file=__import__("sys").stderr)
"""
    )
    import subprocess

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        input=b"",
        capture_output=True,
        env=_child_env(),
        cwd=str(PRODUCT_ROOT),
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr.decode()
    assert completed.stdout == b""
    assert b"SERVED-ONCE" in completed.stderr
