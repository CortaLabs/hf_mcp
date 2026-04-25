from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.registry import build_registry, get_documented_write_specs, get_tool_spec
from hf_mcp.schemas import build_tool_schema
from hf_mcp.formatting_engine import write_draft_artifact
from hf_mcp.tools.write_documented import (
    build_write_handlers,
    bump_live,
    create_thread_live,
    deposit_live,
    reply_to_thread_live,
    send_live,
    withdraw_live,
)
from hf_mcp.write_preflight import WritePreflightError, validate_write_body


class _CaptureTransport:
    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._responses = responses or {}

    def write(self, *, asks: dict[str, Any], helper: str | None = None) -> dict[str, Any]:
        self.calls.append({"asks": asks, "helper": helper})
        if helper is not None and helper in self._responses:
            return dict(self._responses[helper])
        return {"ok": True, "asks": asks, "helper": helper}


def _flow_actions(result: dict[str, Any]) -> set[tuple[str, tuple[tuple[str, int], ...]]]:
    flow = result.get("_hf_flow")
    assert isinstance(flow, dict)
    next_actions = flow.get("next_actions")
    assert isinstance(next_actions, list)

    actions: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
    for action in next_actions:
        assert isinstance(action, dict)
        tool = action.get("tool")
        arguments = action.get("arguments")
        if not isinstance(tool, str):
            continue
        if not isinstance(arguments, dict):
            continue
        actions.add((tool, tuple(sorted((str(key), int(value)) for key, value in arguments.items()))))
    return actions


def _policy(*, enabled_capabilities: set[str], enabled_parameter_families: set[str]) -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset(enabled_capabilities),
            enabled_parameter_families=frozenset(enabled_parameter_families),
        )
    )


def test_write_specs_include_only_concrete_core_rows_for_absence_path() -> None:
    specs = get_documented_write_specs()
    assert {spec.tool_name for spec in specs} == {
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
    }
    forbidden = {"contracts.write", "sigmarket.write", "admin.high_risk.write"}
    assert forbidden.isdisjoint({spec.tool_name for spec in build_registry()})


def test_build_write_handlers_registers_only_core_rows_allowed_by_policy() -> None:
    policy = _policy(
        enabled_capabilities={"threads.create", "posts.reply", "bytes.transfer", "contracts.write"},
        enabled_parameter_families={
            "selectors.forum",
            "selectors.thread",
            "selectors.bytes",
            "writes.content",
            "writes.bytes",
            "confirm.live",
        },
    )
    handlers = build_write_handlers(policy, _CaptureTransport())

    assert set(handlers) == {"threads.create", "posts.reply", "bytes.transfer"}
    assert "contracts.write" not in handlers


@pytest.mark.parametrize(
    ("call", "tool_name"),
    [
        (lambda transport: create_thread_live(
            transport=transport,
            fid=10,
            subject="subject",
            message="message",
            confirm_live=False,
        ), "threads.create"),
        (lambda transport: reply_to_thread_live(
            transport=transport,
            tid=20,
            message="message",
            confirm_live=False,
        ), "posts.reply"),
        (lambda transport: send_live(
            transport=transport,
            target_uid=30,
            amount=4,
            confirm_live=False,
        ), "bytes.transfer"),
        (lambda transport: deposit_live(transport=transport, amount=7, confirm_live=False), "bytes.deposit"),
        (lambda transport: withdraw_live(transport=transport, amount=8, confirm_live=False), "bytes.withdraw"),
        (lambda transport: bump_live(transport=transport, tid=99, confirm_live=False), "bytes.bump"),
    ],
)
def test_core_write_helpers_fail_closed_without_confirm_live(
    call: Any,
    tool_name: str,
) -> None:
    transport = _CaptureTransport()

    with pytest.raises(PermissionError, match=tool_name):
        call(transport)

    assert transport.calls == []


def test_bound_write_handlers_still_fail_closed_without_confirm_live() -> None:
    policy = _policy(
        enabled_capabilities={"threads.create", "posts.reply"},
        enabled_parameter_families={"selectors.forum", "selectors.thread", "writes.content", "confirm.live"},
    )
    transport = _CaptureTransport()
    handlers = build_write_handlers(policy, transport)

    with pytest.raises(PermissionError, match="posts.reply"):
        handlers["posts.reply"](tid=77, message="Denied", message_format="mycode", confirm_live=False)

    assert transport.calls == []


def test_create_thread_live_shapes_payload_and_helper_path() -> None:
    transport = _CaptureTransport()

    result = create_thread_live(
        transport=transport,
        fid=12,
        subject="Sell",
        message="Details",
        confirm_live=True,
    )

    assert transport.calls == [
        {
            "asks": {"threads": {"_fid": 12, "_subject": "Sell", "_message": "Details"}},
            "helper": "threads",
        }
    ]
    assert result["helper"] == "threads"


def test_reply_and_bytes_write_helpers_shape_payloads_truthfully() -> None:
    transport = _CaptureTransport()

    reply_to_thread_live(transport=transport, tid=44, message="Hi", confirm_live=True)
    send_live(transport=transport, target_uid=55, amount=100, reason="tip", pid=99, confirm_live=True)
    deposit_live(transport=transport, amount=60, confirm_live=True)
    withdraw_live(transport=transport, amount=20, confirm_live=True)
    bump_live(transport=transport, tid=77, confirm_live=True)

    assert transport.calls == [
        {"asks": {"posts": {"_tid": 44, "_message": "Hi"}}, "helper": "posts"},
        {"asks": {"bytes": {"_uid": 55, "_amount": 100, "_reason": "tip", "_pid": 99}}, "helper": "bytes"},
        {"asks": {"bytes": {"_deposit": 60}}, "helper": "bytes/deposit"},
        {"asks": {"bytes": {"_withdraw": 20}}, "helper": "bytes/withdraw"},
        {"asks": {"bytes": {"_bump": 77}}, "helper": "bytes/bump"},
    ]


def test_confirmed_stubbed_writes_attach_post_action_hf_flow_metadata() -> None:
    transport = _CaptureTransport(
        responses={
            "threads": {"threads": [{"tid": "6324346", "fid": "375"}], "ok": True},
            "posts": {"posts": [{"tid": "6324346", "pid": "9001"}], "ok": True},
            "bytes": {"bytes": [{"uid": "2047020"}], "ok": True},
            "bytes/deposit": {"ok": True},
        }
    )

    thread_result = create_thread_live(
        transport=transport,
        fid=375,
        subject="Thread title",
        message="Thread body",
        confirm_live=True,
    )
    thread_actions = _flow_actions(thread_result)
    assert ("threads.read", (("tid", 6324346),)) in thread_actions
    assert ("posts.read", (("tid", 6324346),)) in thread_actions
    assert ("forums.read", (("fid", 375),)) in thread_actions

    reply_result = reply_to_thread_live(
        transport=transport,
        tid=6324346,
        message="Reply body",
        confirm_live=True,
    )
    reply_actions = _flow_actions(reply_result)
    assert ("posts.read", (("tid", 6324346),)) in reply_actions

    transfer_result = send_live(
        transport=transport,
        target_uid=2047020,
        amount=50,
        confirm_live=True,
    )
    transfer_actions = _flow_actions(transfer_result)
    assert ("bytes.read", (("uid", 2047020),)) in transfer_actions
    assert ("users.read", (("uid", 2047020),)) in transfer_actions

    no_id_result = deposit_live(
        transport=transport,
        amount=12,
        confirm_live=True,
    )
    flow = no_id_result.get("_hf_flow")
    assert isinstance(flow, dict)
    assert flow.get("next_actions") == []


def test_write_helpers_decode_html_entities_in_mycode_text() -> None:
    transport = _CaptureTransport()

    create_thread_live(
        transport=transport,
        fid=12,
        subject="Release &quot;0.2&quot;",
        message='[code]{&quot;mode&quot;:&quot;raw&quot;}[/code] and `output_mode=&quot;structured&quot;`',
        confirm_live=True,
    )
    reply_to_thread_live(
        transport=transport,
        tid=44,
        message='[code]{&quot;posts&quot;:[{&quot;pid&quot;:&quot;62946370&quot;}]}[/code]',
        confirm_live=True,
    )

    assert transport.calls[0] == {
        "asks": {
            "threads": {
                "_fid": 12,
                "_subject": 'Release "0.2"',
                "_message": '[code]{"mode":"raw"}[/code] and `output_mode="structured"`',
            }
        },
        "helper": "threads",
    }
    assert transport.calls[1] == {
        "asks": {
            "posts": {
                "_tid": 44,
                "_message": '[code]{"posts":[{"pid":"62946370"}]}[/code]',
            }
        },
        "helper": "posts",
    }


def test_write_helpers_can_convert_markdown_messages_to_mycode() -> None:
    transport = _CaptureTransport()

    create_thread_live(
        transport=transport,
        fid=12,
        subject="Markdown",
        message="**Bold**\n\n- one\n- two\n\n[site](https://example.test)",
        message_format="markdown",
        confirm_live=True,
    )
    reply_to_thread_live(
        transport=transport,
        tid=44,
        message="> quoted\n\n```json\n{\"ok\":true}\n```",
        message_format="markdown",
        confirm_live=True,
    )

    assert transport.calls == [
        {
            "asks": {
                "threads": {
                    "_fid": 12,
                    "_subject": "Markdown",
                    "_message": (
                        "[b]Bold[/b]\n\n"
                        "[list]\n"
                        "[*] one\n"
                        "[*] two\n"
                        "[/list]\n\n"
                        "[url=https://example.test]site[/url]"
                    ),
                }
            },
            "helper": "threads",
        },
        {
            "asks": {
                "posts": {
                    "_tid": 44,
                    "_message": "[quote]quoted[/quote]\n\n[code]{\"ok\":true}\n[/code]",
                }
            },
            "helper": "posts",
        },
    ]


def test_reply_can_publish_cached_preflight_draft_by_id_without_resending_message(tmp_path: Path) -> None:
    transport = _CaptureTransport()
    artifact = write_draft_artifact("**Approved**\n\n- cached draft body", "markdown", draft_dir=tmp_path)

    reply_to_thread_live(
        transport=transport,
        tid=44,
        draft_id=artifact.draft_id,
        confirm_live=True,
        draft_dir=tmp_path,
    )

    assert transport.calls == [
        {
            "asks": {
                "posts": {
                    "_tid": 44,
                    "_message": "[b]Approved[/b]\n\n[list]\n[*] cached draft body\n[/list]",
                }
            },
            "helper": "posts",
        }
    ]


@pytest.mark.parametrize("selector", ["draft_id", "draft_path"])
def test_thread_create_can_publish_cached_preflight_draft_from_configured_dir(
    tmp_path: Path,
    selector: str,
) -> None:
    transport = _CaptureTransport()
    artifact = write_draft_artifact("**Approved**\n\n- thread draft body", "markdown", draft_dir=tmp_path)
    kwargs: dict[str, Any]
    if selector == "draft_id":
        kwargs = {"draft_id": artifact.draft_id}
    else:
        kwargs = {"draft_path": str(artifact.path)}

    create_thread_live(
        transport=transport,
        fid=12,
        subject="Draft Thread",
        confirm_live=True,
        draft_dir=tmp_path,
        **kwargs,
    )

    assert transport.calls == [
        {
            "asks": {
                "threads": {
                    "_fid": 12,
                    "_subject": "Draft Thread",
                    "_message": "[b]Approved[/b]\n\n[list]\n[*] thread draft body\n[/list]",
                }
            },
            "helper": "threads",
        }
    ]


def test_write_helpers_reject_message_and_draft_together_before_transport() -> None:
    transport = _CaptureTransport()
    artifact = write_draft_artifact("approved body", "markdown")

    with pytest.raises(ValueError, match="either message or draft"):
        reply_to_thread_live(
            transport=transport,
            tid=44,
            message="duplicate",
            draft_id=artifact.draft_id,
            confirm_live=True,
        )

    assert transport.calls == []


def test_draft_lookup_failure_never_calls_transport(tmp_path: Path) -> None:
    transport = _CaptureTransport()

    with pytest.raises(FileNotFoundError, match="Draft artifact not found"):
        reply_to_thread_live(
            transport=transport,
            tid=44,
            draft_id="a" * 32,
            confirm_live=True,
            draft_dir=tmp_path,
        )

    assert transport.calls == []


def test_draft_loaded_preflight_failure_never_calls_transport(tmp_path: Path) -> None:
    transport = _CaptureTransport()
    artifact = write_draft_artifact("[list]\n[*] item", "markdown", draft_dir=tmp_path)

    with pytest.raises(WritePreflightError, match="unclosed list"):
        reply_to_thread_live(
            transport=transport,
            tid=44,
            draft_id=artifact.draft_id,
            confirm_live=True,
            draft_dir=tmp_path,
        )

    assert transport.calls == []


def test_draft_backed_publish_requires_confirm_live_before_transport(tmp_path: Path) -> None:
    transport = _CaptureTransport()
    artifact = write_draft_artifact("approved body", "markdown", draft_dir=tmp_path)

    with pytest.raises(PermissionError, match="posts.reply"):
        reply_to_thread_live(
            transport=transport,
            tid=44,
            draft_id=artifact.draft_id,
            confirm_live=False,
            draft_dir=tmp_path,
        )

    assert transport.calls == []


def test_markdown_write_preflight_blocks_malformed_generated_mycode_before_transport() -> None:
    transport = _CaptureTransport()

    with pytest.raises(WritePreflightError, match="unclosed list"):
        reply_to_thread_live(
            transport=transport,
            tid=44,
            message="[list]\n[*] item",
            message_format="markdown",
            confirm_live=True,
        )

    assert transport.calls == []


def test_write_preflight_rejects_nested_code_blocks_and_placeholder_leaks() -> None:
    with pytest.raises(WritePreflightError, match="nested code blocks"):
        validate_write_body("[code]outer [code]inner[/code][/code]", source_format="markdown")

    with pytest.raises(WritePreflightError, match="internal formatter placeholder"):
        validate_write_body("before \x00INLCODE0\x00 after", source_format="markdown")


def test_write_preflight_allows_balanced_markdown_conversion_output() -> None:
    validate_write_body(
        (
            "[b]Update[/b]\n\n"
            "[list]\n"
            "[*] [code]body_format=\"markdown\"[/code]\n"
            "[*] [url=https://github.com/CortaLabs/hf_mcp]Project[/url]\n"
            "[/list]\n\n"
            "[code]{\"tool\":\"posts.reply\"}[/code]"
        ),
        source_format="markdown",
    )


def test_schema_surface_kwargs_invoke_core_write_handlers_truthfully() -> None:
    policy = _policy(
        enabled_capabilities={
            "threads.create",
            "posts.reply",
            "bytes.transfer",
            "bytes.deposit",
            "bytes.withdraw",
            "bytes.bump",
        },
        enabled_parameter_families={"selectors.forum", "selectors.thread", "selectors.bytes", "writes.content", "writes.bytes", "confirm.live"},
    )
    transport = _CaptureTransport()
    handlers = build_write_handlers(policy, transport)

    handlers["threads.create"](fid=101, subject="Title", message="Body", message_format="mycode", confirm_live=True)
    handlers["posts.reply"](tid=202, message="Reply", message_format="mycode", confirm_live=True)
    handlers["bytes.transfer"](target_uid=303, amount=4, confirm_live=True)
    handlers["bytes.deposit"](amount=5, confirm_live=True)
    handlers["bytes.withdraw"](amount=6, confirm_live=True)
    handlers["bytes.bump"](tid=707, confirm_live=True)

    assert transport.calls == [
        {"asks": {"threads": {"_fid": 101, "_subject": "Title", "_message": "Body"}}, "helper": "threads"},
        {"asks": {"posts": {"_tid": 202, "_message": "Reply"}}, "helper": "posts"},
        {"asks": {"bytes": {"_uid": 303, "_amount": 4}}, "helper": "bytes"},
        {"asks": {"bytes": {"_deposit": 5}}, "helper": "bytes/deposit"},
        {"asks": {"bytes": {"_withdraw": 6}}, "helper": "bytes/withdraw"},
        {"asks": {"bytes": {"_bump": 707}}, "helper": "bytes/bump"},
    ]


def test_handlers_accept_kwargs_generated_from_repaired_write_schemas() -> None:
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
    transport = _CaptureTransport()
    handlers = build_write_handlers(policy, transport)

    schema_kwargs: dict[str, dict[str, Any]] = {
        "threads.create": {
            "fid": 1001,
            "subject": "T",
            "message": "M",
            "draft_id": None,
            "draft_path": None,
            "message_format": "mycode",
            "confirm_live": True,
        },
        "posts.reply": {
            "tid": 1002,
            "message": "R",
            "draft_id": None,
            "draft_path": None,
            "message_format": "mycode",
            "confirm_live": True,
        },
        "bytes.transfer": {"target_uid": 1003, "amount": 10, "confirm_live": True},
        "bytes.deposit": {"amount": 11, "confirm_live": True},
        "bytes.withdraw": {"amount": 12, "confirm_live": True},
        "bytes.bump": {"tid": 1004, "confirm_live": True},
    }

    for tool_name, kwargs in schema_kwargs.items():
        schema = build_tool_schema(get_tool_spec(tool_name), policy)
        assert set(kwargs) == set(schema["properties"])
        handlers[tool_name](**kwargs)

    assert transport.calls == [
        {"asks": {"threads": {"_fid": 1001, "_subject": "T", "_message": "M"}}, "helper": "threads"},
        {"asks": {"posts": {"_tid": 1002, "_message": "R"}}, "helper": "posts"},
        {"asks": {"bytes": {"_uid": 1003, "_amount": 10}}, "helper": "bytes"},
        {"asks": {"bytes": {"_deposit": 11}}, "helper": "bytes/deposit"},
        {"asks": {"bytes": {"_withdraw": 12}}, "helper": "bytes/withdraw"},
        {"asks": {"bytes": {"_bump": 1004}}, "helper": "bytes/bump"},
    ]
