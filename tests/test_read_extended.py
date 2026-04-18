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
    list_entries,
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
        ("contracts.read", {"contract_id": 7}, "contracts"),
        ("disputes.read", {"dispute_id": 11}, "disputes"),
        ("sigmarket.market.read", {"listing_id": 13}, "sigmarket/market"),
        ("sigmarket.order.read", {"listing_id": 17}, "sigmarket/order"),
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
