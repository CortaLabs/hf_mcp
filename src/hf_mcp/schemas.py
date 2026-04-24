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
    "formatting.content": (
        ("message", {"type": "string", "minLength": 1}, False),
        (
            "source_path",
            {
                "type": "string",
                "minLength": 1,
                "description": "Optional .md, .mycode, or .txt source file inside the hf_mcp draft cache directory.",
            },
            False,
        ),
        (
            "message_format",
            {
                "type": "string",
                "enum": ["mycode", "markdown"],
                "default": "markdown",
                "description": "Input format to simulate before any live write.",
            },
            False,
        ),
    ),
    "writes.content": (
        ("subject", {"type": "string", "minLength": 1}, False),
        ("message", {"type": "string", "minLength": 1}, False),
        (
            "draft_id",
            {
                "type": "string",
                "pattern": "^[a-f0-9]{32}$",
                "description": "Optional cached formatting.preflight draft id to publish without resending message text.",
            },
            False,
        ),
        (
            "draft_path",
            {
                "type": "string",
                "minLength": 1,
                "description": "Optional cached formatting.preflight JSON artifact path inside the hf_mcp draft cache directory.",
            },
            False,
        ),
        (
            "message_format",
            {
                "type": "string",
                "enum": ["mycode", "markdown"],
                "default": "mycode",
                "description": "Input format for message; markdown is converted to Hack Forums MyCode before writing.",
            },
            False,
        ),
    ),
    "writes.bytes": (
        ("amount", {"type": "integer", "minimum": 1}, True),
        ("note", {"type": "string", "minLength": 1}, False),
    ),
    "confirm.live": (("confirm_live", {"type": "boolean", "const": True}, True),),
    "drafts.selector": (
        (
            "draft_id",
            {
                "type": "string",
                "pattern": "^[a-f0-9]{32}$",
            },
            False,
        ),
        (
            "draft_path",
            {
                "type": "string",
                "minLength": 1,
            },
            False,
        ),
    ),
    "drafts.filters": (
        (
            "status",
            {
                "type": "string",
                "enum": ["draft", "ready", "approved", "archived"],
            },
            False,
        ),
        ("category", {"type": "string", "minLength": 1}, False),
        ("title", {"type": "string", "minLength": 1}, False),
        ("scheduled_before", {"type": "string", "format": "date-time"}, False),
        ("scheduled_after", {"type": "string", "format": "date-time"}, False),
        ("limit", {"type": "integer", "minimum": 0, "default": 50}, False),
        ("offset", {"type": "integer", "minimum": 0, "default": 0}, False),
    ),
    "drafts.metadata": (
        ("title", {"type": "string"}, False),
        ("category", {"type": "string"}, False),
        (
            "status",
            {
                "type": "string",
                "enum": ["draft", "ready", "approved", "archived"],
            },
            False,
        ),
        ("scheduled_at", {"type": "string", "format": "date-time"}, False),
    ),
    "drafts.confirm_delete": (("confirm_delete", {"type": "boolean", "const": True}, True),),
}

_TOOL_REQUIRED_OVERRIDES: dict[str, tuple[str, ...]] = {
    "threads.read": ("fid",),
    "posts.read": ("tid",),
    "contracts.read": (),
    "disputes.read": (),
    "bratings.read": (),
    "sigmarket.market.read": (),
    "sigmarket.order.read": (),
    "threads.create": ("fid", "subject", "confirm_live"),
    "posts.reply": ("tid", "confirm_live"),
    "bytes.deposit": ("amount", "confirm_live"),
    "bytes.withdraw": ("amount", "confirm_live"),
    "bytes.bump": ("tid", "confirm_live"),
    "drafts.list": (),
    "drafts.read": (),
    "drafts.update": (),
    "drafts.delete": ("confirm_delete",),
}

_TOOL_SELECTOR_PROPERTY_OVERRIDES: dict[str, tuple[tuple[str, str], ...]] = {
    "contracts.read": (("cid", "selectors.contract"), ("uid", "selectors.contract")),
    "disputes.read": (("cdid", "selectors.dispute"), ("uid", "selectors.dispute")),
    "sigmarket.market.read": (("uid", "selectors.sigmarket"),),
    "sigmarket.order.read": (("oid", "selectors.sigmarket"), ("uid", "selectors.sigmarket")),
    "bytes.bump": (("tid", "selectors.thread"),),
}

_TOOL_SELECTOR_PROPERTY_REMOVALS: dict[str, tuple[str, ...]] = {
    "contracts.read": ("contract_id",),
    "disputes.read": ("dispute_id", "did"),
    "sigmarket.market.read": ("listing_id",),
    "sigmarket.order.read": ("listing_id",),
    "posts.reply": ("subject",),
    "bytes.transfer": ("note",),
    "bytes.deposit": ("target_uid", "note"),
    "bytes.withdraw": ("target_uid", "note"),
    "bytes.bump": ("target_uid", "amount", "note"),
}

_READ_OUTPUT_MODE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["readable", "structured", "raw"],
    "default": "readable",
}
_READ_INCLUDE_RAW_PAYLOAD_SCHEMA: dict[str, Any] = {
    "type": "boolean",
    "default": False,
}
_READ_BODY_FORMAT_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": ["raw", "clean", "markdown"],
    "default": "markdown",
    "description": "How BBCode/MyCode body fields should be exposed in structuredContent.",
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
    if spec.tool_name.startswith("drafts."):
        schema = _base_schema(spec)
    else:
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
    if spec.operation == "read" and policy.can_register(spec.tool_name) and spec.tool_name not in {
        "formatting.preflight",
        "drafts.list",
        "drafts.read",
    }:
        properties = schema.get("properties")
        if isinstance(properties, dict):
            updated_properties = dict(properties)
        else:
            updated_properties = {}
        updated_properties.setdefault("output_mode", dict(_READ_OUTPUT_MODE_SCHEMA))
        updated_properties.setdefault("include_raw_payload", dict(_READ_INCLUDE_RAW_PAYLOAD_SCHEMA))
        updated_properties.setdefault("body_format", dict(_READ_BODY_FORMAT_SCHEMA))
        schema["properties"] = updated_properties
    if spec.tool_name == "formatting.preflight":
        schema["anyOf"] = [{"required": ["message"]}, {"required": ["source_path"]}]
    elif spec.tool_name in {"drafts.read", "drafts.update", "drafts.delete"}:
        schema["anyOf"] = [{"required": ["draft_id"]}, {"required": ["draft_path"]}]
    elif "writes.content" in spec.parameter_families:
        schema["anyOf"] = [{"required": ["message"]}, {"required": ["draft_id"]}, {"required": ["draft_path"]}]
    return schema


def build_tool_output_schema(spec: ToolSpec) -> dict[str, object] | None:
    if spec.operation != "read":
        return None
    if spec.tool_name == "formatting.preflight":
        return {
            "type": "object",
            "additionalProperties": True,
            "x-hf-helper-path": spec.helper_path,
            "x-hf-formatting-engine": True,
        }
    return {
        "type": "object",
        "additionalProperties": True,
        "x-hf-helper-path": spec.helper_path,
        "x-hf-output-modes": ["readable", "structured", "raw"],
        "x-hf-body-formats": ["raw", "clean", "markdown"],
    }


__all__ = ["build_tool_output_schema", "build_tool_schema"]
