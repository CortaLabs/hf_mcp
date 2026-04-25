from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, cast

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.normalizers import format_body_fields, normalize_response
from hf_mcp.output_modes import ReadOutputMode, resolve_read_output_defaults
from hf_mcp.registry import get_core_read_specs
from hf_mcp.transport import HFTransport

ReadHandler = Callable[..., dict[str, Any]]
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 30
_DEFAULT_THREAD_FIELDS = (
    "tid",
    "fid",
    "subject",
    "dateline",
    "uid",
    "username",
    "views",
    "lastpost",
    "sticky",
)
_DEFAULT_THREAD_FIRSTPOST_FIELDS = {
    "pid": True,
    "message": True,
    "author": {
        "uid": True,
        "username": True,
    },
}
_DEFAULT_POST_FIELDS = (
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
)
_DEFAULT_FORUM_FIELDS = ("fid", "name", "description", "type")
_DEFAULT_ME_BASIC_FIELDS = (
    "uid",
    "username",
    "usergroup",
    "displaygroup",
    "additionalgroups",
    "postnum",
    "awards",
    "bytes",
    "vault",
    "threadnum",
    "avatar",
    "avatardimensions",
    "avatartype",
    "lastvisit",
    "usertitle",
    "website",
    "timeonline",
    "reputation",
    "referrals",
)
_DEFAULT_ME_ADVANCED_FIELDS = (
    "unreadpms",
    "invisible",
    "totalpms",
    "lastactive",
    "warningpoints",
)
_DEFAULT_USER_PROFILE_FIELDS = (
    "uid",
    "username",
    "usergroup",
    "displaygroup",
    "additionalgroups",
    "postnum",
    "awards",
    "myps",
    "threadnum",
    "avatar",
    "avatardimensions",
    "avatartype",
    "usertitle",
    "website",
    "timeonline",
    "reputation",
    "referrals",
)


def _build_me_asks(
    *,
    include_basic_fields: bool | None,
    include_advanced_fields: bool | None,
    allow_advanced_fields: bool,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {"me": {}}
    if include_basic_fields is not False:
        for field_name in _DEFAULT_ME_BASIC_FIELDS:
            asks["me"][field_name] = True
    if include_advanced_fields is True and allow_advanced_fields:
        for field_name in _DEFAULT_ME_ADVANCED_FIELDS:
            asks["me"][field_name] = True
    return asks


def _build_users_asks(
    *,
    uid: int,
    page: int | None,
    per_page: int | None,
    include_profile_fields: bool | None,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {
        "users": {"_uid": uid, "_page": _coerce_page(page), "_perpage": _coerce_per_page(per_page)},
    }
    if include_profile_fields is not False:
        for field_name in _DEFAULT_USER_PROFILE_FIELDS:
            asks["users"][field_name] = True
    return asks


def _build_forums_asks(*, fid: int, page: int | None, per_page: int | None) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {
        "forums": {"_fid": fid, "_page": _coerce_page(page), "_perpage": _coerce_per_page(per_page)}
    }
    for field_name in _DEFAULT_FORUM_FIELDS:
        asks["forums"][field_name] = True
    return asks


def _build_threads_asks(
    *,
    fid: int | None,
    tid: int | None,
    uid: int | None,
    page: int | None,
    per_page: int | None,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {"threads": {}}
    if fid is not None:
        asks["threads"]["_fid"] = fid
    if tid is not None:
        asks["threads"]["_tid"] = tid
    if uid is not None:
        asks["threads"]["_uid"] = uid
    if "_fid" not in asks["threads"] and "_tid" not in asks["threads"] and "_uid" not in asks["threads"]:
        raise ValueError("threads.read requires at least one selector: fid, tid, or uid")
    asks["threads"]["_page"] = _coerce_page(page)
    asks["threads"]["_perpage"] = _coerce_per_page(per_page)
    for field_name in _DEFAULT_THREAD_FIELDS:
        asks["threads"][field_name] = True
    asks["threads"]["firstpost"] = {
        "pid": _DEFAULT_THREAD_FIRSTPOST_FIELDS["pid"],
        "message": _DEFAULT_THREAD_FIRSTPOST_FIELDS["message"],
        "author": dict(_DEFAULT_THREAD_FIRSTPOST_FIELDS["author"]),
    }
    return asks


def _build_posts_asks(
    *,
    tid: int | None,
    pid: int | None,
    uid: int | None,
    page: int | None,
    per_page: int | None,
    include_post_body: bool | None,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {"posts": {}}
    if tid is not None:
        asks["posts"]["_tid"] = tid
    if pid is not None:
        asks["posts"]["_pid"] = pid
    if uid is not None:
        asks["posts"]["_uid"] = uid
    if "_pid" not in asks["posts"] and "_tid" not in asks["posts"] and "_uid" not in asks["posts"]:
        raise ValueError("posts.read requires at least one selector: pid, tid, or uid")
    asks["posts"]["_page"] = _coerce_page(page)
    asks["posts"]["_perpage"] = _coerce_per_page(per_page)
    for field_name in _DEFAULT_POST_FIELDS:
        asks["posts"][field_name] = True
    if include_post_body is False:
        asks["posts"].pop("message", None)
    return asks


def get_profile(
    *,
    transport: HFTransport,
    include_basic_fields: bool | None = True,
    include_advanced_fields: bool | None = False,
    allow_advanced_fields: bool = True,
) -> dict[str, Any]:
    asks = _build_me_asks(
        include_basic_fields=include_basic_fields,
        include_advanced_fields=include_advanced_fields,
        allow_advanced_fields=allow_advanced_fields,
    )
    return transport.read(asks=asks, helper="me")


def get_user(
    *,
    transport: HFTransport,
    uid: int,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
    include_profile_fields: bool | None = True,
) -> dict[str, Any]:
    asks = _build_users_asks(
        uid=uid,
        page=page,
        per_page=per_page,
        include_profile_fields=include_profile_fields,
    )
    return transport.read(asks=asks, helper="users")


def list_forums(
    *,
    transport: HFTransport,
    fid: int,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
) -> dict[str, Any]:
    asks = _build_forums_asks(fid=fid, page=page, per_page=per_page)
    return transport.read(asks=asks, helper="forums")


def list_threads(
    *,
    transport: HFTransport,
    fid: int | None = None,
    tid: int | None = None,
    uid: int | None = None,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
) -> dict[str, Any]:
    asks = _build_threads_asks(fid=fid, tid=tid, uid=uid, page=page, per_page=per_page)
    return transport.read(asks=asks, helper="threads")


def list_posts(
    *,
    transport: HFTransport,
    tid: int | None = None,
    pid: int | None = None,
    uid: int | None = None,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
    include_post_body: bool | None = True,
) -> dict[str, Any]:
    asks = _build_posts_asks(
        tid=tid,
        pid=pid,
        uid=uid,
        page=page,
        per_page=per_page,
        include_post_body=include_post_body,
    )
    return transport.read(asks=asks, helper="posts")


def _coerce_page(page: int | None) -> int:
    return DEFAULT_PAGE if page is None else page


def _coerce_per_page(per_page: int | None) -> int:
    return DEFAULT_PER_PAGE if per_page is None else per_page


def _line_for_entry(entry: Mapping[str, Any], *, primary_keys: tuple[str, ...], message_key: str | None = None) -> str:
    segments: list[str] = []
    for key in primary_keys:
        value = entry.get(key)
        if value not in (None, ""):
            segments.append(f"{key}={value}")
    if message_key is not None:
        message_value = entry.get(message_key)
        if isinstance(message_value, str) and message_value:
            normalized = _normalize_message_text(message_value)
            if normalized:
                segments.append(f"{message_key}={normalized}")
    return ", ".join(segments) if segments else "entry"


def _normalize_message_text(message: str) -> str:
    cleaned = message.replace("\\r\\n", "\n").replace("\\n", "\n")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in cleaned.split("\n")]
    return "\n".join(lines).strip()


def _as_rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        return [value]
    return []


def _build_content_summary(tool_name: str, payload: Mapping[str, Any], mode: ReadOutputMode) -> str:
    root_key = tool_name.split(".", 1)[0]
    rows = _as_rows(payload, root_key)
    if mode != "readable":
        return f"{tool_name} returned {len(rows)} row(s)."

    if tool_name == "me.read":
        if not rows:
            return "me.read returned 0 row(s)."
        profile_summary_keys = (
            "uid",
            "username",
            "usergroup",
            "usertitle",
            "postnum",
            "threadnum",
            "reputation",
            "bytes",
        )
        return (
            "me.read profile: "
            f"{_line_for_entry(rows[0], primary_keys=profile_summary_keys)}"
        )
    if tool_name == "users.read":
        return _build_rows_summary("users.read", rows, primary_keys=("uid", "username", "reputation"))
    if tool_name == "forums.read":
        return _build_rows_summary("forums.read", rows, primary_keys=("fid", "name", "type"))
    if tool_name == "threads.read":
        return _build_threads_readable_content(rows)
    if tool_name == "posts.read":
        return _build_rows_summary(
            "posts.read",
            rows,
            primary_keys=("pid", "tid", "fid", "uid", "subject"),
            message_key="message",
        )
    return f"{tool_name} returned {len(rows)} row(s)."


def _build_threads_readable_content(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return "threads.read returned 0 thread(s)."

    lines = [f"threads.read returned {len(rows)} thread(s)."]
    for index, row in enumerate(rows, start=1):
        subject = row.get("subject")
        title = subject if isinstance(subject, str) and subject else f"Thread {index}"
        lines.extend(("", f"## {title}"))

        thread_fields = _flatten_readable_fields(row, exclude_keys=frozenset({"firstpost"}))
        if thread_fields:
            lines.extend(("", "### Thread fields"))
            lines.extend(f"- {key}: {value}" for key, value in thread_fields)

        firstpost = row.get("firstpost")
        if not isinstance(firstpost, Mapping):
            continue

        firstpost_fields = _flatten_readable_fields(firstpost, prefix="firstpost", exclude_keys=frozenset({"message"}))
        if firstpost_fields:
            lines.extend(("", "### First post fields"))
            lines.extend(f"- {key}: {value}" for key, value in firstpost_fields)

        message_value = firstpost.get("message")
        if isinstance(message_value, str) and message_value:
            normalized = _normalize_message_text(message_value)
            if normalized:
                lines.extend(("", "### Thread body", "", normalized))
    return "\n".join(lines)


def _flatten_readable_fields(
    value: Mapping[str, Any],
    *,
    prefix: str | None = None,
    exclude_keys: frozenset[str] = frozenset(),
) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for key, nested_value in value.items():
        key_name = str(key)
        if key_name in exclude_keys:
            continue
        field_name = f"{prefix}.{key_name}" if prefix else key_name
        if isinstance(nested_value, Mapping):
            fields.extend(_flatten_readable_fields(nested_value, prefix=field_name))
        elif isinstance(nested_value, list):
            fields.append((field_name, json.dumps(nested_value, ensure_ascii=False)))
        elif nested_value not in (None, ""):
            fields.append((field_name, str(nested_value)))
    return fields


def _build_rows_summary(
    label: str,
    rows: list[Mapping[str, Any]],
    *,
    primary_keys: tuple[str, ...],
    message_key: str | None = None,
) -> str:
    if not rows:
        return f"{label} returned 0 row(s)."
    lines = [f"{label} returned {len(rows)} row(s):"]
    for row in rows:
        lines.append(f"- {_line_for_entry(row, primary_keys=primary_keys, message_key=message_key)}")
    return "\n".join(lines)


def _build_raw_resource(tool_name: str, raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "resource",
        "resource": {
            "uri": f"hf-mcp://raw/{tool_name}",
            "mimeType": "application/json",
            "text": json.dumps(raw_payload, ensure_ascii=False),
        },
    }


def _build_read_tool_result(
    *,
    tool_name: str,
    normalized_payload: dict[str, Any],
    mode: ReadOutputMode,
    raw_payload: Mapping[str, Any] | None,
    include_raw_payload: bool,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": _build_content_summary(tool_name, normalized_payload, mode)}]
    if raw_payload is not None and (mode == "raw" or include_raw_payload):
        content.append(_build_raw_resource(tool_name, raw_payload))
    return {
        "content": content,
        "structuredContent": normalized_payload,
    }


def build_core_read_handlers(policy: CapabilityPolicy, transport: HFTransport) -> dict[str, ReadHandler]:
    handlers: dict[str, ReadHandler] = {}
    settings = cast(HFMCPSettings, getattr(policy, "_settings"))

    def _finalize_result(
        *,
        tool_name: str,
        asks: Mapping[str, Any],
        helper: str,
        output_mode: str | None,
        include_raw_payload: bool | None,
        body_format: str | None,
    ) -> dict[str, Any]:
        defaults = resolve_read_output_defaults(settings, output_mode, include_raw_payload, body_format)
        need_raw = defaults.mode == "raw" or defaults.include_raw_payload
        raw_payload: dict[str, Any] | None = None
        if need_raw:
            raw_payload = transport.read_raw(asks=asks, helper=helper)
            normalized_payload = normalize_response(raw_payload)
        else:
            normalized_payload = transport.read(asks=asks, helper=helper)
        normalized_payload = format_body_fields(normalized_payload, defaults.body_format)
        return _build_read_tool_result(
            tool_name=tool_name,
            normalized_payload=normalized_payload,
            mode=defaults.mode,
            raw_payload=raw_payload,
            include_raw_payload=defaults.include_raw_payload,
        )

    for spec in get_core_read_specs():
        if not policy.can_register(spec.tool_name):
            continue
        if spec.tool_name == "me.read":
            allow_advanced = "fields.me.advanced" in policy.allowed_parameter_families("me.read")

            def _me_handler(
                *,
                include_basic_fields: bool | None = True,
                include_advanced_fields: bool | None = False,
                output_mode: str | None = None,
                include_raw_payload: bool | None = None,
                body_format: str | None = None,
            ) -> dict[str, Any]:
                asks = _build_me_asks(
                    include_basic_fields=include_basic_fields,
                    include_advanced_fields=include_advanced_fields,
                    allow_advanced_fields=allow_advanced,
                )
                return _finalize_result(
                    tool_name="me.read",
                    asks=asks,
                    helper="me",
                    output_mode=output_mode,
                    include_raw_payload=include_raw_payload,
                    body_format=body_format,
                )

            handlers[spec.tool_name] = _me_handler
        elif spec.tool_name == "users.read":
            def _users_handler(
                *,
                uid: int,
                page: int | None = DEFAULT_PAGE,
                per_page: int | None = DEFAULT_PER_PAGE,
                include_profile_fields: bool | None = True,
                output_mode: str | None = None,
                include_raw_payload: bool | None = None,
                body_format: str | None = None,
            ) -> dict[str, Any]:
                asks = _build_users_asks(
                    uid=uid,
                    page=page,
                    per_page=per_page,
                    include_profile_fields=include_profile_fields,
                )
                return _finalize_result(
                    tool_name="users.read",
                    asks=asks,
                    helper="users",
                    output_mode=output_mode,
                    include_raw_payload=include_raw_payload,
                    body_format=body_format,
                )

            handlers[spec.tool_name] = _users_handler
        elif spec.tool_name == "forums.read":
            def _forums_handler(
                *,
                fid: int,
                page: int | None = DEFAULT_PAGE,
                per_page: int | None = DEFAULT_PER_PAGE,
                output_mode: str | None = None,
                include_raw_payload: bool | None = None,
                body_format: str | None = None,
            ) -> dict[str, Any]:
                asks = _build_forums_asks(fid=fid, page=page, per_page=per_page)
                return _finalize_result(
                    tool_name="forums.read",
                    asks=asks,
                    helper="forums",
                    output_mode=output_mode,
                    include_raw_payload=include_raw_payload,
                    body_format=body_format,
                )

            handlers[spec.tool_name] = _forums_handler
        elif spec.tool_name == "threads.read":
            def _threads_handler(
                *,
                fid: int | None = None,
                tid: int | None = None,
                uid: int | None = None,
                page: int | None = DEFAULT_PAGE,
                per_page: int | None = DEFAULT_PER_PAGE,
                output_mode: str | None = None,
                include_raw_payload: bool | None = None,
                body_format: str | None = None,
            ) -> dict[str, Any]:
                asks = _build_threads_asks(fid=fid, tid=tid, uid=uid, page=page, per_page=per_page)
                return _finalize_result(
                    tool_name="threads.read",
                    asks=asks,
                    helper="threads",
                    output_mode=output_mode,
                    include_raw_payload=include_raw_payload,
                    body_format=body_format,
                )

            handlers[spec.tool_name] = _threads_handler
        elif spec.tool_name == "posts.read":
            def _posts_handler(
                *,
                tid: int | None = None,
                pid: int | None = None,
                uid: int | None = None,
                page: int | None = DEFAULT_PAGE,
                per_page: int | None = DEFAULT_PER_PAGE,
                include_post_body: bool | None = True,
                output_mode: str | None = None,
                include_raw_payload: bool | None = None,
                body_format: str | None = None,
            ) -> dict[str, Any]:
                asks = _build_posts_asks(
                    tid=tid,
                    pid=pid,
                    uid=uid,
                    page=page,
                    per_page=per_page,
                    include_post_body=include_post_body,
                )
                return _finalize_result(
                    tool_name="posts.read",
                    asks=asks,
                    helper="posts",
                    output_mode=output_mode,
                    include_raw_payload=include_raw_payload,
                    body_format=body_format,
                )

            handlers[spec.tool_name] = _posts_handler
    return handlers


__all__ = [
    "build_core_read_handlers",
    "get_profile",
    "get_user",
    "list_forums",
    "list_threads",
    "list_posts",
]
