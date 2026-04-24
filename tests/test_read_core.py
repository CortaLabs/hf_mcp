from __future__ import annotations

import json
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
from hf_mcp.output_modes import ReadOutputDefaults
from hf_mcp.registry import get_core_read_specs, get_tool_spec
from hf_mcp.schemas import build_tool_schema
from hf_mcp.token_store import TokenBundle
from hf_mcp.tools.read_core import (
    build_core_read_handlers,
    get_profile,
    get_user,
    list_forums,
    list_posts,
    list_threads,
)
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
        output_schema: dict[str, object] | None = None,
        handler: Any,
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


def test_me_handler_reads_authenticated_profile_without_uid_selector(
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

    result = handlers["me.read"](include_basic_fields=None, include_advanced_fields=True)

    assert captured["route"] == "/read/me"
    me_asks = captured["payload"]["asks"]["me"]
    assert "_uid" not in me_asks
    assert me_asks["uid"] is True
    assert me_asks["username"] is True
    assert me_asks["usergroup"] is True
    assert me_asks["avatar"] is True
    assert "unreadpms" not in me_asks
    assert "unreadalerts" not in me_asks
    assert "invisible" not in me_asks
    assert "totalpms" not in me_asks
    assert "lastactive" not in me_asks
    assert "warningpoints" not in me_asks
    assert "regdate" not in me_asks
    assert result["structuredContent"]["me"] == [{"uid": "5", "username": "forge", "unreadpms": "99"}]
    assert result["content"][0]["type"] == "text"


def test_get_profile_omits_uid_selector_when_called_directly(monkeypatch: pytest.MonkeyPatch) -> None:
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
        return {"me": {"uid": 5, "username": "forge"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = get_profile(transport=transport)

    assert captured["route"] == "/read/me"
    assert captured["payload"]["asks"]["me"] == {
        "uid": True,
        "username": True,
        "usergroup": True,
        "avatar": True,
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert "content" not in result
    assert "structuredContent" not in result
    assert result["me"] == [{"uid": "5", "username": "forge"}]


def test_get_profile_includes_advanced_fields_only_when_opted_in_and_allowed(
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
        return {"me": {"uid": 5, "username": "forge", "unreadpms": 3, "unreadalerts": 2}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = get_profile(transport=transport, include_advanced_fields=True, allow_advanced_fields=True)

    me_asks = captured["payload"]["asks"]["me"]
    assert captured["route"] == "/read/me"
    assert me_asks["uid"] is True
    assert me_asks["username"] is True
    assert me_asks["usergroup"] is True
    assert me_asks["avatar"] is True
    assert me_asks["unreadpms"] is True
    assert me_asks["unreadalerts"] is True
    assert me_asks["invisible"] is True
    assert me_asks["totalpms"] is True
    assert me_asks["lastactive"] is True
    assert me_asks["warningpoints"] is True
    assert me_asks["regdate"] is True
    assert set(me_asks.keys()) == {
        "uid",
        "username",
        "usergroup",
        "avatar",
        "unreadpms",
        "unreadalerts",
        "invisible",
        "totalpms",
        "lastactive",
        "warningpoints",
        "regdate",
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert "content" not in result
    assert "structuredContent" not in result
    assert result["me"] == [{"uid": "5", "username": "forge", "unreadpms": "3", "unreadalerts": "2"}]


def test_get_user_defaults_optional_values_and_requests_profile_bundle(
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
        return {"users": {"uid": 5, "username": "forge", "reputation": 42}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = get_user(transport=transport, uid=5, page=None, per_page=None, include_profile_fields=True)

    user_asks = captured["payload"]["asks"]["users"]
    assert captured["route"] == "/read/users"
    assert user_asks["_uid"] == 5
    assert user_asks["_page"] == 1
    assert user_asks["_perpage"] == 30
    assert user_asks["uid"] is True
    assert user_asks["username"] is True
    assert user_asks["avatar"] is True
    assert user_asks["usergroup"] is True
    assert user_asks["usertitle"] is True
    assert user_asks["reputation"] is True
    assert set(user_asks.keys()) == {
        "_uid",
        "_page",
        "_perpage",
        "uid",
        "username",
        "avatar",
        "usergroup",
        "usertitle",
        "reputation",
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result["users"] == [{"uid": "5", "username": "forge", "reputation": "42"}]


def test_list_threads_defaults_optional_values_and_requests_record_fields(
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
        return {"threads": [{"tid": 123, "subject": "Topic"}]}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_threads(transport=transport, fid=375, page=None, per_page=None)

    thread_asks = captured["payload"]["asks"]["threads"]
    assert captured["route"] == "/read/threads"
    assert thread_asks["_fid"] == 375
    assert "_tid" not in thread_asks
    assert thread_asks["_page"] == 1
    assert thread_asks["_perpage"] == 30
    assert thread_asks["tid"] is True
    assert thread_asks["fid"] is True
    assert thread_asks["subject"] is True
    assert thread_asks["dateline"] is True
    assert thread_asks["uid"] is True
    assert thread_asks["username"] is True
    assert thread_asks["views"] is True
    assert thread_asks["lastpost"] is True
    assert thread_asks["sticky"] is True
    assert thread_asks["firstpost"]["pid"] is True
    assert thread_asks["firstpost"]["message"] is True
    assert thread_asks["firstpost"]["author"]["uid"] is True
    assert thread_asks["firstpost"]["author"]["username"] is True
    assert set(thread_asks.keys()) == {
        "_fid",
        "_page",
        "_perpage",
        "tid",
        "fid",
        "subject",
        "dateline",
        "uid",
        "username",
        "views",
        "lastpost",
        "sticky",
        "firstpost",
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert "content" not in result
    assert "structuredContent" not in result
    assert result["threads"] == [{"tid": "123", "subject": "Topic"}]


def test_list_forums_defaults_optional_values_and_requests_forum_card_fields(
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
        return {
            "forums": {
                "fid": 375,
                "name": "General",
                "description": "General discussion",
                "type": "f",
            }
        }

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_forums(transport=transport, fid=375, page=None, per_page=None)

    forum_asks = captured["payload"]["asks"]["forums"]
    assert captured["route"] == "/read/forums"
    assert forum_asks["_fid"] == 375
    assert forum_asks["_page"] == 1
    assert forum_asks["_perpage"] == 30
    assert forum_asks["fid"] is True
    assert forum_asks["name"] is True
    assert forum_asks["description"] is True
    assert forum_asks["type"] is True
    assert set(forum_asks.keys()) == {"_fid", "_page", "_perpage", "fid", "name", "description", "type"}
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert "content" not in result
    assert "structuredContent" not in result
    assert result["forums"] == [
        {"fid": "375", "name": "General", "description": "General discussion", "type": "f"}
    ]


def test_list_posts_defaults_optional_values_and_requests_record_fields(
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
        return {"posts": {"pid": 88, "subject": "No PID filter", "message": "Text"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_posts(
        transport=transport,
        tid=123,
        page=None,
        per_page=None,
        include_post_body=None,
    )

    post_asks = captured["payload"]["asks"]["posts"]
    assert captured["route"] == "/read/posts"
    assert post_asks["_tid"] == 123
    assert "_pid" not in post_asks
    assert post_asks["_page"] == 1
    assert post_asks["_perpage"] == 30
    assert post_asks["pid"] is True
    assert post_asks["tid"] is True
    assert post_asks["uid"] is True
    assert post_asks["fid"] is True
    assert post_asks["dateline"] is True
    assert post_asks["subject"] is True
    assert post_asks["message"] is True
    assert post_asks["edituid"] is True
    assert post_asks["edittime"] is True
    assert post_asks["editreason"] is True
    assert set(post_asks.keys()) == {
        "_tid",
        "_page",
        "_perpage",
        "pid",
        "tid",
        "uid",
        "fid",
        "dateline",
        "subject",
        "message",
        "edituid",
        "edittime",
        "editreason",
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert "content" not in result
    assert "structuredContent" not in result
    assert result["posts"] == [{"pid": "88", "subject": "No PID filter", "message": "Text"}]


def test_list_posts_include_post_body_false_removes_only_message(
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
        return {"posts": {"pid": 99, "subject": "No Body"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_posts(
        transport=transport,
        tid=123,
        page=None,
        per_page=None,
        include_post_body=False,
    )

    post_asks = captured["payload"]["asks"]["posts"]
    assert captured["route"] == "/read/posts"
    assert post_asks["_tid"] == 123
    assert "_pid" not in post_asks
    assert post_asks["_page"] == 1
    assert post_asks["_perpage"] == 30
    assert post_asks["pid"] is True
    assert post_asks["tid"] is True
    assert post_asks["uid"] is True
    assert post_asks["fid"] is True
    assert post_asks["dateline"] is True
    assert post_asks["subject"] is True
    assert "message" not in post_asks
    assert post_asks["edituid"] is True
    assert post_asks["edittime"] is True
    assert post_asks["editreason"] is True
    assert set(post_asks.keys()) == {
        "_tid",
        "_page",
        "_perpage",
        "pid",
        "tid",
        "uid",
        "fid",
        "dateline",
        "subject",
        "edituid",
        "edittime",
        "editreason",
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert "content" not in result
    assert "structuredContent" not in result
    assert result["posts"] == [{"pid": "99", "subject": "No Body"}]


def test_registered_posts_handler_supports_output_modes_and_raw_payload_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[dict[str, Any]]] = {"read": [], "read_raw": []}
    normalized_payload = {
        "posts": [
            {
                "pid": "7",
                "tid": "123",
                "fid": "90",
                "uid": "5",
                "subject": "Hello",
                "message": "Line one\\n  Line two  ",
            }
        ]
    }
    raw_payload = {
        "posts": {
            "pid": 7,
            "tid": 123,
            "fid": 90,
            "uid": 5,
            "subject": "Hello",
            "message": "Line one\\n  Line two  ",
        }
    }

    def _fake_read(self: HFTransport, asks: dict[str, Any], helper: str | None = None) -> dict[str, Any]:
        captured["read"].append({"asks": asks, "helper": helper})
        return normalized_payload

    def _fake_read_raw(self: HFTransport, asks: dict[str, Any], helper: str | None = None) -> dict[str, Any]:
        captured["read_raw"].append({"asks": asks, "helper": helper})
        return raw_payload

    monkeypatch.setattr(HFTransport, "read", _fake_read)
    monkeypatch.setattr(HFTransport, "read_raw", _fake_read_raw)

    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"posts.read"}),
        enabled_parameter_families=frozenset({"selectors.thread", "selectors.post", "filters.pagination", "fields.posts.body"}),
        read_output_defaults=ReadOutputDefaults(mode="structured", include_raw_payload=True),
    )
    policy = CapabilityPolicy(settings)
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    handler = build_core_read_handlers(policy, transport)["posts.read"]

    readable_result = handler(tid=123, output_mode="readable", include_raw_payload=False)
    assert readable_result["structuredContent"] == normalized_payload
    assert readable_result["content"][0]["type"] == "text"
    assert "pid=7" in readable_result["content"][0]["text"]
    assert "tid=123" in readable_result["content"][0]["text"]
    assert "Line one\nLine two" in readable_result["content"][0]["text"]
    assert len(readable_result["content"]) == 1

    structured_result = handler(tid=123, output_mode="structured", include_raw_payload=False)
    assert structured_result["structuredContent"] == normalized_payload
    assert structured_result["content"] == [{"type": "text", "text": "posts.read returned 1 row(s)."}]

    raw_result = handler(tid=123, output_mode="raw", include_raw_payload=False)
    assert raw_result["structuredContent"] == normalized_payload
    assert raw_result["content"][0] == {"type": "text", "text": "posts.read returned 1 row(s)."}
    assert raw_result["content"][1]["type"] == "resource"
    assert raw_result["content"][1]["resource"]["uri"] == "hf-mcp://raw/posts.read"
    assert raw_result["content"][1]["resource"]["mimeType"] == "application/json"
    assert json.loads(raw_result["content"][1]["resource"]["text"]) == raw_payload

    defaults_result = handler(tid=123)
    assert defaults_result["structuredContent"] == normalized_payload
    assert defaults_result["content"][0] == {"type": "text", "text": "posts.read returned 1 row(s)."}
    assert defaults_result["content"][1]["type"] == "resource"
    assert json.loads(defaults_result["content"][1]["resource"]["text"]) == raw_payload

    assert len(captured["read"]) == 2
    assert len(captured["read_raw"]) == 2
    assert all(call["helper"] == "posts" for call in captured["read"])
    assert all(call["helper"] == "posts" for call in captured["read_raw"])
