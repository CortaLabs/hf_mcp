from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from .config import HFMCPSettings

ReadOutputMode = Literal["readable", "structured", "raw"]
_VALID_READ_OUTPUT_MODES: frozenset[str] = frozenset({"readable", "structured", "raw"})


@dataclass(frozen=True, slots=True)
class ReadOutputDefaults:
    mode: ReadOutputMode = "readable"
    include_raw_payload: bool = False


def _coerce_output_mode(raw_value: object, *, field_name: str) -> ReadOutputMode:
    if not isinstance(raw_value, str):
        raise ValueError(f"`{field_name}` must be a string.")
    mode = raw_value.strip()
    if mode not in _VALID_READ_OUTPUT_MODES:
        valid = ", ".join(sorted(_VALID_READ_OUTPUT_MODES))
        raise ValueError(f"Unknown read output mode '{mode}'. Valid modes: {valid}.")
    return cast(ReadOutputMode, mode)


def _coerce_bool(raw_value: object, *, field_name: str) -> bool:
    if not isinstance(raw_value, bool):
        raise ValueError(f"`{field_name}` must be a boolean.")
    return raw_value


def parse_read_output_defaults(raw_value: object) -> ReadOutputDefaults:
    defaults = ReadOutputDefaults()
    if raw_value is None:
        return defaults
    if not isinstance(raw_value, dict):
        raise ValueError("`read_output_defaults` must be a mapping.")

    mode = defaults.mode
    include_raw_payload = defaults.include_raw_payload

    if "mode" in raw_value:
        mode = _coerce_output_mode(raw_value["mode"], field_name="read_output_defaults.mode")
    if "include_raw_payload" in raw_value:
        include_raw_payload = _coerce_bool(
            raw_value["include_raw_payload"],
            field_name="read_output_defaults.include_raw_payload",
        )
    return ReadOutputDefaults(mode=mode, include_raw_payload=include_raw_payload)


def resolve_read_output_defaults(
    settings: HFMCPSettings,
    output_mode: str | None,
    include_raw_payload: bool | None,
) -> ReadOutputDefaults:
    base_defaults = getattr(settings, "read_output_defaults", ReadOutputDefaults())
    resolved_mode = (
        base_defaults.mode
        if output_mode is None
        else _coerce_output_mode(output_mode, field_name="output_mode")
    )
    resolved_include_raw_payload = (
        base_defaults.include_raw_payload
        if include_raw_payload is None
        else _coerce_bool(include_raw_payload, field_name="include_raw_payload")
    )
    return ReadOutputDefaults(
        mode=resolved_mode,
        include_raw_payload=resolved_include_raw_payload,
    )


__all__ = ["ReadOutputDefaults", "resolve_read_output_defaults"]
