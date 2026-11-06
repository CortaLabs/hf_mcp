from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, cast

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.hf_client import DEFAULT_PAGE, DEFAULT_PER_PAGE, HFClient, ReadRequest
from hf_mcp.normalizers import normalize_extended_payload
from hf_mcp.registry import get_specs
from hf_mcp.tools.read_core import ReadHandler, make_read_handler, selectors_of
from hf_mcp.transport import HFTransport

_SELECTOR_ALIASES: dict[str, dict[str, str]] = {
    "bytes.read": {"target_uid": "uid"},
    # Legacy aliases are accepted for backward compatibility only.
    "contracts.read": {"contract_id": "cid"},
    "disputes.read": {"dispute_id": "cdid", "did": "cdid"},
    "sigmarket.order.read": {"oid": "smid"},
}


@dataclass(frozen=True, slots=True)
class _ExtendedTool:
    resource: str
    selectors: tuple[str, ...]
    base_fields: frozenset[str]
    # include_* keyword -> (field, default)
    toggles: Mapping[str, tuple[str, bool]]
    with_flow: bool = True


_EXTENDED_TOOLS: dict[str, _ExtendedTool] = {
    "bytes.read": _ExtendedTool(
        "bytes",
        ("id", "uid", "from_uid", "to_uid"),
        frozenset({"core"}),
        {"include_amount": ("amount", True)},
    ),
    "contracts.read": _ExtendedTool(
        "contracts",
        ("cid", "uid"),
        frozenset({"starter"}),
        {
            "include_inituser": ("inituser", False),
            "include_otheruser": ("otheruser", False),
            "include_escrow": ("escrow", False),
            "include_thread": ("thread", False),
            "include_ibrating": ("ibrating", False),
            "include_obrating": ("obrating", False),
        },
    ),
    "disputes.read": _ExtendedTool(
        "disputes",
        ("cdid", "cid", "uid", "claimantuid", "defendantuid"),
        frozenset({"starter"}),
        {
            "include_contract": ("contract", False),
            "include_claimant": ("claimant", False),
            "include_defendant": ("defendant", False),
            "include_dispute_thread": ("dispute_thread", False),
        },
    ),
    "bratings.read": _ExtendedTool(
        "bratings",
        ("crid", "cid", "uid", "from_uid", "to_uid"),
        frozenset({"starter"}),
        {
            "include_contract": ("contract", True),
            "include_from": ("from", False),
            "include_to": ("to", False),
        },
    ),
    "sigmarket.market.read": _ExtendedTool(
        "sigmarket.market", ("uid",), frozenset({"market"}), {}
    ),
    "sigmarket.order.read": _ExtendedTool(
        "sigmarket.order",
        ("smid", "uid", "seller", "buyer"),
        frozenset({"order"}),
        {},
    ),
    "admin.high_risk.read": _ExtendedTool(
        "admin.high_risk", (), frozenset(), {}, with_flow=False
    ),
}


def _translate_selector_kwargs(
    tool_name: str, kwargs: dict[str, Any]
) -> dict[str, Any]:
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


def _extended_request(
    tool_name: str, /, **kwargs: Any
) -> tuple[ReadRequest, dict[str, Any]]:
    tool = _EXTENDED_TOOLS[tool_name]
    arguments = _translate_selector_kwargs(tool_name, kwargs)
    remaining = dict(arguments)
    page = remaining.pop("page", DEFAULT_PAGE)
    per_page = remaining.pop("per_page", DEFAULT_PER_PAGE)
    selectors = selectors_of(
        **{name: remaining.pop(name, None) for name in tool.selectors}
    )
    fields = set(tool.base_fields)
    for keyword, (field, default) in tool.toggles.items():
        if remaining.pop(keyword, default):
            fields.add(field)
    if remaining:
        names = ", ".join(sorted(remaining))
        raise TypeError(f"Unexpected argument(s) for '{tool_name}': {names}.")
    request = ReadRequest(tool.resource, selectors, frozenset(fields), page, per_page)
    return request, arguments


def _read_extended(
    transport: HFTransport, tool_name: str, kwargs: dict[str, Any]
) -> dict[str, Any]:
    request, _ = _extended_request(tool_name, **kwargs)
    return normalize_extended_payload(HFClient(transport).read(request))


def list_entries(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_extended(transport, "bytes.read", kwargs)


def list_contracts(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_extended(transport, "contracts.read", kwargs)


def list_disputes(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_extended(transport, "disputes.read", kwargs)


def list_bratings(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_extended(transport, "bratings.read", kwargs)


def list_market(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_extended(transport, "sigmarket.market.read", kwargs)


def list_orders(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_extended(transport, "sigmarket.order.read", kwargs)


def list_admin_high_risk(*, transport: HFTransport, **kwargs: Any) -> dict[str, Any]:
    return _read_extended(transport, "admin.high_risk.read", kwargs)


def build_extended_read_handlers(
    policy: CapabilityPolicy, transport: HFTransport
) -> dict[str, ReadHandler]:
    settings = cast(HFMCPSettings, getattr(policy, "_settings"))
    client = HFClient(transport)
    handlers: dict[str, ReadHandler] = {}
    for spec in get_specs("extended_read"):
        if not policy.can_register(spec.name) or spec.name not in _EXTENDED_TOOLS:
            continue

        handlers[spec.name] = make_read_handler(
            client=client,
            settings=settings,
            tool_name=spec.name,
            build=partial(_extended_request, spec.name),
            normalize=normalize_extended_payload,
            with_flow=_EXTENDED_TOOLS[spec.name].with_flow,
        )
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
