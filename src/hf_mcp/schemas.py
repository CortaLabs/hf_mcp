from __future__ import annotations

from typing import Any

from .capabilities import CapabilityPolicy
from .registry import ToolSpec

_FAMILY_PROPERTY_SPECS: dict[str, tuple[tuple[str, dict[str, Any], bool], ...]] = {
    "selectors.user": (("uid", {"type": "integer", "minimum": 1}, True),),
    "selectors.forum": (("fid", {"type": "integer", "minimum": 1}, True),),
    "selectors.thread": (("tid", {"type": "integer", "minimum": 1}, True),),
    "selectors.post": (("pid", {"type": "integer", "minimum": 1}, True),),
    "selectors.bytes": (("target_uid", {"type": "integer", "minimum": 1}, True),),
    "selectors.contract": (("contract_id", {"type": "integer", "minimum": 1}, True),),
    "selectors.dispute": (("dispute_id", {"type": "integer", "minimum": 1}, True),),
    "selectors.sigmarket": (("listing_id", {"type": "integer", "minimum": 1}, True),),
    "filters.pagination": (
        ("page", {"type": "integer", "minimum": 1, "default": 1}, False),
        ("per_page", {"type": "integer", "minimum": 1, "maximum": 30, "default": 30}, False),
    ),
    "fields.me.basic": (("include_basic_fields", {"type": "boolean", "default": True}, False),),
    "fields.me.advanced": (("include_advanced_fields", {"type": "boolean", "default": False}, False),),
    "fields.users.profile": (("include_profile_fields", {"type": "boolean", "default": True}, False),),
    "fields.posts.body": (("include_post_body", {"type": "boolean", "default": True}, False),),
    "fields.bytes.amount": (("include_amount", {"type": "boolean", "default": True}, False),),
    "writes.content": (
        ("subject", {"type": "string", "minLength": 1}, False),
        ("message", {"type": "string", "minLength": 1}, True),
    ),
    "writes.bytes": (
        ("amount", {"type": "integer", "minimum": 1}, True),
        ("note", {"type": "string", "minLength": 1}, False),
    ),
    "confirm.live": (("confirm_live", {"type": "boolean", "const": True}, True),),
}

_TOOL_REQUIRED_OVERRIDES: dict[str, tuple[str, ...]] = {
    "threads.read": ("fid",),
    "posts.read": ("tid",),
    "contracts.read": (),
    "disputes.read": (),
    "bratings.read": (),
    "sigmarket.market.read": (),
    "sigmarket.order.read": (),
}

_TOOL_SELECTOR_PROPERTY_OVERRIDES: dict[str, tuple[tuple[str, str], ...]] = {
    "contracts.read": (("cid", "selectors.contract"), ("uid", "selectors.contract")),
    "disputes.read": (("cdid", "selectors.dispute"), ("uid", "selectors.dispute")),
    "sigmarket.market.read": (("uid", "selectors.sigmarket"),),
    "sigmarket.order.read": (("oid", "selectors.sigmarket"), ("uid", "selectors.sigmarket")),
}

_TOOL_SELECTOR_PROPERTY_REMOVALS: dict[str, tuple[str, ...]] = {
    "contracts.read": ("contract_id",),
    "disputes.read": ("dispute_id", "did"),
    "sigmarket.market.read": ("listing_id",),
    "sigmarket.order.read": ("listing_id",),
}


def _tag_with_family(schema: dict[str, Any], family: str) -> dict[str, Any]:
    tagged = dict(schema)
    tagged["x-hf-parameter-family"] = family
    return tagged


def _base_schema(spec: ToolSpec) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    seen_required: set[str] = set()

    for family in spec.parameter_families:
        for property_name, property_schema, is_required in _FAMILY_PROPERTY_SPECS.get(family, ()):
            if property_name not in properties:
                properties[property_name] = _tag_with_family(property_schema, family)
            if is_required and property_name not in seen_required:
                required.append(property_name)
                seen_required.add(property_name)

    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "x-hf-capability-family": spec.capability_family,
        "x-hf-coverage-family": spec.coverage_family,
        "x-hf-operation": spec.operation,
        "x-hf-helper-path": spec.helper_path,
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def build_tool_schema(spec: ToolSpec, policy: CapabilityPolicy) -> dict[str, Any]:
    schema = policy.prune_schema(spec.tool_name, _base_schema(spec))
    pruned_required = schema.get("required")
    properties = schema.get("properties")
    if isinstance(properties, dict):
        updated_properties = dict(properties)
        for legacy_name in _TOOL_SELECTOR_PROPERTY_REMOVALS.get(spec.tool_name, ()):
            updated_properties.pop(legacy_name, None)
        for selector_name, selector_family in _TOOL_SELECTOR_PROPERTY_OVERRIDES.get(spec.tool_name, ()):
            selector_schema = {"type": "integer", "minimum": 1}
            updated_properties[selector_name] = _tag_with_family(selector_schema, selector_family)
        schema["properties"] = updated_properties
    required_override = _TOOL_REQUIRED_OVERRIDES.get(spec.tool_name)
    if required_override is not None:
        if not required_override:
            schema.pop("required", None)
        else:
            required = [field for field in required_override if field in schema.get("properties", {})]
            if required:
                schema["required"] = required
            elif isinstance(pruned_required, list):
                fallback_required = [field for field in pruned_required if field in schema.get("properties", {})]
                if fallback_required:
                    schema["required"] = fallback_required
                else:
                    schema.pop("required", None)
            else:
                schema.pop("required", None)
    return schema


__all__ = ["build_tool_schema"]
