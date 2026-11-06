"""The one place that knows how Hack Forums v2 spells a read.

Tools describe *what* to read with a ``ReadRequest``. ``HFClient.read`` turns it
into v2 asks plus a helper route and makes exactly one transport call. The client
never retries, normalizes, logs payloads or interprets errors; ``HFAPIError`` from
the transport propagates unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from hf_mcp.transport import HFTransport

DEFAULT_PAGE = 1
DEFAULT_PER_PAGE = 30


@dataclass(frozen=True, slots=True)
class ReadRequest:
    resource: str
    selectors: Mapping[str, int | str] = field(default_factory=dict)
    fields: frozenset[str] = frozenset()
    page: int | None = None
    per_page: int | None = None


@dataclass(frozen=True, slots=True)
class _Resource:
    endpoint: str
    route: str | None
    selectors: Mapping[str, str]
    fields: Mapping[str, tuple[str, ...]]
    paged: bool = True
    require_any: tuple[str, ...] = ()
    nested: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def _words(text: str) -> tuple[str, ...]:
    return tuple(text.split())


def _expansions(*names: str) -> dict[str, tuple[str, ...]]:
    return {name: (name,) for name in names}


_ME_BASIC = _words(
    "uid username usergroup displaygroup additionalgroups postnum awards bytes vault threadnum avatar avatardimensions avatartype lastvisit usertitle website timeonline reputation referrals"
)
_ME_ADVANCED = ("unreadpms", "invisible", "totalpms", "lastactive", "warningpoints")
_USER_PROFILE = _words(
    "uid username usergroup displaygroup additionalgroups postnum awards myps threadnum avatar avatardimensions avatartype usertitle website timeonline reputation referrals"
)
_THREAD = _words("tid fid subject dateline uid username views lastpost sticky")
_POST = _words("pid tid uid fid dateline subject edituid edittime editreason")
_CONTRACT = _words(
    "cid dateline otherdateline public timeout_days timeout status istatus ostatus cancelstatus type tid inituid otheruid muid iprice icurrency iproduct oprice ocurrency oproduct terms template_id oaddress iaddress idispute odispute"
)
_DISPUTE = _words(
    "cdid contractid claimantuid defendantuid dateline status dispute_tid claimantnotes defendantnotes"
)
_BRATING = ("crid", "contractid", "fromid", "toid", "dateline", "amount", "message")
_MARKET = ("uid", "user", "price", "duration", "active", "sig", "dateadded", "ppd")
_ORDER = _words("smid buyer seller startdate enddate price duration active")

_RESOURCES: dict[str, _Resource] = {
    "me": _Resource(
        "me",
        None,
        {},
        {"basic": _ME_BASIC, "advanced": _ME_ADVANCED},
        paged=False,
    ),
    "users": _Resource("users", None, {"uid": "_uid"}, {"profile": _USER_PROFILE}),
    "forums": _Resource(
        "forums",
        None,
        {"fid": "_fid"},
        {"forum": ("fid", "name", "description", "type")},
    ),
    "threads": _Resource(
        "threads",
        None,
        {"fid": "_fid", "tid": "_tid", "uid": "_uid"},
        {"thread": _THREAD},
        require_any=("fid", "tid", "uid"),
        nested={
            "thread": {
                "firstpost": {
                    "pid": True,
                    "message": True,
                    "author": {"uid": True, "username": True},
                }
            }
        },
    ),
    "posts": _Resource(
        "posts",
        None,
        {"tid": "_tid", "pid": "_pid", "uid": "_uid"},
        {"post": _POST, "body": ("message",)},
        require_any=("pid", "tid", "uid"),
    ),
    "bytes": _Resource(
        "bytes",
        "bytes",
        {"id": "_id", "uid": "_uid", "from_uid": "_from", "to_uid": "_to"},
        {"core": ("id", "dateline", "type", "reason"), "amount": ("amount",)},
    ),
    "contracts": _Resource(
        "contracts",
        "contracts",
        {"cid": "_cid", "uid": "_uid"},
        {
            "starter": _CONTRACT,
            **_expansions(
                "inituser", "otheruser", "escrow", "thread", "ibrating", "obrating"
            ),
        },
    ),
    "disputes": _Resource(
        "disputes",
        "disputes",
        {
            "cdid": "_cdid",
            "cid": "_cid",
            "uid": "_uid",
            "claimantuid": "_claimantuid",
            "defendantuid": "_defendantuid",
        },
        {
            "starter": _DISPUTE,
            **_expansions("contract", "claimant", "defendant", "dispute_thread"),
        },
    ),
    # The helper route for bratings returns 404 live; the generic route is proven.
    "bratings": _Resource(
        "bratings",
        None,
        {
            "crid": "_crid",
            "cid": "_cid",
            "uid": "_uid",
            "from_uid": "_from",
            "to_uid": "_to",
        },
        {"starter": _BRATING, **_expansions("contract", "from", "to")},
    ),
    "sigmarket.market": _Resource(
        "sigmarket/market",
        "sigmarket/market",
        {"uid": "_uid"},
        {"market": _MARKET},
    ),
    "sigmarket.order": _Resource(
        "sigmarket/order",
        "sigmarket/order",
        {"smid": "_smid", "uid": "_uid", "seller": "_seller", "buyer": "_buyer"},
        {"order": _ORDER},
    ),
    "admin.high_risk": _Resource(
        "admin/high-risk/read", "admin/high-risk/read", {}, {}
    ),
}


def _lookup(resource: str) -> _Resource:
    entry = _RESOURCES.get(resource)
    if entry is None:
        raise ValueError(f"Unknown read resource '{resource}'.")
    return entry


def flow_source(resource: str) -> str:
    """The endpoint label flow breadcrumbs use for a resource."""
    return _lookup(resource).endpoint


def _build_asks(request: ReadRequest, entry: _Resource) -> dict[str, dict[str, Any]]:
    for name in request.selectors:
        if name not in entry.selectors:
            raise ValueError(
                f"Unknown selector '{name}' for read resource '{request.resource}'."
            )
    for name in request.fields:
        if name not in entry.fields:
            raise ValueError(
                f"Unknown field '{name}' for read resource '{request.resource}'."
            )
    if entry.require_any and not any(
        request.selectors.get(name) is not None for name in entry.require_any
    ):
        raise ValueError(
            f"{request.resource}.read requires at least one selector: "
            f"{_join_or(entry.require_any)}"
        )

    body: dict[str, Any] = {
        wire: request.selectors[name]
        for name, wire in entry.selectors.items()
        if request.selectors.get(name) is not None
    }
    if entry.paged:
        body["_page"] = DEFAULT_PAGE if request.page is None else request.page
        body["_perpage"] = (
            DEFAULT_PER_PAGE if request.per_page is None else request.per_page
        )
    for group, wire_fields in entry.fields.items():
        if group not in request.fields:
            continue
        for wire_field in wire_fields:
            body[wire_field] = True
        for key, value in entry.nested.get(group, {}).items():
            body[key] = _copy_nested(value)
    return {entry.endpoint: body}


def _copy_nested(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy_nested(item) for key, item in value.items()}
    return value


def _join_or(names: tuple[str, ...]) -> str:
    return f"{', '.join(names[:-1])}, or {names[-1]}"


class HFClient:
    def __init__(self, transport: HFTransport) -> None:
        self._transport = transport

    def read(self, request: ReadRequest) -> dict[str, Any]:
        entry = _lookup(request.resource)
        asks = _build_asks(request, entry)
        return self._transport.read_raw(asks=asks, helper=entry.route)


__all__ = ["HFClient", "ReadRequest", "flow_source"]
