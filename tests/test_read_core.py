from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.capabilities import CAPABILITY_PARAMETER_FAMILIES, CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.dispatcher import RuntimeBundle, register_tools
from hf_mcp.registry import get_core_read_specs, get_tool_spec
from hf_mcp.schemas import build_tool_schema
from hf_mcp.token_store import TokenBundle
from hf_mcp.tools.read_core import build_core_read_handlers, list_posts, list_threads
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
    ) -> None:
        self.tools[name] = {
            "description": description,
            "input_schema": input_schema,
            "annotations": annotations,
            "handler": handler,
        }


class _StubTokenStore:
    def require_bundle(self) -> TokenBundle:
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset())


def _policy(*, enabled_capabilities: set[str], enabled_parameter_families: set[str]) -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset(enabled_capabilities),
            enabled_parameter_families=frozenset(enabled_parameter_families),
        )
    )


def test_core_read_specs_match_registry_rows_and_parameter_families() -> None:
    specs = get_core_read_specs()
    assert {spec.tool_name for spec in specs} == {
        "me.read",
        "users.read",
        "forums.read",
        "threads.read",
        "posts.read",
    }
    for spec in specs:
        assert set(spec.parameter_families) == set(CAPABILITY_PARAMETER_FAMILIES[spec.capability_family])


def test_build_core_read_handlers_registers_only_policy_allowed_core_rows() -> None:
    policy = _policy(
        enabled_capabilities={"me.read", "threads.read"},
        enabled_parameter_families={"selectors.user", "fields.me.basic", "selectors.forum", "selectors.thread"},
    )
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    handlers = build_core_read_handlers(policy, transport)

    assert set(handlers) == {"me.read", "threads.read"}
    assert "users.read" not in handlers
    assert "posts.read" not in handlers


def test_me_schema_prunes_advanced_parameter_when_family_not_allowed() -> None:
    spec = get_tool_spec("me.read")
    policy = _policy(
        enabled_capabilities={"me.read"},
        enabled_parameter_families={"selectors.user", "fields.me.basic"},
    )

    schema = build_tool_schema(spec, policy)

    assert "include_basic_fields" in schema["properties"]
    assert "include_advanced_fields" not in schema["properties"]


def test_threads_and_posts_schema_use_anchored_required_selectors() -> None:
    policy = _policy(
        enabled_capabilities={"threads.read", "posts.read"},
        enabled_parameter_families={"selectors.forum", "selectors.thread", "selectors.post", "filters.pagination", "fields.posts.body"},
    )

    threads_schema = build_tool_schema(get_tool_spec("threads.read"), policy)
    posts_schema = build_tool_schema(get_tool_spec("posts.read"), policy)

    assert set(threads_schema.get("required", [])) == {"fid"}
    assert "tid" in threads_schema["properties"]
    assert "tid" not in threads_schema["required"]

    assert set(posts_schema.get("required", [])) == {"tid"}
    assert "pid" in posts_schema["properties"]
    assert "pid" not in posts_schema["required"]


def test_dispatcher_output_excludes_disabled_core_read_capability() -> None:
    policy = _policy(
        enabled_capabilities={"users.read"},
        enabled_parameter_families={"selectors.user", "fields.users.profile", "filters.pagination"},
    )
    server = _CaptureServer()

    register_tools(server, policy, RuntimeBundle())

    assert "users.read" in server.tools
    assert "me.read" not in server.tools
    assert "forums.read" not in server.tools


def test_list_posts_delegates_to_transport_helper_and_returns_normalized_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"posts": {"pid": 7, "subject": "Hello", "message": "Body"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_posts(
        transport=transport,
        tid=123,
        pid=7,
        page=2,
        per_page=99,
        include_post_body=True,
    )

    assert captured["route"] == "/read/posts"
    assert captured["payload"]["asks"]["posts"]["_tid"] == 123
    assert captured["payload"]["asks"]["posts"]["_pid"] == 7
    assert captured["payload"]["asks"]["posts"]["_page"] == 2
    assert captured["payload"]["asks"]["posts"]["_perpage"] == 30
    assert captured["payload"]["asks"]["posts"]["message"] is True
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result["posts"] == [{"pid": "7", "subject": "Hello", "message": "Body"}]


def test_me_handler_drops_advanced_fields_when_parameter_family_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"me": {"uid": 5, "username": "forge", "unreadpms": 99}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    policy = _policy(
        enabled_capabilities={"me.read"},
        enabled_parameter_families={"selectors.user", "fields.me.basic"},
    )
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    handlers = build_core_read_handlers(policy, transport)

    result = handlers["me.read"](uid=5, include_basic_fields=True, include_advanced_fields=True)

    assert captured["route"] == "/read/me"
    me_asks = captured["payload"]["asks"]["me"]
    assert me_asks["_uid"] == 5
    assert me_asks["uid"] is True
    assert me_asks["username"] is True
    assert "unreadpms" not in me_asks
    assert "unreadalerts" not in me_asks
    assert result["me"] == [{"uid": "5", "username": "forge", "unreadpms": "99"}]


def test_list_threads_omits_optional_tid_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"threads": [{"tid": 123, "subject": "Topic"}]}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_threads(transport=transport, fid=375, page=3, per_page=100)

    thread_asks = captured["payload"]["asks"]["threads"]
    assert captured["route"] == "/read/threads"
    assert thread_asks["_fid"] == 375
    assert "_tid" not in thread_asks
    assert thread_asks["_page"] == 3
    assert thread_asks["_perpage"] == 30
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result["threads"] == [{"tid": "123", "subject": "Topic"}]


def test_list_posts_omits_optional_pid_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"posts": {"pid": 88, "subject": "No PID filter", "message": "Text"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_posts(
        transport=transport,
        tid=123,
        page=4,
        per_page=200,
        include_post_body=False,
    )

    post_asks = captured["payload"]["asks"]["posts"]
    assert captured["route"] == "/read/posts"
    assert post_asks["_tid"] == 123
    assert "_pid" not in post_asks
    assert post_asks["_page"] == 4
    assert post_asks["_perpage"] == 30
    assert "message" not in post_asks
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result["posts"] == [{"pid": "88", "subject": "No PID filter", "message": "Text"}]
