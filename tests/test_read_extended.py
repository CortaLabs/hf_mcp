from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.capabilities import CAPABILITY_PARAMETER_FAMILIES, CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.normalizers import normalize_extended_payload
from hf_mcp.registry import get_extended_read_specs, get_tool_spec
from hf_mcp.token_store import TokenBundle
from hf_mcp.tools.read_extended import (
    build_extended_read_handlers,
    list_bratings,
    list_contracts,
    list_disputes,
    list_entries,
    list_market,
    list_orders,
)
from hf_mcp.transport import HFTransport


class _StubTokenStore:
    def require_bundle(self) -> TokenBundle:
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset())


def _policy(*, enabled_capabilities: set[str], enabled_parameter_families: set[str]) -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset(enabled_capabilities),
            enabled_parameter_families=frozenset(enabled_parameter_families),
        )
    )


def test_extended_read_specs_match_registry_rows_and_parameter_families() -> None:
    specs = get_extended_read_specs()
    assert {spec.tool_name for spec in specs} == {
        "bytes.read",
        "contracts.read",
        "disputes.read",
        "bratings.read",
        "sigmarket.market.read",
        "sigmarket.order.read",
        "admin.high_risk.read",
    }
    for spec in specs:
        expected = get_tool_spec(spec.tool_name)
        assert spec.helper_path == expected.helper_path
        if spec.capability_family in CAPABILITY_PARAMETER_FAMILIES:
            assert set(spec.parameter_families) == CAPABILITY_PARAMETER_FAMILIES[spec.capability_family]
        else:
            # Admin/high-risk rows are preserved in the matrix even when no capability mapping exists yet.
            assert spec.parameter_families == ("filters.pagination",)


def test_build_extended_handlers_registers_only_policy_allowed_rows() -> None:
    policy = _policy(
        enabled_capabilities={"bytes.read", "sigmarket.order.read", "admin.high_risk.read"},
        enabled_parameter_families={"selectors.bytes", "fields.bytes.amount", "selectors.sigmarket"},
    )
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    handlers = build_extended_read_handlers(policy, transport)

    assert set(handlers) == {"bytes.read", "sigmarket.order.read"}
    assert "contracts.read" not in handlers
    # Explicit matrix row remains, but policy mapping keeps it fail-closed for now.
    assert "admin.high_risk.read" not in handlers


@pytest.mark.parametrize(
    ("tool_name", "kwargs", "response_key"),
    [
        ("bytes.read", {"target_uid": 5}, "bytes"),
        ("contracts.read", {"cid": 7}, "contracts"),
        ("disputes.read", {"cdid": 11}, "disputes"),
        ("sigmarket.market.read", {"uid": 13}, "sigmarket/market"),
        ("sigmarket.order.read", {"oid": 17}, "sigmarket/order"),
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
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    handlers = build_extended_read_handlers(policy, transport)

    assert handlers[tool_name](**kwargs) == {response_key: []}


@pytest.mark.parametrize(
    ("tool_name", "kwargs", "response_key"),
    [
        ("contracts.read", {"contract_id": 7}, "contracts"),
        ("disputes.read", {"dispute_id": 11}, "disputes"),
        ("disputes.read", {"did": 11}, "disputes"),
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
            "contracts.read",
            "disputes.read",
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
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    handlers = build_extended_read_handlers(policy, transport)

    assert handlers[tool_name](**kwargs) == {response_key: []}


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
        pytest.fail("conflicting dispute selector aliases should fail closed before transport is called")

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    policy = _policy(
        enabled_capabilities={"disputes.read"},
        enabled_parameter_families={"selectors.dispute", "filters.pagination"},
    )
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    handlers = build_extended_read_handlers(policy, transport)

    with pytest.raises(TypeError, match="Conflicting selector values for 'disputes.read'"):
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
        pytest.fail("sigmarket legacy alias should fail closed before transport is called")

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
    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")

    handlers = build_extended_read_handlers(policy, transport)

    with pytest.raises(TypeError, match="listing_id"):
        handlers[tool_name](**kwargs)


def test_list_entries_delegates_to_bytes_helper_and_coerces_amount(
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

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_entries(transport=transport, uid=99, page=3, per_page=999, include_amount=True)

    assert captured["route"] == "/read/bytes"
    assert captured["payload"]["asks"]["bytes"]["_uid"] == 99
    assert captured["payload"]["asks"]["bytes"]["_page"] == 3
    assert captured["payload"]["asks"]["bytes"]["_perpage"] == 30
    assert captured["payload"]["asks"]["bytes"]["amount"] is True
    assert captured["headers"]["Authorization"] == "Bearer token"
    assert result["bytes"] == [{"uid": "99", "amount": "42"}]


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

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_bratings(transport=transport, uid=202, page=2, per_page=3)

    assert captured["route"] == "/read/bratings"
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


@pytest.mark.parametrize(
    ("tool_name", "call_kwargs", "response_payload", "expected_ask"),
    [
        (
            "contracts",
            {"cid": 7, "uid": 99, "page": 2, "per_page": 3},
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
                "cid": True,
                "status": True,
                "type": True,
                "dateline": True,
                "tid": True,
                "inituid": True,
                "otheruid": True,
                "iprice": True,
                "icurrency": True,
                "iproduct": True,
                "oprice": True,
                "ocurrency": True,
                "oproduct": True,
                "idispute": True,
                "odispute": True,
            },
        ),
        (
            "disputes",
            {"cdid": 11, "uid": 99, "page": 2, "per_page": 3},
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
                "_uid": 99,
                "cdid": True,
                "contractid": True,
                "claimantuid": True,
                "defendantuid": True,
                "dateline": True,
                "status": True,
                "dispute_tid": True,
                "claimantnotes": True,
                "defendantnotes": True,
            },
        ),
    ],
)
def test_contracts_and_disputes_use_conservative_starter_asks_and_preserve_mapping_rows(
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

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    if tool_name == "contracts":
        result = list_contracts(transport=transport, **call_kwargs)
    else:
        result = list_disputes(transport=transport, **call_kwargs)

    assert captured["route"] == f"/read/{tool_name}"
    assert captured["payload"]["asks"][tool_name] == expected_ask
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
            {"oid": 17, "uid": 2047020, "page": 1, "per_page": 3},
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
                "_oid": 17,
                "_uid": 2047020,
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

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
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


def test_shared_normalizers_handle_avatar_groups_and_ordering() -> None:
    payload = {
        "bratings": [
            {"uid": "7", "avatar": "/uploads/avatars/a.png", "additionalgroups": "2, 4, ,6"},
            {"uid": "3", "avatar": "https://cdn.example/avatar.png", "additionalgroups": ""},
        ],
        "sigmarket/order": [
            {"oid": "3", "subject": "older"},
            {"oid": "12", "subject": "newer"},
            {"oid": "7", "subject": "middle"},
        ],
    }

    result = normalize_extended_payload(payload)

    assert result["bratings"][0]["avatar"] == "https://hackforums.net/uploads/avatars/a.png"
    assert result["bratings"][0]["additionalgroups"] == ["2", "4", "6"]
    assert result["bratings"][1]["avatar"] == "https://cdn.example/avatar.png"
    assert result["bratings"][1]["additionalgroups"] == []
    assert [row["oid"] for row in result["sigmarket/order"]] == ["12", "7", "3"]


def test_list_orders_preserves_missing_advanced_fields_without_injecting_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_post_json(
        self: HFTransport,
        route: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        return {"sigmarket/order": {"oid": "5", "subject": "single-row"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = list_orders(transport=transport, oid=5, uid=11, page=1, per_page=5)

    assert result["sigmarket/order"] == [{"oid": "5", "subject": "single-row"}]
    assert "message" not in result["sigmarket/order"][0]
