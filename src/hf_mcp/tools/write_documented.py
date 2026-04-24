from __future__ import annotations

from collections.abc import Callable
import html
from pathlib import Path
from typing import Any

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.formatting_engine import read_draft_artifact, prepare_formatting_report
from hf_mcp.mycode import coerce_message_format
from hf_mcp.registry import get_documented_write_specs
from hf_mcp.transport import HFTransport
from hf_mcp.write_preflight import WritePreflightError, validate_write_body

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


def _normalize_write_text(value: str, message_format: str = "mycode") -> str:
    source_format = coerce_message_format(message_format, field_name="message_format")
    normalized = html.unescape(value)
    report = prepare_formatting_report(normalized, source_format)
    for issue in report.issues:
        if issue.severity == "error":
            raise WritePreflightError(issue.message)
    validate_write_body(report.mycode, source_format=source_format)
    return report.mycode


def _resolve_message_text(
    *,
    message: str | None,
    message_format: str,
    draft_id: str | None,
    draft_path: str | None,
    draft_dir: str | Path | None,
) -> str:
    has_message = message is not None and message != ""
    has_draft = draft_id is not None or draft_path is not None
    if has_message and has_draft:
        raise ValueError("Provide either message or draft_id/draft_path, not both.")
    if not has_message and not has_draft:
        raise ValueError("A message, draft_id, or draft_path is required.")
    if has_message:
        return _normalize_write_text(message, message_format)

    artifact = read_draft_artifact(draft_id=draft_id, draft_path=draft_path, draft_dir=draft_dir)
    for issue in artifact.report.issues:
        if issue.severity == "error":
            raise WritePreflightError(issue.message)
    validate_write_body(artifact.report.mycode, source_format=artifact.report.source_format)
    return artifact.report.mycode


def create_thread_live(
    *,
    transport: HFTransport,
    fid: int,
    subject: str,
    message: str | None = None,
    confirm_live: bool,
    message_format: str = "mycode",
    draft_id: str | None = None,
    draft_path: str | None = None,
    draft_dir: str | Path | None = None,
) -> dict[str, Any]:
    _require_confirm_live("threads.create", confirm_live)
    asks = {
        "threads": {
            "_fid": fid,
            "_subject": _normalize_write_text(subject),
            "_message": _resolve_message_text(
                message=message,
                message_format=message_format,
                draft_id=draft_id,
                draft_path=draft_path,
                draft_dir=draft_dir,
            ),
        }
    }
    return transport.write(asks=asks, helper="threads")


def reply_to_thread_live(
    *,
    transport: HFTransport,
    tid: int,
    message: str | None = None,
    confirm_live: bool,
    message_format: str = "mycode",
    draft_id: str | None = None,
    draft_path: str | None = None,
    draft_dir: str | Path | None = None,
) -> dict[str, Any]:
    _require_confirm_live("posts.reply", confirm_live)
    asks = {
        "posts": {
            "_tid": tid,
            "_message": _resolve_message_text(
                message=message,
                message_format=message_format,
                draft_id=draft_id,
                draft_path=draft_path,
                draft_dir=draft_dir,
            ),
        }
    }
    return transport.write(asks=asks, helper="posts")


def send_live(
    *,
    transport: HFTransport,
    target_uid: int,
    amount: int,
    confirm_live: bool,
) -> dict[str, Any]:
    _require_confirm_live("bytes.transfer", confirm_live)
    asks = {"bytes": {"_to_uid": target_uid, "_amount": amount}}
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


def build_write_handlers(
    policy: CapabilityPolicy,
    transport: HFTransport,
    *,
    draft_dir: str | Path | None = None,
) -> dict[str, WriteHandler]:
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
            if handler in (create_thread_live, reply_to_thread_live):
                return handler(transport=transport, draft_dir=draft_dir, **kwargs)
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
