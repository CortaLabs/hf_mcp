from __future__ import annotations

import json
from typing import Any

import pytest

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.hf_client import HFClient, ReadRequest
from hf_mcp.registry import get_tool_spec
from hf_mcp.tools.read_core import build_core_read_handlers
from hf_mcp.tools.read_extended import build_extended_read_handlers
from hf_mcp.transport import HFAPIError, HFTransport, build_error


class _RecordingTransport(HFTransport):
    """Records every read_raw call and answers with a fixed payload."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.payload = payload if payload is not None else {}
        self.error: HFAPIError | None = None

    def read_raw(self, asks: Any, helper: str | None = None) -> dict[str, Any]:  # type: ignore[override]
        self.calls.append({"asks": asks, "helper": helper})
        if self.error is not None:
            raise self.error
        return self.payload


def _flags(fields: str) -> dict[str, bool]:
    return {name: True for name in fields.split()}


_ME = (
    "uid username usergroup displaygroup additionalgroups postnum awards bytes vault "
    "threadnum avatar avatardimensions avatartype lastvisit usertitle website "
    "timeonline reputation referrals"
)
_USER = (
    "uid username usergroup displaygroup additionalgroups postnum awards myps "
    "threadnum avatar avatardimensions avatartype usertitle website timeonline "
    "reputation referrals"
)
_THREAD = "tid fid subject dateline uid username views lastpost sticky"
_POST = "pid tid uid fid dateline subject message edituid edittime editreason"
_CONTRACT = (
    "cid dateline otherdateline public timeout_days timeout status istatus ostatus "
    "cancelstatus type tid inituid otheruid muid iprice icurrency iproduct oprice "
    "ocurrency oproduct terms template_id oaddress iaddress idispute odispute"
)
_DISPUTE = (
    "cdid contractid claimantuid defendantuid dateline status dispute_tid "
    "claimantnotes defendantnotes"
)
_BRATING = "crid contractid fromid toid dateline amount message"
_MARKET = "uid user price duration active sig dateadded ppd"
_ORDER = "smid buyer seller startdate enddate price duration active"
_PAGE = {"_page": 1, "_perpage": 30}

# tool -> (kwargs, expected endpoint key, expected helper route, expected body)
# These are the asks and routes the 0.7.2 tools sent, written out independently of
# the client's own table.
_EXPECTED: dict[str, tuple[dict[str, Any], str, str | None, dict[str, Any]]] = {
    "me.read": ({}, "me", None, _flags(_ME)),
    "users.read": (
        {"uid": 5},
        "users",
        None,
        {"_uid": 5, **_PAGE, **_flags(_USER)},
    ),
    "forums.read": (
        {"fid": 9},
        "forums",
        None,
        {"_fid": 9, **_PAGE, **_flags("fid name description type")},
    ),
    "threads.read": (
        {"tid": 7},
        "threads",
        None,
        {
            "_tid": 7,
            **_PAGE,
            **_flags(_THREAD),
            "firstpost": {
                "pid": True,
                "message": True,
                "author": {"uid": True, "username": True},
            },
        },
    ),
    "posts.read": (
        {"tid": 7},
        "posts",
        None,
        {"_tid": 7, **_PAGE, **_flags(_POST)},
    ),
    "bytes.read": (
        {"uid": 3, "from_uid": 4, "to_uid": 6, "id": 8},
        "bytes",
        "bytes",
        {
            "_id": 8,
            "_uid": 3,
            "_from": 4,
            "_to": 6,
            **_PAGE,
            **_flags("id dateline type reason amount"),
        },
    ),
    "contracts.read": (
        {"cid": 2, "uid": 3, "include_escrow": True},
        "contracts",
        "contracts",
        {"_cid": 2, "_uid": 3, **_PAGE, **_flags(_CONTRACT), "escrow": True},
    ),
    "disputes.read": (
        {"cdid": 1, "cid": 2, "uid": 3, "claimantuid": 4, "defendantuid": 5},
        "disputes",
        "disputes",
        {
            "_cdid": 1,
            "_cid": 2,
            "_uid": 3,
            "_claimantuid": 4,
            "_defendantuid": 5,
            **_PAGE,
            **_flags(_DISPUTE),
        },
    ),
    "bratings.read": (
        {"crid": 1, "cid": 2, "uid": 3, "from_uid": 4, "to_uid": 5},
        "bratings",
        None,
        {
            "_crid": 1,
            "_cid": 2,
            "_uid": 3,
            "_from": 4,
            "_to": 5,
            **_PAGE,
            **_flags(_BRATING),
            "contract": True,
        },
    ),
    "sigmarket.market.read": (
        {"uid": 3},
        "sigmarket/market",
        "sigmarket/market",
        {"_uid": 3, **_PAGE, **_flags(_MARKET)},
    ),
    "sigmarket.order.read": (
        {"smid": 17, "uid": 3, "seller": 4, "buyer": 5},
        "sigmarket/order",
        "sigmarket/order",
        {"_smid": 17, "_uid": 3, "_seller": 4, "_buyer": 5, **_PAGE, **_flags(_ORDER)},
    ),
    "admin.high_risk.read": (
        {},
        "admin/high-risk/read",
        "admin/high-risk/read",
        dict(_PAGE),
    ),
}


def _handlers(
    transport: HFTransport, *names: str, **settings_kwargs: Any
) -> dict[str, Any]:
    policy = CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset(names),
            enabled_parameter_families=frozenset(
                family for name in names for family in get_tool_spec(name).families
            ),
            **settings_kwargs,
        )
    )
    handlers = build_core_read_handlers(policy, transport)
    handlers.update(build_extended_read_handlers(policy, transport))
    return handlers


def test_every_read_tool_has_an_expected_row() -> None:
    from hf_mcp.registry import get_specs

    remote = {
        spec.name
        for group in ("core_read", "extended_read")
        for spec in get_specs(group)
    }
    assert remote == set(_EXPECTED)
    assert len(remote) == 12


@pytest.mark.parametrize("tool_name", sorted(_EXPECTED))
def test_tool_sends_the_same_asks_and_route_as_0_7_2(tool_name: str) -> None:
    kwargs, endpoint, route, body = _EXPECTED[tool_name]
    transport = _RecordingTransport({endpoint: []})
    handler = _handlers(transport, tool_name)[tool_name]

    handler(**kwargs)

    assert transport.calls == [{"asks": {endpoint: body}, "helper": route}]


@pytest.mark.parametrize("tool_name", sorted(_EXPECTED))
def test_client_alone_maps_a_request_to_the_same_single_call(tool_name: str) -> None:
    kwargs, endpoint, route, body = _EXPECTED[tool_name]
    transport = _RecordingTransport({endpoint: []})
    payload = {endpoint: [{"uid": 1}]}
    transport.payload = payload

    # Build the request exactly as the tool does, then hand it to the client.
    from hf_mcp.tools import read_core, read_extended

    if tool_name in read_core._CORE_REQUESTS:
        request, _ = read_core._CORE_REQUESTS[tool_name](**kwargs)
    else:
        request, _ = read_extended._extended_request(tool_name, **kwargs)

    assert HFClient(transport).read(request) is payload
    assert transport.calls == [{"asks": {endpoint: body}, "helper": route}]


@pytest.mark.parametrize(
    "request_",
    [
        ReadRequest("nosuch"),
        ReadRequest("users", {"nosuch": 1}),
        ReadRequest("users", {"uid": 1}, frozenset({"nosuch"})),
        ReadRequest("threads"),
    ],
    ids=["resource", "selector", "field", "required-selector"],
)
def test_mapping_gaps_raise_value_error_with_no_transport_call(
    request_: ReadRequest,
) -> None:
    transport = _RecordingTransport()

    with pytest.raises(ValueError) as caught:
        HFClient(transport).read(request_)

    assert str(caught.value)
    assert transport.calls == []


def test_unknown_selector_and_field_name_what_is_unknown() -> None:
    transport = _RecordingTransport()
    client = HFClient(transport)

    with pytest.raises(ValueError, match="Unknown read resource 'nosuch'."):
        client.read(ReadRequest("nosuch"))
    with pytest.raises(
        ValueError, match="Unknown selector 'nosuch' for read resource 'users'."
    ):
        client.read(ReadRequest("users", {"nosuch": 1}))
    with pytest.raises(
        ValueError, match="Unknown field 'nosuch' for read resource 'users'."
    ):
        client.read(ReadRequest("users", {"uid": 1}, frozenset({"nosuch"})))
    with pytest.raises(
        ValueError,
        match="threads.read requires at least one selector: fid, tid, or uid",
    ):
        client.read(ReadRequest("threads"))


def test_transport_error_propagates_unchanged() -> None:
    transport = _RecordingTransport()
    transport.error = HFAPIError(build_error("AUTH_UNAVAILABLE", operation="local"))

    with pytest.raises(HFAPIError) as caught:
        HFClient(transport).read(ReadRequest("me", fields=frozenset({"basic"})))

    assert caught.value is transport.error
    assert len(transport.calls) == 1


# A fixture with numeric ids, decimal amounts, unsorted rows, avatars and groups.
_FIXTURE: dict[str, Any] = {
    "bytes": [
        {"id": 12, "amount": "10.50", "dateline": 1710000500, "type": "gift"},
        {"id": 3, "amount": 2.25, "dateline": 1710000100, "type": "deposit"},
        {"id": 7, "amount": "0.01", "dateline": 1710000900, "type": "bump"},
    ],
    "me": {
        "uid": 5,
        "username": "reader",
        "avatar": "/uploads/avatars/avatar_5.png",
        "additionalgroups": "9, 4,,12",
    },
}


@pytest.mark.parametrize("tool_name", ["bytes.read", "me.read"])
def test_structured_content_and_raw_attachment_are_mode_independent(
    tool_name: str,
) -> None:
    root = tool_name.split(".")[0]
    payload = {root: _FIXTURE[root]}
    results: list[dict[str, Any]] = []
    transport = _RecordingTransport(payload)
    handler = _handlers(transport, tool_name)[tool_name]

    for mode in ("readable", "structured", "raw"):
        for include_raw in (False, True):
            results.append(handler(output_mode=mode, include_raw_payload=include_raw))

    assert len(transport.calls) == 6
    structured = [result["structuredContent"] for result in results]
    assert all(item == structured[0] for item in structured)
    attached = 0
    for result, (mode, include_raw) in zip(
        results,
        [(m, i) for m in ("readable", "structured", "raw") for i in (False, True)],
        strict=True,
    ):
        resources = [
            part for part in result["content"] if part.get("type") == "resource"
        ]
        if mode == "raw" or include_raw:
            attached += 1
            assert json.loads(resources[0]["resource"]["text"]) == payload
        else:
            assert resources == []
    assert attached == 4
