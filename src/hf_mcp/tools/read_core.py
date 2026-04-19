from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.registry import get_core_read_specs
from hf_mcp.transport import HFTransport

ReadHandler = Callable[..., dict[str, Any]]
DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 30
_DEFAULT_THREAD_FIELDS = ("tid", "subject", "uid", "username")
_DEFAULT_POST_FIELDS = ("pid", "uid", "subject")


def get_profile(
    *,
    transport: HFTransport,
    include_basic_fields: bool | None = True,
    include_advanced_fields: bool | None = False,
    allow_advanced_fields: bool = True,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {"me": {}}
    if include_basic_fields is not False:
        asks["me"]["uid"] = True
        asks["me"]["username"] = True
    if include_advanced_fields is True and allow_advanced_fields:
        asks["me"]["unreadpms"] = True
        asks["me"]["unreadalerts"] = True
    return transport.read(asks=asks, helper="me")


def get_user(
    *,
    transport: HFTransport,
    uid: int,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
    include_profile_fields: bool | None = True,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "users": {"_uid": uid, "_page": _coerce_page(page), "_perpage": _coerce_per_page(per_page)},
    }
    if include_profile_fields is not False:
        asks["users"]["username"] = True
        asks["users"]["avatar"] = True
        asks["users"]["usergroup"] = True
    return transport.read(asks=asks, helper="users")


def list_forums(
    *,
    transport: HFTransport,
    fid: int,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
) -> dict[str, Any]:
    asks = {"forums": {"_fid": fid, "_page": _coerce_page(page), "_perpage": _coerce_per_page(per_page)}}
    return transport.read(asks=asks, helper="forums")


def list_threads(
    *,
    transport: HFTransport,
    fid: int,
    tid: int | None = None,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "threads": {"_fid": fid, "_page": _coerce_page(page), "_perpage": _coerce_per_page(per_page)}
    }
    if tid is not None:
        asks["threads"]["_tid"] = tid
    for field_name in _DEFAULT_THREAD_FIELDS:
        asks["threads"][field_name] = True
    return transport.read(asks=asks, helper="threads")


def list_posts(
    *,
    transport: HFTransport,
    tid: int,
    pid: int | None = None,
    page: int | None = DEFAULT_PAGE,
    per_page: int | None = DEFAULT_PER_PAGE,
    include_post_body: bool | None = True,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "posts": {"_tid": tid, "_page": _coerce_page(page), "_perpage": _coerce_per_page(per_page)},
    }
    if pid is not None:
        asks["posts"]["_pid"] = pid
    for field_name in _DEFAULT_POST_FIELDS:
        asks["posts"][field_name] = True
    if include_post_body is not False:
        asks["posts"]["message"] = True
    return transport.read(asks=asks, helper="posts")


def _coerce_page(page: int | None) -> int:
    return DEFAULT_PAGE if page is None else page


def _coerce_per_page(per_page: int | None) -> int:
    return DEFAULT_PER_PAGE if per_page is None else per_page


def build_core_read_handlers(policy: CapabilityPolicy, transport: HFTransport) -> dict[str, ReadHandler]:
    handlers: dict[str, ReadHandler] = {}
    for spec in get_core_read_specs():
        if not policy.can_register(spec.tool_name):
            continue
        if spec.tool_name == "me.read":
            allow_advanced = "fields.me.advanced" in policy.allowed_parameter_families("me.read")

            def _me_handler(
                *,
                include_basic_fields: bool | None = True,
                include_advanced_fields: bool | None = False,
            ) -> dict[str, Any]:
                return get_profile(
                    transport=transport,
                    include_basic_fields=include_basic_fields,
                    include_advanced_fields=include_advanced_fields,
                    allow_advanced_fields=allow_advanced,
                )

            handlers[spec.tool_name] = _me_handler
        elif spec.tool_name == "users.read":
            def _users_handler(
                *,
                uid: int,
                page: int | None = DEFAULT_PAGE,
                per_page: int | None = DEFAULT_PER_PAGE,
                include_profile_fields: bool | None = True,
            ) -> dict[str, Any]:
                return get_user(
                    transport=transport,
                    uid=uid,
                    page=page,
                    per_page=per_page,
                    include_profile_fields=include_profile_fields,
                )

            handlers[spec.tool_name] = _users_handler
        elif spec.tool_name == "forums.read":
            def _forums_handler(
                *,
                fid: int,
                page: int | None = DEFAULT_PAGE,
                per_page: int | None = DEFAULT_PER_PAGE,
            ) -> dict[str, Any]:
                return list_forums(transport=transport, fid=fid, page=page, per_page=per_page)

            handlers[spec.tool_name] = _forums_handler
        elif spec.tool_name == "threads.read":
            def _threads_handler(
                *,
                fid: int,
                tid: int | None = None,
                page: int | None = DEFAULT_PAGE,
                per_page: int | None = DEFAULT_PER_PAGE,
            ) -> dict[str, Any]:
                return list_threads(transport=transport, fid=fid, tid=tid, page=page, per_page=per_page)

            handlers[spec.tool_name] = _threads_handler
        elif spec.tool_name == "posts.read":
            def _posts_handler(
                *,
                tid: int,
                pid: int | None = None,
                page: int | None = DEFAULT_PAGE,
                per_page: int | None = DEFAULT_PER_PAGE,
                include_post_body: bool | None = True,
            ) -> dict[str, Any]:
                return list_posts(
                    transport=transport,
                    tid=tid,
                    pid=pid,
                    page=page,
                    per_page=per_page,
                    include_post_body=include_post_body,
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
