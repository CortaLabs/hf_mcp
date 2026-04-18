from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.registry import get_documented_write_specs
from hf_mcp.transport import HFTransport

WriteHandler = Callable[..., dict[str, Any]]


PENDING_LATER_LANE_WRITE_ROWS: dict[str, str] = {
    "contracts.write": "Documented later-lane write helper is intentionally blocked pending named helper proof.",
    "sigmarket.write": "Documented later-lane write helper is intentionally blocked pending named helper proof.",
    "admin.high_risk.write": "Documented later-lane write helper is intentionally blocked pending named helper proof.",
}


def _require_confirm_live(tool_name: str, confirm_live: bool) -> None:
    if confirm_live:
        return
    raise PermissionError(
        f"Tool '{tool_name}' performs a live remote write and requires confirm_live=True."
    )


def create_thread_live(
    *,
    transport: HFTransport,
    fid: int,
    subject: str,
    message: str,
    confirm_live: bool,
) -> dict[str, Any]:
    _require_confirm_live("threads.create", confirm_live)
    asks = {"threads": {"_fid": fid, "_subject": subject, "_message": message}}
    return transport.write(asks=asks, helper="threads")


def reply_to_thread_live(
    *,
    transport: HFTransport,
    tid: int,
    message: str,
    confirm_live: bool,
) -> dict[str, Any]:
    _require_confirm_live("posts.reply", confirm_live)
    asks = {"posts": {"_tid": tid, "_message": message}}
    return transport.write(asks=asks, helper="posts")


def send_live(
    *,
    transport: HFTransport,
    target_uid: int,
    amount: int,
    confirm_live: bool,
) -> dict[str, Any]:
    _require_confirm_live("bytes.transfer", confirm_live)
    asks = {"bytes": {"_uid": target_uid, "_amount": amount}}
    return transport.write(asks=asks, helper="bytes")


def deposit_live(
    *,
    transport: HFTransport,
    amount: int,
    confirm_live: bool,
) -> dict[str, Any]:
    _require_confirm_live("bytes.deposit", confirm_live)
    asks = {"bytes": {"_amount": amount}}
    return transport.write(asks=asks, helper="bytes/deposit")


def withdraw_live(
    *,
    transport: HFTransport,
    amount: int,
    confirm_live: bool,
) -> dict[str, Any]:
    _require_confirm_live("bytes.withdraw", confirm_live)
    asks = {"bytes": {"_amount": amount}}
    return transport.write(asks=asks, helper="bytes/withdraw")


def bump_live(
    *,
    transport: HFTransport,
    tid: int,
    confirm_live: bool,
) -> dict[str, Any]:
    _require_confirm_live("bytes.bump", confirm_live)
    asks = {"bytes": {"_tid": tid}}
    return transport.write(asks=asks, helper="bytes/bump")


def build_write_handlers(policy: CapabilityPolicy, transport: HFTransport) -> dict[str, WriteHandler]:
    tool_handlers: dict[str, Callable[..., dict[str, Any]]] = {
        "threads.create": create_thread_live,
        "posts.reply": reply_to_thread_live,
        "bytes.transfer": send_live,
        "bytes.deposit": deposit_live,
        "bytes.withdraw": withdraw_live,
        "bytes.bump": bump_live,
    }

    def _bind_handler(handler: Callable[..., dict[str, Any]]) -> WriteHandler:
        def _call(**kwargs: Any) -> dict[str, Any]:
            return handler(transport=transport, **kwargs)

        return _call

    handlers: dict[str, WriteHandler] = {}
    for spec in get_documented_write_specs():
        if not policy.can_register(spec.tool_name):
            continue
        handler = tool_handlers.get(spec.tool_name)
        if handler is None:
            continue
        handlers[spec.tool_name] = _bind_handler(handler)
    return handlers


__all__ = [
    "PENDING_LATER_LANE_WRITE_ROWS",
    "build_write_handlers",
    "bump_live",
    "create_thread_live",
    "deposit_live",
    "reply_to_thread_live",
    "send_live",
    "withdraw_live",
]
