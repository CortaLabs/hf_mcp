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
from hf_mcp.registry import get_documented_write_specs, get_tool_spec
from hf_mcp.tools.write_documented import (
    PENDING_LATER_LANE_WRITE_ROWS,
    build_write_handlers,
    bump_live,
    create_thread_live,
    deposit_live,
    reply_to_thread_live,
    send_live,
    withdraw_live,
)


class _CaptureTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def write(self, *, asks: dict[str, Any], helper: str | None = None) -> dict[str, Any]:
        self.calls.append({"asks": asks, "helper": helper})
        return {"ok": True, "asks": asks, "helper": helper}


def _policy(*, enabled_capabilities: set[str], enabled_parameter_families: set[str]) -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset(enabled_capabilities),
            enabled_parameter_families=frozenset(enabled_parameter_families),
        )
    )


def test_write_specs_include_core_and_later_lane_rows() -> None:
    specs = get_documented_write_specs()
    assert {spec.tool_name for spec in specs} == {
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
        "contracts.write",
        "sigmarket.write",
        "admin.high_risk.write",
    }


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
    send_live(transport=transport, target_uid=55, amount=100, confirm_live=True)
    deposit_live(transport=transport, amount=60, confirm_live=True)
    withdraw_live(transport=transport, amount=20, confirm_live=True)
    bump_live(transport=transport, tid=77, confirm_live=True)

    assert transport.calls == [
        {"asks": {"posts": {"_tid": 44, "_message": "Hi"}}, "helper": "posts"},
        {"asks": {"bytes": {"_uid": 55, "_amount": 100}}, "helper": "bytes"},
        {"asks": {"bytes": {"_amount": 60}}, "helper": "bytes/deposit"},
        {"asks": {"bytes": {"_amount": 20}}, "helper": "bytes/withdraw"},
        {"asks": {"bytes": {"_tid": 77}}, "helper": "bytes/bump"},
    ]


def test_later_lane_write_rows_remain_explicitly_blocked_without_invented_calls() -> None:
    assert set(PENDING_LATER_LANE_WRITE_ROWS) == {
        "contracts.write",
        "sigmarket.write",
        "admin.high_risk.write",
    }

    for tool_name in PENDING_LATER_LANE_WRITE_ROWS:
        spec = get_tool_spec(tool_name)
        assert spec.operation == "write"
        assert spec.transport_kind == "helper"
        assert "confirm.live" in spec.parameter_families

    policy = _policy(
        enabled_capabilities={"contracts.write", "sigmarket.write", "admin.high_risk.write"},
        enabled_parameter_families={"writes.content", "confirm.live", "selectors.contract", "selectors.sigmarket"},
    )
    handlers = build_write_handlers(policy, _CaptureTransport())
    assert handlers == {}


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

    handlers["threads.create"](fid=101, subject="Title", message="Body", confirm_live=True)
    handlers["posts.reply"](tid=202, message="Reply", confirm_live=True)
    handlers["bytes.transfer"](target_uid=303, amount=4, confirm_live=True)
    handlers["bytes.deposit"](amount=5, confirm_live=True)
    handlers["bytes.withdraw"](amount=6, confirm_live=True)
    handlers["bytes.bump"](tid=707, confirm_live=True)

    assert transport.calls == [
        {"asks": {"threads": {"_fid": 101, "_subject": "Title", "_message": "Body"}}, "helper": "threads"},
        {"asks": {"posts": {"_tid": 202, "_message": "Reply"}}, "helper": "posts"},
        {"asks": {"bytes": {"_uid": 303, "_amount": 4}}, "helper": "bytes"},
        {"asks": {"bytes": {"_amount": 5}}, "helper": "bytes/deposit"},
        {"asks": {"bytes": {"_amount": 6}}, "helper": "bytes/withdraw"},
        {"asks": {"bytes": {"_tid": 707}}, "helper": "bytes/bump"},
    ]
