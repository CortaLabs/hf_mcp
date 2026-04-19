from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.registry import get_core_read_specs
from hf_mcp.transport import HFTransport

ReadHandler = Callable[..., dict[str, Any]]


def get_profile(
    *,
    transport: HFTransport,
    uid: int,
    include_basic_fields: bool = True,
    include_advanced_fields: bool = False,
    allow_advanced_fields: bool = True,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {"me": {"_uid": uid}}
    if include_basic_fields:
        asks["me"]["uid"] = True
        asks["me"]["username"] = True
    if include_advanced_fields and allow_advanced_fields:
        asks["me"]["unreadpms"] = True
        asks["me"]["unreadalerts"] = True
    return transport.read(asks=asks, helper="me")


def get_user(
    *,
    transport: HFTransport,
    uid: int,
    page: int = 1,
    per_page: int = 30,
    include_profile_fields: bool = True,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "users": {"_uid": uid, "_page": page, "_perpage": per_page},
    }
    if include_profile_fields:
        asks["users"]["username"] = True
        asks["users"]["avatar"] = True
        asks["users"]["usergroup"] = True
    return transport.read(asks=asks, helper="users")


def list_forums(
    *,
    transport: HFTransport,
    fid: int,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks = {"forums": {"_fid": fid, "_page": page, "_perpage": per_page}}
    return transport.read(asks=asks, helper="forums")


def list_threads(
    *,
    transport: HFTransport,
    fid: int,
    tid: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {"threads": {"_fid": fid, "_page": page, "_perpage": per_page}}
    if tid is not None:
        asks["threads"]["_tid"] = tid
    return transport.read(asks=asks, helper="threads")


def list_posts(
    *,
    transport: HFTransport,
    tid: int,
    pid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_post_body: bool = True,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "posts": {"_tid": tid, "_page": page, "_perpage": per_page},
    }
    if pid is not None:
        asks["posts"]["_pid"] = pid
    if include_post_body:
        asks["posts"]["message"] = True
    return transport.read(asks=asks, helper="posts")


def build_core_read_handlers(policy: CapabilityPolicy, transport: HFTransport) -> dict[str, ReadHandler]:
    handlers: dict[str, ReadHandler] = {}
    for spec in get_core_read_specs():
        if not policy.can_register(spec.tool_name):
            continue
        if spec.tool_name == "me.read":
            allow_advanced = "fields.me.advanced" in policy.allowed_parameter_families("me.read")

            def _me_handler(**kwargs: Any) -> dict[str, Any]:
                return get_profile(
                    transport=transport,
                    allow_advanced_fields=allow_advanced,
                    **kwargs,
                )

            handlers[spec.tool_name] = _me_handler
        elif spec.tool_name == "users.read":
            handlers[spec.tool_name] = lambda **kwargs: get_user(transport=transport, **kwargs)
        elif spec.tool_name == "forums.read":
            handlers[spec.tool_name] = lambda **kwargs: list_forums(transport=transport, **kwargs)
        elif spec.tool_name == "threads.read":
            handlers[spec.tool_name] = lambda **kwargs: list_threads(transport=transport, **kwargs)
        elif spec.tool_name == "posts.read":
            handlers[spec.tool_name] = lambda **kwargs: list_posts(transport=transport, **kwargs)
    return handlers


__all__ = [
    "build_core_read_handlers",
    "get_profile",
    "get_user",
    "list_forums",
    "list_threads",
    "list_posts",
]
