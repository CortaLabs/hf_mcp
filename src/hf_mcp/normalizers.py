from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .mycode import BodyFormat, format_body_text

MAX_PERPAGE = 30
AVATAR_BASE_URL = "https://hackforums.net"
BODY_TEXT_KEYS: frozenset[str] = frozenset({"message"})


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
            normalized[endpoint] = [_normalize_row(raw_rows)] if raw_rows else []
        elif isinstance(raw_rows, list):
            normalized[endpoint] = [_normalize_value(row) for row in raw_rows]
        else:
            normalized[endpoint] = _normalize_value(raw_rows)
    return normalized


def format_body_fields(
    payload: dict[str, Any], body_format: BodyFormat
) -> dict[str, Any]:
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


def _normalize_endpoint_row(row: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    if "avatar" in normalized:
        normalized["avatar"] = _normalize_avatar_path(normalized["avatar"])
    if "additionalgroups" in normalized:
        normalized["additionalgroups"] = _normalize_additional_groups(
            normalized["additionalgroups"]
        )
    return normalized


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
    normalized = normalize_response(payload)
    for endpoint, value in normalized.items():
        if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
            normalized[endpoint] = [_normalize_endpoint_row(item) for item in value]
    return normalized


def _cap_perpage(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("`_perpage` must be numeric.")
    if isinstance(value, str) and not value.strip():
        raise ValueError("`_perpage` cannot be empty.")
    if not isinstance(value, (int, float, str)):
        raise ValueError("`_perpage` must be numeric.")
    try:
        numeric = int(value.strip() if isinstance(value, str) else value)
    except (ValueError, OverflowError):
        # int() text would echo the caller's value; keep the fixed sentence.
        raise ValueError("`_perpage` must be numeric.") from None

    if numeric < 1:
        raise ValueError("`_perpage` must be >= 1.")
    return min(numeric, MAX_PERPAGE)


__all__ = [
    "format_body_fields",
    "normalize_asks",
    "normalize_response",
    "normalize_extended_payload",
]
