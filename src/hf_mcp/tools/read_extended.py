from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.normalizers import normalize_extended_payload
from hf_mcp.registry import get_extended_read_specs
from hf_mcp.transport import HFTransport

ReadHandler = Callable[..., dict[str, Any]]

_SELECTOR_ALIASES: dict[str, dict[str, str]] = {
    "bytes.read": {"target_uid": "uid"},
    # Legacy aliases are accepted for backward compatibility only.
    "contracts.read": {"contract_id": "cid"},
    "disputes.read": {"dispute_id": "cdid", "did": "cdid"},
}

_CONTRACTS_STARTER_FIELDS: tuple[str, ...] = (
    "cid",
    "status",
    "type",
    "dateline",
    "tid",
    "inituid",
    "otheruid",
    "iprice",
    "icurrency",
    "iproduct",
    "oprice",
    "ocurrency",
    "oproduct",
    "idispute",
    "odispute",
)

_DISPUTES_STARTER_FIELDS: tuple[str, ...] = (
    "cdid",
    "contractid",
    "claimantuid",
    "defendantuid",
    "dateline",
    "status",
    "dispute_tid",
    "claimantnotes",
    "defendantnotes",
)

_BRATINGS_STARTER_FIELDS: tuple[str, ...] = (
    "crid",
    "contractid",
    "fromid",
    "toid",
    "dateline",
    "amount",
    "message",
    "contract",
)

_SIGMARKET_MARKET_FIELDS: tuple[str, ...] = (
    "uid",
    "user",
    "price",
    "duration",
    "active",
    "sig",
    "dateadded",
    "ppd",
)

_SIGMARKET_ORDER_FIELDS: tuple[str, ...] = (
    "smid",
    "buyer",
    "seller",
    "startdate",
    "enddate",
    "price",
    "duration",
    "active",
)


def _translate_selector_kwargs(tool_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    translated = dict(kwargs)
    for public_name, internal_name in _SELECTOR_ALIASES.get(tool_name, {}).items():
        if public_name not in translated:
            continue
        public_value = translated.pop(public_name)
        internal_value = translated.get(internal_name)
        if internal_value is not None and internal_value != public_value:
            raise TypeError(
                f"Conflicting selector values for '{tool_name}': "
                f"'{public_name}'={public_value!r} and '{internal_name}'={internal_value!r}."
            )
        translated[internal_name] = public_value
    return translated


def list_entries(
    *,
    transport: HFTransport,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_amount: bool = True,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {"bytes": {"_page": page, "_perpage": per_page}}
    if uid is not None:
        asks["bytes"]["_uid"] = uid
    if include_amount:
        asks["bytes"]["amount"] = True
    return normalize_extended_payload(transport.read(asks=asks, helper="bytes"))


def list_contracts(
    *,
    transport: HFTransport,
    cid: int | None = None,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "contracts": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _CONTRACTS_STARTER_FIELDS},
        }
    }
    if cid is not None:
        asks["contracts"]["_cid"] = cid
    if uid is not None:
        asks["contracts"]["_uid"] = uid
    return normalize_extended_payload(transport.read(asks=asks, helper="contracts"))


def list_disputes(
    *,
    transport: HFTransport,
    cdid: int | None = None,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "disputes": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _DISPUTES_STARTER_FIELDS},
        }
    }
    if cdid is not None:
        asks["disputes"]["_cdid"] = cdid
    if uid is not None:
        asks["disputes"]["_uid"] = uid
    return normalize_extended_payload(transport.read(asks=asks, helper="disputes"))


def list_bratings(
    *,
    transport: HFTransport,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "bratings": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _BRATINGS_STARTER_FIELDS},
        }
    }
    if uid is not None:
        asks["bratings"]["_uid"] = uid
    return normalize_extended_payload(transport.read(asks=asks, helper="bratings"))


def list_market(
    *,
    transport: HFTransport,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "sigmarket/market": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _SIGMARKET_MARKET_FIELDS},
        }
    }
    if uid is not None:
        asks["sigmarket/market"]["_uid"] = uid
    return normalize_extended_payload(transport.read(asks=asks, helper="sigmarket/market"))


def list_orders(
    *,
    transport: HFTransport,
    oid: int | None = None,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks: dict[str, dict[str, Any]] = {
        "sigmarket/order": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _SIGMARKET_ORDER_FIELDS},
        }
    }
    if oid is not None:
        asks["sigmarket/order"]["_oid"] = oid
    if uid is not None:
        asks["sigmarket/order"]["_uid"] = uid
    return normalize_extended_payload(transport.read(asks=asks, helper="sigmarket/order"))


def list_admin_high_risk(
    *,
    transport: HFTransport,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks = {"admin/high-risk/read": {"_page": page, "_perpage": per_page}}
    return normalize_extended_payload(transport.read(asks=asks, helper="admin/high-risk/read"))


def build_extended_read_handlers(policy: CapabilityPolicy, transport: HFTransport) -> dict[str, ReadHandler]:
    tool_handlers: dict[str, Callable[..., dict[str, Any]]] = {
        "bytes.read": list_entries,
        "contracts.read": list_contracts,
        "disputes.read": list_disputes,
        "bratings.read": list_bratings,
        "sigmarket.market.read": list_market,
        "sigmarket.order.read": list_orders,
        "admin.high_risk.read": list_admin_high_risk,
    }

    def _build_handler(tool_name: str, handler: Callable[..., dict[str, Any]]) -> ReadHandler:
        def _call(**kwargs: Any) -> dict[str, Any]:
            normalized_kwargs = _translate_selector_kwargs(tool_name, kwargs)
            return handler(transport=transport, **normalized_kwargs)

        return _call

    handlers: dict[str, ReadHandler] = {}
    for spec in get_extended_read_specs():
        if not policy.can_register(spec.tool_name):
            continue
        handler = tool_handlers.get(spec.tool_name)
        if handler is None:
            continue
        handlers[spec.tool_name] = _build_handler(spec.tool_name, handler)
    return handlers


__all__ = [
    "build_extended_read_handlers",
    "list_admin_high_risk",
    "list_bratings",
    "list_contracts",
    "list_disputes",
    "list_entries",
    "list_market",
    "list_orders",
]
