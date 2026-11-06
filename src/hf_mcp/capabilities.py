"""Authorization policy: which rows of ``registry.TOOLS`` are published, and how.

A tool is registrable when its capability is enabled, every one of its
``required_families`` is enabled, and, for tools with an ``anyOf``, at least one
branch survives pruning. Presets live in ``config`` (derived from ``TOOLS``).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .config import HFMCPSettings
from .registry import FAMILY_KEY, WIRE_KEY, ToolSpec, get_tool_spec

_INTERNAL_KEYS = (FAMILY_KEY, WIRE_KEY)


class CapabilityPolicy:
    def __init__(self, settings: HFMCPSettings) -> None:
        self._settings = settings

    def can_register(self, tool_name: str) -> bool:
        try:
            spec = get_tool_spec(tool_name)
        except KeyError:
            return False
        return self._registrable(spec)

    def allowed_parameter_families(self, tool_name: str) -> frozenset[str]:
        if not self.can_register(tool_name):
            return frozenset()
        return (
            get_tool_spec(tool_name).families
            & self._settings.enabled_parameter_families
        )

    def input_schema(self, spec: ToolSpec) -> dict[str, Any]:
        """Return the published input schema: a pruned copy with no internal keys."""
        enabled = self._settings.enabled_parameter_families
        schema = deepcopy(spec.input_schema)
        properties = {
            name: prop
            for name, prop in schema["properties"].items()
            if prop[FAMILY_KEY] in enabled
        }
        schema["properties"] = properties
        required = [name for name in schema.get("required", ()) if name in properties]
        if required:
            schema["required"] = required
        else:
            schema.pop("required", None)
        branches = [
            branch
            for branch in schema.get("anyOf", ())
            if all(name in properties for name in branch["required"])
        ]
        if branches:
            schema["anyOf"] = branches
        else:
            schema.pop("anyOf", None)
        for prop in properties.values():
            for key in _INTERNAL_KEYS:
                prop.pop(key, None)
        return schema

    def _registrable(self, spec: ToolSpec) -> bool:
        settings = self._settings
        if spec.capability not in settings.enabled_capabilities:
            return False
        if not spec.required_families <= settings.enabled_parameter_families:
            return False
        if "anyOf" not in spec.input_schema:
            return True
        return bool(self.input_schema(spec).get("anyOf"))


__all__ = ["CapabilityPolicy"]
