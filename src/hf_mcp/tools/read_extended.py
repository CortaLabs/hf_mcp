from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, cast

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.flow import attach_hf_flow, build_hf_flow
from hf_mcp.normalizers import format_body_fields, normalize_extended_payload
from hf_mcp.output_modes import ReadOutputMode, resolve_read_output_defaults
from hf_mcp.registry import get_extended_read_specs
from hf_mcp.transport import HFTransport

ReadHandler = Callable[..., dict[str, Any]]
AskBuilder = Callable[..., tuple[dict[str, dict[str, Any]], str]]

_FLOW_EXTENDED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "bytes.read",
        "contracts.read",
        "disputes.read",
        "bratings.read",
        "sigmarket.market.read",
        "sigmarket.order.read",
    }
)

_SELECTOR_ALIASES: dict[str, dict[str, str]] = {
    "bytes.read": {"target_uid": "uid"},
    # Legacy aliases are accepted for backward compatibility only.
    "contracts.read": {"contract_id": "cid"},
    "disputes.read": {"dispute_id": "cdid", "did": "cdid"},
    "sigmarket.order.read": {"oid": "smid"},
}

_BYTES_CORE_FIELDS: tuple[str, ...] = (
    "id",
    "dateline",
    "type",
    "reason",
)

_CONTRACTS_STARTER_FIELDS: tuple[str, ...] = (
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
)

_CONTRACTS_EXPANSION_FIELDS: tuple[str, ...] = (
    "inituser",
    "otheruser",
    "escrow",
    "thread",
    "ibrating",
    "obrating",
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

_DISPUTES_EXPANSION_FIELDS: tuple[str, ...] = (
    "contract",
    "claimant",
    "defendant",
    "dispute_thread",
)

_BRATINGS_STARTER_FIELDS: tuple[str, ...] = (
    "crid",
    "contractid",
    "fromid",
    "toid",
    "dateline",
    "amount",
    "message",
)

_BRATINGS_EXPANSION_FIELDS: tuple[str, ...] = (
    "contract",
    "from",
    "to",
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


def _build_entries_asks(
    *,
    id: int | None = None,
    uid: int | None = None,
    from_uid: int | None = None,
    to_uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_amount: bool = True,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {
        "bytes": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _BYTES_CORE_FIELDS},
        }
    }
    if id is not None:
        asks["bytes"]["_id"] = id
    if uid is not None:
        asks["bytes"]["_uid"] = uid
    if from_uid is not None:
        asks["bytes"]["_from"] = from_uid
    if to_uid is not None:
        asks["bytes"]["_to"] = to_uid
    if include_amount:
        asks["bytes"]["amount"] = True
    return asks


def _build_contracts_asks(
    *,
    cid: int | None = None,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_inituser: bool = False,
    include_otheruser: bool = False,
    include_escrow: bool = False,
    include_thread: bool = False,
    include_ibrating: bool = False,
    include_obrating: bool = False,
) -> dict[str, dict[str, Any]]:
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
    for field, enabled in zip(
        _CONTRACTS_EXPANSION_FIELDS,
        (include_inituser, include_otheruser, include_escrow, include_thread, include_ibrating, include_obrating),
        strict=True,
    ):
        if enabled:
            asks["contracts"][field] = True
    return asks


def _build_disputes_asks(
    *,
    cdid: int | None = None,
    cid: int | None = None,
    uid: int | None = None,
    claimantuid: int | None = None,
    defendantuid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_contract: bool = False,
    include_claimant: bool = False,
    include_defendant: bool = False,
    include_dispute_thread: bool = False,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {
        "disputes": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _DISPUTES_STARTER_FIELDS},
        }
    }
    if cdid is not None:
        asks["disputes"]["_cdid"] = cdid
    if cid is not None:
        asks["disputes"]["_cid"] = cid
    if uid is not None:
        asks["disputes"]["_uid"] = uid
    if claimantuid is not None:
        asks["disputes"]["_claimantuid"] = claimantuid
    if defendantuid is not None:
        asks["disputes"]["_defendantuid"] = defendantuid
    for field, enabled in zip(
        _DISPUTES_EXPANSION_FIELDS,
        (include_contract, include_claimant, include_defendant, include_dispute_thread),
        strict=True,
    ):
        if enabled:
            asks["disputes"][field] = True
    return asks


def _build_bratings_asks(
    *,
    crid: int | None = None,
    cid: int | None = None,
    uid: int | None = None,
    from_uid: int | None = None,
    to_uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_contract: bool = True,
    include_from: bool = False,
    include_to: bool = False,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {
        "bratings": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _BRATINGS_STARTER_FIELDS},
        }
    }
    if crid is not None:
        asks["bratings"]["_crid"] = crid
    if cid is not None:
        asks["bratings"]["_cid"] = cid
    if uid is not None:
        asks["bratings"]["_uid"] = uid
    if from_uid is not None:
        asks["bratings"]["_from"] = from_uid
    if to_uid is not None:
        asks["bratings"]["_to"] = to_uid
    for field, enabled in zip(
        _BRATINGS_EXPANSION_FIELDS,
        (include_contract, include_from, include_to),
        strict=True,
    ):
        if enabled:
            asks["bratings"][field] = True
    return asks


def _build_market_asks(
    *,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {
        "sigmarket/market": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _SIGMARKET_MARKET_FIELDS},
        }
    }
    if uid is not None:
        asks["sigmarket/market"]["_uid"] = uid
    return asks


def _build_orders_asks(
    *,
    smid: int | None = None,
    uid: int | None = None,
    seller: int | None = None,
    buyer: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, dict[str, Any]]:
    asks: dict[str, dict[str, Any]] = {
        "sigmarket/order": {
            "_page": page,
            "_perpage": per_page,
            **{field: True for field in _SIGMARKET_ORDER_FIELDS},
        }
    }
    if smid is not None:
        asks["sigmarket/order"]["_smid"] = smid
    if uid is not None:
        asks["sigmarket/order"]["_uid"] = uid
    if seller is not None:
        asks["sigmarket/order"]["_seller"] = seller
    if buyer is not None:
        asks["sigmarket/order"]["_buyer"] = buyer
    return asks


def _build_admin_high_risk_asks(*, page: int = 1, per_page: int = 30) -> dict[str, dict[str, Any]]:
    return {"admin/high-risk/read": {"_page": page, "_perpage": per_page}}


def _as_rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    if isinstance(value, Mapping):
        return [value]
    return []


def _line_for_entry(entry: Mapping[str, Any]) -> str:
    summary_keys = (
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
    parts: list[str] = []
    for key in summary_keys:
        value = entry.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    return ", ".join(parts) if parts else "entry"


def _build_rows_summary(label: str, rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return f"{label} returned 0 row(s)."
    lines = [f"{label} returned {len(rows)} row(s):"]
    for row in rows:
        lines.append(f"- {_line_for_entry(row)}")
    return "\n".join(lines)


def _extended_root_key(tool_name: str) -> str:
    if tool_name == "sigmarket.market.read":
        return "sigmarket/market"
    if tool_name == "sigmarket.order.read":
        return "sigmarket/order"
    if tool_name == "admin.high_risk.read":
        return "admin/high-risk/read"
    return tool_name.split(".", 1)[0]


def _build_content_summary(tool_name: str, payload: Mapping[str, Any], mode: ReadOutputMode) -> str:
    rows = _as_rows(payload, _extended_root_key(tool_name))
    if mode != "readable":
        return f"{tool_name} returned {len(rows)} row(s)."
    return _build_rows_summary(tool_name, rows)


def _build_raw_resource(tool_name: str, raw_payload: Mapping[str, Any]) -> dict[str, Any]:
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
    arguments: Mapping[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "text", "text": _build_content_summary(tool_name, normalized_payload, mode)}]
    if raw_payload is not None and (mode == "raw" or include_raw_payload):
        content.append(_build_raw_resource(tool_name, raw_payload))
    if tool_name not in _FLOW_EXTENDED_TOOL_NAMES:
        return {"content": content, "structuredContent": normalized_payload}
    flow = build_hf_flow(
        tool_name=tool_name,
        normalized_payload=normalized_payload,
        arguments=arguments,
        source=source,
    )
    return {"content": content, "structuredContent": attach_hf_flow(normalized_payload, flow)}


def list_entries(
    *,
    transport: HFTransport,
    id: int | None = None,
    uid: int | None = None,
    from_uid: int | None = None,
    to_uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_amount: bool = True,
) -> dict[str, Any]:
    asks = _build_entries_asks(
        id=id,
        uid=uid,
        from_uid=from_uid,
        to_uid=to_uid,
        page=page,
        per_page=per_page,
        include_amount=include_amount,
    )
    return normalize_extended_payload(transport.read(asks=asks, helper="bytes"))


def list_contracts(
    *,
    transport: HFTransport,
    cid: int | None = None,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_inituser: bool = False,
    include_otheruser: bool = False,
    include_escrow: bool = False,
    include_thread: bool = False,
    include_ibrating: bool = False,
    include_obrating: bool = False,
) -> dict[str, Any]:
    asks = _build_contracts_asks(
        cid=cid,
        uid=uid,
        page=page,
        per_page=per_page,
        include_inituser=include_inituser,
        include_otheruser=include_otheruser,
        include_escrow=include_escrow,
        include_thread=include_thread,
        include_ibrating=include_ibrating,
        include_obrating=include_obrating,
    )
    return normalize_extended_payload(transport.read(asks=asks, helper="contracts"))


def list_disputes(
    *,
    transport: HFTransport,
    cdid: int | None = None,
    cid: int | None = None,
    uid: int | None = None,
    claimantuid: int | None = None,
    defendantuid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_contract: bool = False,
    include_claimant: bool = False,
    include_defendant: bool = False,
    include_dispute_thread: bool = False,
) -> dict[str, Any]:
    asks = _build_disputes_asks(
        cdid=cdid,
        cid=cid,
        uid=uid,
        claimantuid=claimantuid,
        defendantuid=defendantuid,
        page=page,
        per_page=per_page,
        include_contract=include_contract,
        include_claimant=include_claimant,
        include_defendant=include_defendant,
        include_dispute_thread=include_dispute_thread,
    )
    return normalize_extended_payload(transport.read(asks=asks, helper="disputes"))


def list_bratings(
    *,
    transport: HFTransport,
    crid: int | None = None,
    cid: int | None = None,
    uid: int | None = None,
    from_uid: int | None = None,
    to_uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
    include_contract: bool = True,
    include_from: bool = False,
    include_to: bool = False,
) -> dict[str, Any]:
    asks = _build_bratings_asks(
        crid=crid,
        cid=cid,
        uid=uid,
        from_uid=from_uid,
        to_uid=to_uid,
        page=page,
        per_page=per_page,
        include_contract=include_contract,
        include_from=include_from,
        include_to=include_to,
    )
    return normalize_extended_payload(transport.read(asks=asks, helper="bratings"))


def list_market(
    *,
    transport: HFTransport,
    uid: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks = _build_market_asks(uid=uid, page=page, per_page=per_page)
    return normalize_extended_payload(transport.read(asks=asks, helper="sigmarket/market"))


def list_orders(
    *,
    transport: HFTransport,
    oid: int | None = None,
    smid: int | None = None,
    uid: int | None = None,
    seller: int | None = None,
    buyer: int | None = None,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    if smid is not None and oid is not None and smid != oid:
        raise TypeError(
            "Conflicting selector values for 'sigmarket.order.read': "
            f"'oid'={oid!r} and 'smid'={smid!r}."
        )
    normalized_smid = smid if smid is not None else oid
    asks = _build_orders_asks(
        smid=normalized_smid,
        uid=uid,
        seller=seller,
        buyer=buyer,
        page=page,
        per_page=per_page,
    )
    return normalize_extended_payload(transport.read(asks=asks, helper="sigmarket/order"))


def list_admin_high_risk(
    *,
    transport: HFTransport,
    page: int = 1,
    per_page: int = 30,
) -> dict[str, Any]:
    asks = _build_admin_high_risk_asks(page=page, per_page=per_page)
    return normalize_extended_payload(transport.read(asks=asks, helper="admin/high-risk/read"))


def build_extended_read_handlers(policy: CapabilityPolicy, transport: HFTransport) -> dict[str, ReadHandler]:
    settings = cast(HFMCPSettings, getattr(policy, "_settings"))

    request_builders: dict[str, AskBuilder] = {
        "bytes.read": lambda **kwargs: (_build_entries_asks(**kwargs), "bytes"),
        "contracts.read": lambda **kwargs: (_build_contracts_asks(**kwargs), "contracts"),
        "disputes.read": lambda **kwargs: (_build_disputes_asks(**kwargs), "disputes"),
        "bratings.read": lambda **kwargs: (_build_bratings_asks(**kwargs), "bratings"),
        "sigmarket.market.read": lambda **kwargs: (_build_market_asks(**kwargs), "sigmarket/market"),
        "sigmarket.order.read": lambda **kwargs: (_build_orders_asks(**kwargs), "sigmarket/order"),
        "admin.high_risk.read": lambda **kwargs: (_build_admin_high_risk_asks(**kwargs), "admin/high-risk/read"),
    }

    def _finalize_result(
        *,
        tool_name: str,
        asks: Mapping[str, Any],
        helper: str,
        output_mode: str | None,
        include_raw_payload: bool | None,
        body_format: str | None,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        defaults = resolve_read_output_defaults(settings, output_mode, include_raw_payload, body_format)
        need_raw = defaults.mode == "raw" or defaults.include_raw_payload
        raw_payload: dict[str, Any] | None = None
        if need_raw:
            raw_payload = transport.read_raw(asks=asks, helper=helper)
            normalized_payload = normalize_extended_payload(raw_payload)
        else:
            normalized_payload = normalize_extended_payload(transport.read(asks=asks, helper=helper))
        normalized_payload = format_body_fields(normalized_payload, defaults.body_format)
        return _build_read_tool_result(
            tool_name=tool_name,
            normalized_payload=normalized_payload,
            mode=defaults.mode,
            raw_payload=raw_payload,
            include_raw_payload=defaults.include_raw_payload,
            arguments=arguments,
            source=helper,
        )

    def _build_handler(tool_name: str, builder: AskBuilder) -> ReadHandler:
        def _call(
            *,
            output_mode: str | None = None,
            include_raw_payload: bool | None = None,
            body_format: str | None = None,
            **kwargs: Any,
        ) -> dict[str, Any]:
            normalized_kwargs = _translate_selector_kwargs(tool_name, kwargs)
            asks, helper = builder(**normalized_kwargs)
            return _finalize_result(
                tool_name=tool_name,
                asks=asks,
                helper=helper,
                output_mode=output_mode,
                include_raw_payload=include_raw_payload,
                body_format=body_format,
                arguments=normalized_kwargs,
            )

        return _call

    handlers: dict[str, ReadHandler] = {}
    for spec in get_extended_read_specs():
        if not policy.can_register(spec.tool_name):
            continue
        builder = request_builders.get(spec.tool_name)
        if builder is None:
            continue
        handlers[spec.tool_name] = _build_handler(spec.tool_name, builder)
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
