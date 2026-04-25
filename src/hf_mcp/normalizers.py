from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .mycode import BodyFormat, format_body_text

MAX_PERPAGE = 30
AVATAR_BASE_URL = "https://hackforums.net"
BODY_TEXT_KEYS: frozenset[str] = frozenset({"message"})

_ORDERING_KEYS: dict[str, tuple[str, ...]] = {
    "contracts": ("cid", "id"),
    "disputes": ("did", "id"),
    "bratings": ("id", "uid"),
    "sigmarket/market": ("mid", "id"),
    "sigmarket/order": ("smid", "oid", "id"),
}


def normalize_asks(asks: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if not asks:
        raise ValueError("`asks` must contain at least one endpoint request.")

    normalized: dict[str, dict[str, Any]] = {}
    for endpoint, endpoint_payload in asks.items():
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("Endpoint keys in `asks` must be non-empty strings.")
        if not isinstance(endpoint_payload, Mapping):
            raise ValueError(f"`asks[{endpoint}]` must be a mapping.")

        entry: dict[str, Any] = {}
        for key, value in endpoint_payload.items():
            if key == "_perpage":
                entry[key] = _cap_perpage(value)
            else:
                entry[key] = value
        normalized[endpoint.strip()] = entry
    return normalized


def normalize_response(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for endpoint, raw_rows in payload.items():
        if isinstance(raw_rows, Mapping):
            normalized[endpoint] = [_normalize_row(raw_rows)]
        elif isinstance(raw_rows, list):
            normalized[endpoint] = [_normalize_value(row) for row in raw_rows]
        else:
            normalized[endpoint] = _normalize_value(raw_rows)
    return normalized


def format_body_fields(payload: dict[str, Any], body_format: BodyFormat) -> dict[str, Any]:
    if body_format == "raw":
        return payload
    return _format_body_value(payload, body_format)


def _normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in row.items():
        normalized[str(key)] = _normalize_value(value)
    return normalized


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _normalize_row(value)
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return value


def _format_body_value(value: Any, body_format: BodyFormat) -> Any:
    if isinstance(value, Mapping):
        formatted: dict[str, Any] = {}
        for key, nested_value in value.items():
            key_name = str(key)
            if key_name in BODY_TEXT_KEYS and isinstance(nested_value, str):
                formatted[key_name] = format_body_text(nested_value, body_format)
            else:
                formatted[key_name] = _format_body_value(nested_value, body_format)
        return formatted
    if isinstance(value, list):
        return [_format_body_value(item, body_format) for item in value]
    return value


def _normalize_endpoint_rows(endpoint: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_rows = [_normalize_endpoint_row(endpoint, row) for row in rows]
    return _order_endpoint_rows(endpoint, normalized_rows)


def _normalize_endpoint_row(endpoint: str, row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    if endpoint == "bytes" and "amount" in normalized:
        normalized["amount"] = _normalize_bytes_amount(normalized["amount"])
    if "avatar" in normalized:
        normalized["avatar"] = _normalize_avatar_path(normalized["avatar"])
    if "additionalgroups" in normalized:
        normalized["additionalgroups"] = _normalize_additional_groups(normalized["additionalgroups"])
    return normalized


def _order_endpoint_rows(endpoint: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = _ORDERING_KEYS.get(endpoint)
    if not keys:
        return rows
    for key in keys:
        if any(key in row for row in rows):
            return sorted(rows, key=lambda row: _sort_key(row.get(key)), reverse=True)
    return rows


def _sort_key(value: Any) -> tuple[int, float | str]:
    if value is None:
        return (0, "")
    if isinstance(value, (int, float)):
        return (1, float(value))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return (0, "")
        try:
            return (1, float(stripped))
        except ValueError:
            return (0, stripped)
    return (0, str(value))


def _normalize_bytes_amount(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return str(int(float(value)))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return value
        try:
            return str(int(float(stripped)))
        except ValueError:
            return value
    return value


def _normalize_avatar_path(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"{AVATAR_BASE_URL}{value}"
    return value


def _normalize_additional_groups(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return [group for group in (item.strip() for item in value.split(",")) if group]


def normalize_extended_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for endpoint, value in payload.items():
        if isinstance(value, Mapping):
            normalized[endpoint] = _normalize_endpoint_rows(endpoint, [dict(value)])
            continue
        if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
            normalized[endpoint] = _normalize_endpoint_rows(endpoint, [dict(item) for item in value])
            continue
        normalized[endpoint] = value
    return normalized


def _cap_perpage(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("`_perpage` must be numeric.")
    if isinstance(value, int):
        numeric = value
    elif isinstance(value, float):
        numeric = int(value)
    elif isinstance(value, str):
        value = value.strip()
        if not value:
            raise ValueError("`_perpage` cannot be empty.")
        numeric = int(value)
    else:
        raise ValueError("`_perpage` must be numeric.")

    if numeric < 1:
        raise ValueError("`_perpage` must be >= 1.")
    return min(numeric, MAX_PERPAGE)


__all__ = ["format_body_fields", "normalize_asks", "normalize_response", "normalize_extended_payload"]
