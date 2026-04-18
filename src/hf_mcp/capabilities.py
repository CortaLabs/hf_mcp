from __future__ import annotations

from copy import deepcopy
from typing import Any

from hf_mcp.config import HFMCPSettings

CAPABILITY_PARAMETER_FAMILIES: dict[str, frozenset[str]] = {
    "me.read": frozenset({"selectors.user", "fields.me.basic", "fields.me.advanced"}),
    "users.read": frozenset({"selectors.user", "filters.pagination", "fields.users.profile"}),
    "forums.read": frozenset({"selectors.forum", "filters.pagination"}),
    "threads.read": frozenset({"selectors.forum", "selectors.thread", "filters.pagination"}),
    "posts.read": frozenset(
        {"selectors.thread", "selectors.post", "filters.pagination", "fields.posts.body"}
    ),
    "bytes.read": frozenset({"selectors.bytes", "fields.bytes.amount"}),
    "contracts.read": frozenset({"selectors.contract", "filters.pagination"}),
    "disputes.read": frozenset({"selectors.dispute", "filters.pagination"}),
    "bratings.read": frozenset({"selectors.user", "filters.pagination"}),
    "sigmarket.market.read": frozenset({"selectors.sigmarket", "filters.pagination"}),
    "sigmarket.order.read": frozenset({"selectors.sigmarket", "filters.pagination"}),
    "admin.high_risk.read": frozenset({"filters.pagination"}),
    "threads.create": frozenset({"selectors.forum", "writes.content", "confirm.live"}),
    "posts.reply": frozenset({"selectors.thread", "writes.content", "confirm.live"}),
    "bytes.transfer": frozenset({"selectors.bytes", "writes.bytes", "confirm.live"}),
    "bytes.deposit": frozenset({"selectors.bytes", "writes.bytes", "confirm.live"}),
    "bytes.withdraw": frozenset({"selectors.bytes", "writes.bytes", "confirm.live"}),
    "bytes.bump": frozenset({"selectors.bytes", "writes.bytes", "confirm.live"}),
    "contracts.write": frozenset({"selectors.contract", "writes.content", "confirm.live"}),
    "sigmarket.write": frozenset({"selectors.sigmarket", "writes.content", "confirm.live"}),
    "admin.high_risk.write": frozenset({"writes.content", "confirm.live"}),
}

TOOL_TO_CAPABILITY: dict[str, str] = {capability: capability for capability in CAPABILITY_PARAMETER_FAMILIES}


class CapabilityPolicy:
    def __init__(self, settings: HFMCPSettings) -> None:
        self._settings = settings

    def can_register(self, tool_name: str) -> bool:
        capability = TOOL_TO_CAPABILITY.get(tool_name)
        if capability is None:
            return False
        if capability not in self._settings.enabled_capabilities:
            return False
        families = CAPABILITY_PARAMETER_FAMILIES.get(capability, frozenset())
        return bool(families & self._settings.enabled_parameter_families)

    def allowed_parameter_families(self, tool_name: str) -> frozenset[str]:
        if not self.can_register(tool_name):
            return frozenset()
        capability = TOOL_TO_CAPABILITY[tool_name]
        configured = self._settings.enabled_parameter_families
        return CAPABILITY_PARAMETER_FAMILIES.get(capability, frozenset()) & configured

    def prune_schema(self, tool_name: str, schema: dict[str, Any]) -> dict[str, Any]:
        if not self.can_register(tool_name):
            return {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }

        pruned = deepcopy(schema)
        allowed = self.allowed_parameter_families(tool_name)
        kept = _prune_schema_node(pruned, allowed)
        if not isinstance(kept, dict):
            return {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }
        return kept


def _prune_schema_node(node: Any, allowed: frozenset[str]) -> Any:
    if not isinstance(node, dict):
        return node

    family = node.get("x-hf-parameter-family")
    if isinstance(family, str) and family not in allowed:
        return None

    families = node.get("x-hf-parameter-families")
    if isinstance(families, list):
        filtered = [item for item in families if isinstance(item, str) and item in allowed]
        if not filtered:
            return None
        node["x-hf-parameter-families"] = filtered

    properties = node.get("properties")
    if isinstance(properties, dict):
        original_required = node.get("required")
        required = set(original_required) if isinstance(original_required, list) else set()

        pruned_properties: dict[str, Any] = {}
        for prop_name, prop_schema in properties.items():
            pruned_property = _prune_schema_node(prop_schema, allowed)
            if pruned_property is None:
                required.discard(prop_name)
                continue
            pruned_properties[prop_name] = pruned_property

        node["properties"] = pruned_properties
        if isinstance(original_required, list):
            node["required"] = [name for name in original_required if name in pruned_properties]

    items = node.get("items")
    if items is not None:
        pruned_items = _prune_schema_node(items, allowed)
        if pruned_items is None:
            node.pop("items", None)
        else:
            node["items"] = pruned_items

    for combinator in ("allOf", "anyOf", "oneOf"):
        branch = node.get(combinator)
        if isinstance(branch, list):
            pruned_branch = []
            for item in branch:
                pruned_item = _prune_schema_node(item, allowed)
                if pruned_item is not None:
                    pruned_branch.append(pruned_item)
            node[combinator] = pruned_branch

    return node


__all__ = [
    "CAPABILITY_PARAMETER_FAMILIES",
    "CapabilityPolicy",
    "TOOL_TO_CAPABILITY",
]
