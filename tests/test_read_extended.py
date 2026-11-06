from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.normalizers import normalize_extended_payload
from hf_mcp.output_modes import ReadOutputDefaults
from hf_mcp.registry import get_specs, get_tool_spec
from hf_mcp.token_store import TokenBundle
from hf_mcp.tools.read_extended import (
    build_extended_read_handlers,
    list_admin_high_risk,
    list_bratings,
    list_contracts,
    list_disputes,
    list_entries,
    list_market,
    list_orders,
)
from hf_mcp.transport import HFTransport

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"


@pytest.mark.parametrize("output_mode", ["structured", "raw"])
def test_bratings_handler_uses_generic_route_in_all_output_modes(
    monkeypatch: pytest.MonkeyPatch,
    output_mode: str,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(
        self: HFTransport, route: str, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        calls.append({"route": route, "payload": payload})
        if route != "/read":
            raise RuntimeError("HF helper route failed with HTTP 404")
        return {"bratings": [{"crid": 7, "contractid": 8}]}

    monkeypatch.setattr(HFTransport, "_post_json", fake_post)
    policy = _policy(
        enabled_capabilities={"bratings.read"},
        enabled_parameter_families=set(get_tool_spec("bratings.read").families),
    )
    handlers = build_extended_read_handlers(policy, HFTransport(_StubTokenStore()))
    result = handlers["bratings.read"](
        uid=5, page=2, per_page=3, output_mode=output_mode
    )
    assert len(calls) == 1
    asks = calls[0]["payload"]["asks"]["bratings"]
    assert asks["_uid"] == 5
    assert asks["_page"] == 2
    assert asks["_perpage"] == 3
    assert asks["contract"] is True
    assert result["structuredContent"]["bratings"][0]["crid"] == "7"
    if output_mode == "raw":
        raw = json.loads(result["content"][1]["resource"]["text"])
        assert raw["bratings"][0]["crid"] == 7


class _StubTokenStore:
    def require_bundle(self) -> TokenBundle:
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset())


def _policy(
    *, enabled_capabilities: set[str], enabled_parameter_families: set[str]
) -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset(enabled_capabilities),
            enabled_parameter_families=frozenset(enabled_parameter_families),
        )
    )


def _actions_as_tuples(
    flow: dict[str, object],
) -> set[tuple[str, tuple[tuple[str, int], ...]]]:
    actions = flow.get("next_actions")
    assert isinstance(actions, list)
    normalized: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
    for action in actions:
        assert isinstance(action, dict)
        tool = action.get("tool")
        arguments = action.get("arguments")
        if not isinstance(tool, str) or not isinstance(arguments, dict):
            continue
        normalized.add(
            (
                tool,
                tuple(
                    sorted((str(key), int(value)) for key, value in arguments.items())
                ),
            )
        )
    return normalized


def _assert_structured_payload_with_flow(
    *,
    tool_name: str,
    structured_content: dict[str, Any],
    expected_payload: dict[str, Any],
) -> None:
    for key, value in expected_payload.items():
        assert structured_content[key] == value
    assert "_hf_flow" in structured_content
    flow = structured_content["_hf_flow"]
    assert flow["entry_tool"] == tool_name
    assert isinstance(flow.get("next_actions"), list)


def test_extended_read_specs_match_registry_rows_and_parameter_families() -> None:
    specs = get_specs("extended_read")
    assert {spec.name for spec in specs} == {
        "bytes.read",
        "contracts.read",
        "disputes.read",
        "bratings.read",
        "sigmarket.market.read",
        "sigmarket.order.read",
        "admin.high_risk.read",
    }
    for spec in specs:
        assert get_tool_spec(spec.name) is spec
        assert spec.group == "extended_read"
        assert spec.families >= {"output.options"}


def test_build_extended_handlers_registers_only_policy_allowed_rows() -> None:
    policy = _policy(
        enabled_capabilities={
            "bytes.read",
            "sigmarket.order.read",
            "admin.high_risk.read",
        },
        enabled_parameter_families={
            "selectors.bytes",
            "fields.bytes.amount",
            "selectors.sigmarket",
        },
    )
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )

    handlers = build_extended_read_handlers(policy, transport)

    # admin.high_risk.read has only optional families, so it registers with its
    # capability alone; contracts.read stays out because its capability is off.
    assert set(handlers) == {
        "bytes.read",
        "sigmarket.order.read",
        "admin.high_risk.read",
    }
    assert "contracts.read" not in handlers


@pytest.mark.parametrize(
    ("tool_name", "kwargs", "response_key"),
    [
        ("bytes.read", {"uid": 5}, "bytes"),
        ("contracts.read", {"cid": 7}, "contracts"),
        ("disputes.read", {"cdid": 11}, "disputes"),
        ("sigmarket.market.read", {"uid": 13}, "sigmarket/market"),
        ("sigmarket.order.read", {"smid": 17}, "sigmarket/order"),
    ],
)
def test_extended_handlers_accept_schema_surface_selector_names(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    kwargs: dict[str, int],
    response_key: str,
) -> None:
    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        return {response_key: []}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    policy = _policy(
        enabled_capabilities={
            "bytes.read",
            "contracts.read",
            "disputes.read",
            "sigmarket.market.read",
            "sigmarket.order.read",
        },
        enabled_parameter_families={
            "selectors.bytes",
            "selectors.contract",
            "selectors.dispute",
            "selectors.sigmarket",
            "filters.pagination",
            "fields.bytes.amount",
        },
    )
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )

    handlers = build_extended_read_handlers(policy, transport)

    result = handlers[tool_name](**kwargs)
    _assert_structured_payload_with_flow(
        tool_name=tool_name,
        structured_content=result["structuredContent"],
        expected_payload={response_key: []},
    )
    assert result["content"] == [
        {"type": "text", "text": f"{tool_name} returned 0 row(s)."}
    ]


@pytest.mark.parametrize(
    ("tool_name", "kwargs", "response_key"),
    [
        ("bytes.read", {"target_uid": 5}, "bytes"),
        ("contracts.read", {"contract_id": 7}, "contracts"),
        ("disputes.read", {"dispute_id": 11}, "disputes"),
        ("disputes.read", {"did": 11}, "disputes"),
        ("sigmarket.order.read", {"oid": 17}, "sigmarket/order"),
    ],
)
def test_extended_handlers_keep_legacy_selector_aliases_for_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    kwargs: dict[str, int],
    response_key: str,
) -> None:
    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        return {response_key: []}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    policy = _policy(
        enabled_capabilities={
            "bytes.read",
            "contracts.read",
            "disputes.read",
            "sigmarket.market.read",
            "sigmarket.order.read",
        },
        enabled_parameter_families={
            "selectors.bytes",
            "selectors.contract",
            "selectors.dispute",
            "selectors.sigmarket",
            "filters.pagination",
        },
    )
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )

    handlers = build_extended_read_handlers(policy, transport)

    result = handlers[tool_name](**kwargs)
    _assert_structured_payload_with_flow(
        tool_name=tool_name,
        structured_content=result["structuredContent"],
        expected_payload={response_key: []},
    )
    assert result["content"] == [
        {"type": "text", "text": f"{tool_name} returned 0 row(s)."}
    ]


def test_sigmarket_order_legacy_oid_alias_maps_to_canonical_smid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_read(
        self: HFTransport, asks: dict[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        captured["asks"] = asks
        captured["helper"] = helper
        return {"sigmarket/order": []}

    monkeypatch.setattr(HFTransport, "read_raw", _fake_read)

    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"sigmarket.order.read"}),
        enabled_parameter_families=frozenset(
            {"selectors.sigmarket", "filters.pagination"}
        ),
    )
    policy = CapabilityPolicy(settings)
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    handler = build_extended_read_handlers(policy, transport)["sigmarket.order.read"]

    result = handler(oid=17)
    _assert_structured_payload_with_flow(
        tool_name="sigmarket.order.read",
        structured_content=result["structuredContent"],
        expected_payload={"sigmarket/order": []},
    )
    assert captured["helper"] == "sigmarket/order"
    assert captured["asks"]["sigmarket/order"]["_smid"] == 17
    assert "_oid" not in captured["asks"]["sigmarket/order"]


def test_registered_sigmarket_order_handler_supports_output_modes_and_raw_payload_attachment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    read_payload = {
        "sigmarket/order": [
            {"smid": "3", "status": "1", "dateline": "1710000000", "amount": "5"},
            {"smid": "12", "status": "2", "dateline": "1710001000", "amount": "8"},
        ]
    }
    raw_payload = {
        "sigmarket/order": [
            {"smid": "3", "status": "1", "dateline": "1710000000", "amount": "5"},
            {"smid": "12", "status": "2", "dateline": "1710001000", "amount": "8"},
        ]
    }

    def _fake_read_raw(
        self: HFTransport, asks: dict[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        captured.append({"asks": asks, "helper": helper})
        return raw_payload

    monkeypatch.setattr(HFTransport, "read_raw", _fake_read_raw)

    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"sigmarket.order.read"}),
        enabled_parameter_families=frozenset(
            {"selectors.sigmarket", "filters.pagination"}
        ),
        read_output_defaults=ReadOutputDefaults(
            mode="structured", include_raw_payload=True
        ),
    )
    policy = CapabilityPolicy(settings)
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    handler = build_extended_read_handlers(policy, transport)["sigmarket.order.read"]

    readable_result = handler(
        smid=17, output_mode="readable", include_raw_payload=False
    )
    _assert_structured_payload_with_flow(
        tool_name="sigmarket.order.read",
        structured_content=readable_result["structuredContent"],
        expected_payload=normalize_extended_payload(read_payload),
    )
    assert readable_result["content"][0]["type"] == "text"
    assert "smid=12" in readable_result["content"][0]["text"]
    assert "status=2" in readable_result["content"][0]["text"]
    assert "dateline=1710001000" in readable_result["content"][0]["text"]
    assert "amount=8" in readable_result["content"][0]["text"]
    assert len(readable_result["content"]) == 1

    structured_result = handler(
        smid=17, output_mode="structured", include_raw_payload=False
    )
    _assert_structured_payload_with_flow(
        tool_name="sigmarket.order.read",
        structured_content=structured_result["structuredContent"],
        expected_payload=normalize_extended_payload(read_payload),
    )
    assert structured_result["content"] == [
        {"type": "text", "text": "sigmarket.order.read returned 2 row(s)."}
    ]

    raw_result = handler(smid=17, output_mode="raw", include_raw_payload=False)
    _assert_structured_payload_with_flow(
        tool_name="sigmarket.order.read",
        structured_content=raw_result["structuredContent"],
        expected_payload=normalize_extended_payload(raw_payload),
    )
    assert raw_result["content"][0] == {
        "type": "text",
        "text": "sigmarket.order.read returned 2 row(s).",
    }
    assert raw_result["content"][1]["type"] == "resource"
    assert (
        raw_result["content"][1]["resource"]["uri"]
        == "hf-mcp://raw/sigmarket.order.read"
    )
    assert raw_result["content"][1]["resource"]["mimeType"] == "application/json"
    assert json.loads(raw_result["content"][1]["resource"]["text"]) == raw_payload
    assert (
        json.loads(raw_result["content"][1]["resource"]["text"])["sigmarket/order"][0][
            "smid"
        ]
        == "3"
    )
    assert raw_result["structuredContent"]["sigmarket/order"][0]["smid"] == "3"

    readable_with_raw = handler(
        smid=17, output_mode="readable", include_raw_payload=True
    )
    _assert_structured_payload_with_flow(
        tool_name="sigmarket.order.read",
        structured_content=readable_with_raw["structuredContent"],
        expected_payload=normalize_extended_payload(raw_payload),
    )
    assert readable_with_raw["content"][1]["type"] == "resource"
    assert (
        json.loads(readable_with_raw["content"][1]["resource"]["text"]) == raw_payload
    )

    defaults_result = handler(smid=17)
    _assert_structured_payload_with_flow(
        tool_name="sigmarket.order.read",
        structured_content=defaults_result["structuredContent"],
        expected_payload=normalize_extended_payload(raw_payload),
    )
    assert defaults_result["content"][0] == {
        "type": "text",
        "text": "sigmarket.order.read returned 2 row(s).",
    }
    assert defaults_result["content"][1]["type"] == "resource"
    assert json.loads(defaults_result["content"][1]["resource"]["text"]) == raw_payload

    assert len(captured) == 5
    assert all(call["helper"] == "sigmarket/order" for call in captured)
    assert all(call["asks"]["sigmarket/order"]["_smid"] == 17 for call in captured)


@pytest.mark.parametrize(
    ("tool_name", "kwargs", "response_payload", "expected_actions"),
    [
        (
            "contracts.read",
            {"cid": 7},
            {
                "contracts": [
                    {
                        "cid": "7",
                        "tid": "1234",
                        "inituid": "99",
                        "otheruid": "77",
                        "idispute": "11",
                    }
                ]
            },
            {
                ("disputes.read", (("cid", 7),)),
                ("threads.read", (("tid", 1234),)),
                ("users.read", (("uid", 77),)),
                ("users.read", (("uid", 99),)),
            },
        ),
        (
            "disputes.read",
            {"cdid": 11},
            {
                "disputes": [
                    {
                        "cdid": "11",
                        "contractid": "7",
                        "claimantuid": "99",
                        "dispute_tid": "4321",
                    }
                ]
            },
            {
                ("contracts.read", (("cid", 7),)),
                ("threads.read", (("tid", 4321),)),
                ("users.read", (("uid", 99),)),
            },
        ),
        (
            "bratings.read",
            {"crid": 31},
            {
                "bratings": [
                    {"crid": "31", "contractid": "7", "fromid": "101", "toid": "202"}
                ]
            },
            {
                ("contracts.read", (("cid", 7),)),
                ("users.read", (("uid", 101),)),
                ("users.read", (("uid", 202),)),
            },
        ),
        (
            "sigmarket.market.read",
            {"uid": 2047020},
            {"sigmarket/market": [{"uid": "2047020"}]},
            {
                ("users.read", (("uid", 2047020),)),
                ("sigmarket.order.read", (("uid", 2047020),)),
            },
        ),
        (
            "sigmarket.order.read",
            {"oid": 17},
            {"sigmarket/order": [{"smid": "17", "buyer": "2047020", "seller": "1"}]},
            {
                ("sigmarket.order.read", (("smid", 17),)),
                ("users.read", (("uid", 1),)),
                ("users.read", (("uid", 2047020),)),
                ("sigmarket.market.read", (("uid", 1),)),
                ("sigmarket.market.read", (("uid", 2047020),)),
            },
        ),
    ],
)
def test_extended_handlers_emit_hf_flow_with_expected_pivots(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    kwargs: dict[str, int],
    response_payload: dict[str, Any],
    expected_actions: set[tuple[str, tuple[tuple[str, int], ...]]],
) -> None:
    def _fake_read(
        self: HFTransport, asks: dict[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        del asks
        del helper
        return response_payload

    monkeypatch.setattr(HFTransport, "read_raw", _fake_read)

    policy = _policy(
        enabled_capabilities={
            "contracts.read",
            "disputes.read",
            "bratings.read",
            "sigmarket.market.read",
            "sigmarket.order.read",
        },
        enabled_parameter_families={
            "selectors.contract",
            "selectors.dispute",
            "selectors.sigmarket",
            "filters.pagination",
        },
    )
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    handler = build_extended_read_handlers(policy, transport)[tool_name]

    result = handler(**kwargs)

    assert "_hf_flow" in result["structuredContent"]
    flow = result["structuredContent"]["_hf_flow"]
    assert flow["entry_tool"] == tool_name
    assert expected_actions <= _actions_as_tuples(flow)


def test_admin_high_risk_read_result_does_not_emit_hf_flow_until_flow_is_designed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_read(
        self: HFTransport, asks: dict[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        return {"admin/high-risk/read": [{"uid": "7", "risk_score": "99"}]}

    monkeypatch.setattr(HFTransport, "read_raw", _fake_read)
    policy = _policy(
        enabled_capabilities={"admin.high_risk.read"},
        enabled_parameter_families=set(get_tool_spec("admin.high_risk.read").families),
    )
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    handler = build_extended_read_handlers(policy, transport)["admin.high_risk.read"]

    result = handler(page=1)

    assert result["structuredContent"] == {
        "admin/high-risk/read": [{"uid": "7", "risk_score": "99"}]
    }
    assert "_hf_flow" not in result["structuredContent"]


def test_readable_summary_omits_dispute_free_text_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_read(
        self: HFTransport, asks: dict[str, Any], helper: str | None = None
    ) -> dict[str, Any]:
        return {
            "disputes": [
                {
                    "cdid": "11",
                    "status": "1",
                    "claimantnotes": "secret claimant note",
                    "defendantnotes": "secret defendant note",
                }
            ]
        }

    monkeypatch.setattr(HFTransport, "read_raw", _fake_read)

    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset({"disputes.read"}),
        enabled_parameter_families=frozenset(
            {"selectors.dispute", "filters.pagination"}
        ),
        read_output_defaults=ReadOutputDefaults(mode="readable"),
    )
    policy = CapabilityPolicy(settings)
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    handler = build_extended_read_handlers(policy, transport)["disputes.read"]

    result = handler(cdid=11)
    summary = result["content"][0]["text"]
    assert "claimantnotes" not in summary
    assert "defendantnotes" not in summary


@pytest.mark.parametrize(
    ("kwargs",),
    [
        ({"cdid": 11, "did": 12},),
        ({"cdid": 11, "dispute_id": 12},),
        ({"did": 11, "dispute_id": 12},),
    ],
)
def test_extended_handlers_fail_closed_for_conflicting_dispute_selector_aliases(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, int],
) -> None:
    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        pytest.fail(
            "conflicting dispute selector aliases should fail closed before transport is called"
        )

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    policy = _policy(
        enabled_capabilities={"disputes.read"},
        enabled_parameter_families={"selectors.dispute", "filters.pagination"},
    )
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )

    handlers = build_extended_read_handlers(policy, transport)

    with pytest.raises(
        TypeError, match="Conflicting selector values for 'disputes.read'"
    ):
        handlers["disputes.read"](**kwargs)


@pytest.mark.parametrize(
    ("tool_name", "kwargs"),
    [
        ("sigmarket.market.read", {"listing_id": 13}),
        ("sigmarket.order.read", {"listing_id": 17}),
    ],
)
def test_extended_handlers_fail_closed_for_sigmarket_legacy_listing_alias(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    kwargs: dict[str, int],
) -> None:
    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        pytest.fail(
            "sigmarket legacy alias should fail closed before transport is called"
        )

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    policy = _policy(
        enabled_capabilities={
            "sigmarket.market.read",
            "sigmarket.order.read",
        },
        enabled_parameter_families={
            "selectors.sigmarket",
            "filters.pagination",
        },
    )
    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )

    handlers = build_extended_read_handlers(policy, transport)

    with pytest.raises(TypeError, match="listing_id"):
        handlers[tool_name](**kwargs)


def test_list_entries_delegates_to_bytes_helper_and_keeps_amount_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"bytes": [{"uid": "99", "amount": "42.75"}]}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    result = list_entries(
        transport=transport,
        id=7,
        uid=99,
        from_uid=55,
        to_uid=66,
        page=3,
        per_page=999,
        include_amount=True,
    )

    assert captured["route"] == "/read/bytes"
    assert captured["payload"]["asks"]["bytes"]["_id"] == 7
    assert captured["payload"]["asks"]["bytes"]["_uid"] == 99
    assert captured["payload"]["asks"]["bytes"]["_from"] == 55
    assert captured["payload"]["asks"]["bytes"]["_to"] == 66
    assert captured["payload"]["asks"]["bytes"]["_page"] == 3
    assert captured["payload"]["asks"]["bytes"]["_perpage"] == 30
    assert captured["payload"]["asks"]["bytes"]["id"] is True
    assert captured["payload"]["asks"]["bytes"]["dateline"] is True
    assert captured["payload"]["asks"]["bytes"]["type"] is True
    assert captured["payload"]["asks"]["bytes"]["reason"] is True
    assert captured["payload"]["asks"]["bytes"]["amount"] is True
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result["bytes"] == [{"uid": "99", "amount": "42.75"}]


def test_list_bratings_uses_conservative_starter_bundle_and_preserves_mapping_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {
            "bratings": [
                {
                    "crid": "77",
                    "contractid": "12",
                    "fromid": "101",
                    "toid": "202",
                    "dateline": "1710001111",
                    "amount": "250",
                    "message": "good trade",
                    "contract": {"cid": "12"},
                }
            ]
        }

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    result = list_bratings(transport=transport, uid=202, page=2, per_page=3)

    assert captured["route"] == "/read"
    assert captured["payload"]["asks"]["bratings"] == {
        "_page": 2,
        "_perpage": 3,
        "_uid": 202,
        "crid": True,
        "contractid": True,
        "fromid": True,
        "toid": True,
        "dateline": True,
        "amount": True,
        "message": True,
        "contract": True,
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result["bratings"][0]["contract"] == {"cid": "12"}
    assert "from" not in result["bratings"][0]
    assert "to" not in result["bratings"][0]


def test_list_bratings_supports_canonical_selectors_and_optional_expansions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"bratings": []}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    result = list_bratings(
        transport=transport,
        crid=77,
        cid=12,
        uid=202,
        from_uid=101,
        to_uid=202,
        include_from=True,
        include_to=True,
    )

    assert captured["route"] == "/read"
    asks = captured["payload"]["asks"]["bratings"]
    assert asks["_crid"] == 77
    assert asks["_cid"] == 12
    assert asks["_uid"] == 202
    assert asks["_from"] == 101
    assert asks["_to"] == 202
    assert asks["contract"] is True
    assert asks["from"] is True
    assert asks["to"] is True
    assert result == {"bratings": []}


@pytest.mark.parametrize(
    ("tool_name", "call_kwargs", "response_payload", "expected_subset"),
    [
        (
            "contracts",
            {
                "cid": 7,
                "uid": 99,
                "page": 2,
                "per_page": 3,
                "include_inituser": True,
                "include_otheruser": True,
                "include_escrow": True,
                "include_thread": True,
                "include_ibrating": True,
                "include_obrating": True,
            },
            {
                "contracts": [
                    {
                        "cid": "7",
                        "status": "5",
                        "type": "1",
                        "dateline": "1710000000",
                        "tid": "1234",
                        "inituid": "99",
                        "otheruid": "77",
                        "iprice": "10",
                        "icurrency": "USD",
                        "iproduct": "",
                        "oprice": "0",
                        "ocurrency": "other",
                        "oproduct": "service",
                        "idispute": "0",
                        "odispute": "0",
                    }
                ]
            },
            {
                "_page": 2,
                "_perpage": 3,
                "_cid": 7,
                "_uid": 99,
                "inituser": True,
                "otheruser": True,
                "escrow": True,
                "thread": True,
                "ibrating": True,
                "obrating": True,
            },
        ),
        (
            "disputes",
            {
                "cdid": 11,
                "cid": 7,
                "uid": 99,
                "claimantuid": 99,
                "defendantuid": 77,
                "page": 2,
                "per_page": 3,
                "include_contract": True,
                "include_claimant": True,
                "include_defendant": True,
                "include_dispute_thread": True,
            },
            {
                "disputes": [
                    {
                        "cdid": "11",
                        "contractid": "7",
                        "claimantuid": "99",
                        "defendantuid": "77",
                        "dateline": "1710001000",
                        "status": "1",
                        "dispute_tid": "4321",
                        "claimantnotes": "note a",
                        "defendantnotes": "note b",
                    }
                ]
            },
            {
                "_page": 2,
                "_perpage": 3,
                "_cdid": 11,
                "_cid": 7,
                "_uid": 99,
                "_claimantuid": 99,
                "_defendantuid": 77,
                "contract": True,
                "claimant": True,
                "defendant": True,
                "dispute_thread": True,
            },
        ),
    ],
)
def test_contracts_and_disputes_use_conservative_starter_asks_and_preserve_mapping_rows(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    call_kwargs: dict[str, Any],
    response_payload: dict[str, Any],
    expected_subset: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return response_payload

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    if tool_name == "contracts":
        result = list_contracts(transport=transport, **call_kwargs)
    else:
        result = list_disputes(transport=transport, **call_kwargs)

    assert captured["route"] == f"/read/{tool_name}"
    actual_ask = captured["payload"]["asks"][tool_name]
    for key, value in expected_subset.items():
        assert actual_ask[key] == value
    if tool_name == "contracts":
        for field in {
            "cid",
            "dateline",
            "otherdateline",
            "public",
            "timeout_days",
            "timeout",
            "status",
            "istatus",
            "ostatus",
            "cancelstatus",
            "type",
            "tid",
            "inituid",
            "otheruid",
            "muid",
            "iprice",
            "icurrency",
            "iproduct",
            "oprice",
            "ocurrency",
            "oproduct",
            "terms",
            "template_id",
            "oaddress",
            "iaddress",
            "idispute",
            "odispute",
        }:
            assert actual_ask[field] is True
    else:
        for field in {
            "cdid",
            "contractid",
            "claimantuid",
            "defendantuid",
            "dateline",
            "status",
            "dispute_tid",
            "claimantnotes",
            "defendantnotes",
        }:
            assert actual_ask[field] is True
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result == response_payload

    row = result[tool_name][0]
    assert "contract" not in row
    assert "claimant" not in row
    assert "defendant" not in row
    assert "dispute_thread" not in row


@pytest.mark.parametrize(
    ("tool_name", "call_kwargs", "response_payload", "expected_ask"),
    [
        (
            "sigmarket/market",
            {"uid": 2047020, "page": 1, "per_page": 3},
            {
                "sigmarket/market": [
                    {
                        "uid": "2047020",
                        "user": "example",
                        "price": "5",
                        "duration": "30",
                        "active": "1",
                        "sig": "banner",
                        "dateadded": "1710000000",
                        "ppd": "0",
                    }
                ]
            },
            {
                "_page": 1,
                "_perpage": 3,
                "_uid": 2047020,
                "uid": True,
                "user": True,
                "price": True,
                "duration": True,
                "active": True,
                "sig": True,
                "dateadded": True,
                "ppd": True,
            },
        ),
        (
            "sigmarket/order",
            {
                "smid": 17,
                "uid": 2047020,
                "seller": 1,
                "buyer": 2047020,
                "page": 1,
                "per_page": 3,
            },
            {
                "sigmarket/order": [
                    {
                        "smid": "17",
                        "buyer": "2047020",
                        "seller": "1",
                        "startdate": "1710000100",
                        "enddate": "1712592100",
                        "price": "8",
                        "duration": "30",
                        "active": "1",
                    }
                ]
            },
            {
                "_page": 1,
                "_perpage": 3,
                "_smid": 17,
                "_uid": 2047020,
                "_seller": 1,
                "_buyer": 2047020,
                "smid": True,
                "buyer": True,
                "seller": True,
                "startdate": True,
                "enddate": True,
                "price": True,
                "duration": True,
                "active": True,
            },
        ),
    ],
)
def test_sigmarket_market_and_order_use_docs_backed_asks_and_preserve_mapping_rows(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    call_kwargs: dict[str, int],
    response_payload: dict[str, Any],
    expected_ask: dict[str, Any],
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return response_payload

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    if tool_name == "sigmarket/market":
        result = list_market(transport=transport, **call_kwargs)
    else:
        result = list_orders(transport=transport, **call_kwargs)

    assert captured["route"] == f"/read/{tool_name}"
    assert captured["payload"]["asks"][tool_name] == expected_ask
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result == response_payload

    row = result[tool_name][0]
    assert "message" not in row
    assert "subject" not in row


def test_shared_normalizers_handle_avatar_groups_and_upstream_ordering() -> None:
    payload = {
        "bratings": [
            {
                "uid": "7",
                "avatar": "/uploads/avatars/a.png",
                "additionalgroups": "2, 4, ,6",
            },
            {
                "uid": "3",
                "avatar": "https://cdn.example/avatar.png",
                "additionalgroups": "",
            },
        ],
        "sigmarket/order": [
            {"smid": "3", "subject": "older"},
            {"smid": "12", "subject": "newer"},
            {"smid": "7", "subject": "middle"},
        ],
    }

    result = normalize_extended_payload(payload)

    assert (
        result["bratings"][0]["avatar"]
        == "https://hackforums.net/uploads/avatars/a.png"
    )
    assert result["bratings"][0]["additionalgroups"] == ["2", "4", "6"]
    assert result["bratings"][1]["avatar"] == "https://cdn.example/avatar.png"
    assert result["bratings"][1]["additionalgroups"] == []
    assert [row["smid"] for row in result["sigmarket/order"]] == ["3", "12", "7"]


def test_list_orders_preserves_missing_advanced_fields_without_injecting_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        return {"sigmarket/order": {"smid": "5", "subject": "single-row"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    result = list_orders(transport=transport, smid=5, uid=11, page=1, per_page=5)

    assert result["sigmarket/order"] == [{"smid": "5", "subject": "single-row"}]
    assert "message" not in result["sigmarket/order"][0]


def test_list_admin_high_risk_uses_expected_helper_route_and_returns_plain_normalized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"admin/high-risk/read": [{"uid": "7", "risk_score": "99"}]}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(
        token_store=_StubTokenStore(), base_url="https://example.test"
    )
    result = list_admin_high_risk(transport=transport, page=2, per_page=9)

    assert captured["route"] == "/read/admin/high-risk/read"
    assert captured["payload"]["asks"] == {
        "admin/high-risk/read": {"_page": 2, "_perpage": 9}
    }
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result == {"admin/high-risk/read": [{"uid": "7", "risk_score": "99"}]}
    assert "content" not in result
    assert "structuredContent" not in result
