from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from functools import partial
from typing import Any, cast

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.flow import attach_hf_flow, build_hf_flow
from hf_mcp.hf_client import (
    DEFAULT_PAGE,
    DEFAULT_PER_PAGE,
    HFClient,
    ReadRequest,
    flow_source,
)
from hf_mcp.normalizers import format_body_fields, normalize_response
from hf_mcp.output_modes import ReadOutputMode, resolve_read_output_defaults
from hf_mcp.registry import get_specs
from hf_mcp.transport import HFTransport

ReadHandler = Callable[..., dict[str, Any]]
RequestBuilder = Callable[..., tuple[ReadRequest, dict[str, Any]]]
Normalizer = Callable[[dict[str, Any]], dict[str, Any]]
_GENERIC_SUMMARY_KEYS = (
    "cid",
    "cdid",
    "crid",
    "smid",
    "oid",
    "uid",
    "status",
    "dateline",
    "amount",
    "price",
)


def selectors_of(**values: int | str | None) -> dict[str, int | str]:
    return {name: value for name, value in values.items() if value is not None}


def _me_request(
    *,
    include_basic_fields: bool | None = True,
    include_advanced_fields: bool | None = False,
    allow_advanced_fields: bool = True,
) -> tuple[ReadRequest, dict[str, Any]]:
    fields = set()
    if include_basic_fields is not False:
        fields.add("basic")
    if include_advanced_fields is True and allow_advanced_fields:
        fields.add("advanced")
    arguments = {
        "include_basic_fields": include_basic_fields,
        "include_advanced_fields": include_advanced_fields,
    }
    return ReadRequest("me", fields=frozenset(fields)), arguments


def _users_request(
    *,
    uid: int,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
    include_profile_fields: bool | None = True,
) -> tuple[ReadRequest, dict[str, Any]]:
    fields = frozenset() if include_profile_fields is False else frozenset({"profile"})
    request = ReadRequest("users", selectors_of(uid=uid), fields, page, per_page)
    return request, {"uid": uid, "page": page, "per_page": per_page}


def _forums_request(
    *,
    fid: int,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
) -> tuple[ReadRequest, dict[str, Any]]:
    request = ReadRequest(
        "forums", selectors_of(fid=fid), frozenset({"forum"}), page, per_page
    )
    return request, {"fid": fid, "page": page, "per_page": per_page}


def _threads_request(
    *,
    fid: int | None = None,
    tid: int | None = None,
    uid: int | None = None,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
) -> tuple[ReadRequest, dict[str, Any]]:
    request = ReadRequest(
        "threads",
        selectors_of(fid=fid, tid=tid, uid=uid),
        frozenset({"thread"}),
        page,
        per_page,
    )
    arguments = {"fid": fid, "tid": tid, "uid": uid, "page": page}
    return request, {**arguments, "per_page": per_page}


def _posts_request(
    *,
    tid: int | None = None,
    pid: int | None = None,
    uid: int | None = None,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
    include_post_body: bool | None = True,
) -> tuple[ReadRequest, dict[str, Any]]:
    fields = frozenset({"post"} if include_post_body is False else {"post", "body"})
    request = ReadRequest(
        "posts", selectors_of(tid=tid, pid=pid, uid=uid), fields, page, per_page
    )
    arguments = {"tid": tid, "pid": pid, "uid": uid, "page": page}
    return request, {
        **arguments,
        "per_page": per_page,
        "include_post_body": include_post_body,
    }


_CORE_REQUESTS: dict[str, RequestBuilder] = {
    "me.read": _me_request,
    "users.read": _users_request,
    "forums.read": _forums_request,
    "threads.read": _threads_request,
    "posts.read": _posts_request,
}


def _read_structured(
    transport: HFTransport, build: RequestBuilder, normalize: Normalizer, **kwargs: Any
) -> dict[str, Any]:
    request, _ = build(**kwargs)
    return normalize(HFClient(transport).read(request))


def get_profile(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_structured(transport, _me_request, normalize_response, **kwargs)


def get_user(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_structured(transport, _users_request, normalize_response, **kwargs)


def list_forums(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_structured(transport, _forums_request, normalize_response, **kwargs)


def list_threads(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_structured(transport, _threads_request, normalize_response, **kwargs)


def list_posts(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_structured(transport, _posts_request, normalize_response, **kwargs)


def _line_for_entry(
    entry: Mapping[str, Any],
    *,
    primary_keys: tuple[str, ...],
    message_key: str | None = None,
) -> str:
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


def _build_content_summary(
    tool_name: str, payload: Mapping[str, Any], mode: ReadOutputMode, root_key: str
) -> str:
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
        return _build_rows_summary(
            "users.read", rows, primary_keys=("uid", "username", "reputation")
        )
    if tool_name == "forums.read":
        return _build_rows_summary(
            "forums.read", rows, primary_keys=("fid", "name", "type")
        )
    if tool_name == "threads.read":
        return _build_threads_readable_content(rows)
    if tool_name == "posts.read":
        return _build_rows_summary(
            "posts.read",
            rows,
            primary_keys=("pid", "tid", "fid", "uid", "subject"),
            message_key="message",
        )
    return _build_rows_summary(tool_name, rows, primary_keys=_GENERIC_SUMMARY_KEYS)


def _build_threads_readable_content(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return "threads.read returned 0 thread(s)."

    lines = [f"threads.read returned {len(rows)} thread(s)."]
    for index, row in enumerate(rows, start=1):
        subject = row.get("subject")
        title = subject if isinstance(subject, str) and subject else f"Thread {index}"
        lines.extend(("", f"## {title}"))

        thread_fields = _flatten_readable_fields(
            row, exclude_keys=frozenset({"firstpost"})
        )
        if thread_fields:
            lines.extend(("", "### Thread fields"))
            lines.extend(f"- {key}: {value}" for key, value in thread_fields)

        firstpost = row.get("firstpost")
        if not isinstance(firstpost, Mapping):
            continue

        firstpost_fields = _flatten_readable_fields(
            firstpost, prefix="firstpost", exclude_keys=frozenset({"message"})
        )
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
        lines.append(
            f"- {_line_for_entry(row, primary_keys=primary_keys, message_key=message_key)}"
        )
    return "\n".join(lines)


def _build_raw_resource(
    tool_name: str, raw_payload: Mapping[str, Any]
) -> dict[str, Any]:
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
    root_key: str,
    with_flow: bool,
    arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": _build_content_summary(
                tool_name, normalized_payload, mode, root_key
            ),
        }
    ]
    if raw_payload is not None and (mode == "raw" or include_raw_payload):
        content.append(_build_raw_resource(tool_name, raw_payload))
    if not with_flow:
        return {"content": content, "structuredContent": normalized_payload}
    flow = build_hf_flow(
        tool_name=tool_name,
        normalized_payload=normalized_payload,
        arguments=arguments,
        source=root_key,
    )
    return {
        "content": content,
        "structuredContent": attach_hf_flow(normalized_payload, flow),
    }


def _finalize_result(
    *,
    client: HFClient,
    settings: HFMCPSettings,
    tool_name: str,
    request: ReadRequest,
    normalize: Normalizer,
    with_flow: bool,
    output_mode: str | None,
    include_raw_payload: bool | None,
    body_format: str | None,
    arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The one read pipeline: one client read, one structured path, one result."""
    defaults = resolve_read_output_defaults(
        settings, output_mode, include_raw_payload, body_format
    )
    raw_payload = client.read(request)
    structured = format_body_fields(normalize(raw_payload), defaults.body_format)
    return _build_read_tool_result(
        tool_name=tool_name,
        normalized_payload=structured,
        mode=defaults.mode,
        raw_payload=raw_payload,
        include_raw_payload=defaults.include_raw_payload,
        root_key=flow_source(request.resource),
        with_flow=with_flow,
        arguments=arguments,
    )


def make_read_handler(
    *,
    client: HFClient,
    settings: HFMCPSettings,
    tool_name: str,
    build: RequestBuilder,
    normalize: Normalizer,
    with_flow: bool,
) -> ReadHandler:
    def _call(
        *,
        output_mode: str | None = None,
        include_raw_payload: bool | None = None,
        body_format: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        request, arguments = build(**kwargs)
        return _finalize_result(
            client=client,
            settings=settings,
            tool_name=tool_name,
            request=request,
            normalize=normalize,
            with_flow=with_flow,
            output_mode=output_mode,
            include_raw_payload=include_raw_payload,
            body_format=body_format,
            arguments=arguments,
        )

    return _call


def build_core_read_handlers(
    policy: CapabilityPolicy, transport: HFTransport
) -> dict[str, ReadHandler]:
    settings = cast(HFMCPSettings, getattr(policy, "_settings"))
    client = HFClient(transport)
    handlers: dict[str, ReadHandler] = {}
    for spec in get_specs("core_read"):
        if not policy.can_register(spec.name):
            continue
        build = _CORE_REQUESTS[spec.name]
        if spec.name == "me.read":
            allow_advanced = "fields.me.advanced" in policy.allowed_parameter_families(
                "me.read"
            )
            build = partial(_me_request, allow_advanced_fields=allow_advanced)
        handlers[spec.name] = make_read_handler(
            client=client,
            settings=settings,
            tool_name=spec.name,
            build=build,
            normalize=normalize_response,
            with_flow=True,
        )
    return handlers


__all__ = [
    "build_core_read_handlers",
    "get_profile",
    "get_user",
    "list_forums",
    "list_threads",
    "list_posts",
]
