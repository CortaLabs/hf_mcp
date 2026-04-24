from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from .annotations import build_annotations
from .capabilities import CapabilityPolicy
from .config import DEFAULT_DRAFT_DIR, HFMCPSettings
from .metadata import get_tool_specs
from .registry import get_documented_write_specs, mcp_tool_name
from .schemas import build_tool_output_schema, build_tool_schema
from .token_store import load_token_store
from .tools.drafts import build_draft_handlers
from .tools.formatting import build_formatting_handlers
from .tools.read_core import build_core_read_handlers
from .tools.read_extended import build_extended_read_handlers
from .tools.write_documented import build_write_handlers
from .transport import HFTransport


@dataclass(frozen=True, slots=True)
class RuntimeBundle:
    transport: object | None = None
    auth_context: object | None = None
    settings: HFMCPSettings | None = None


def resolve_runtime_bundle(settings: HFMCPSettings) -> RuntimeBundle:
    _require_runtime_secrets(settings)
    store = load_token_store(settings)
    bundle = store.require_bundle()
    transport = HFTransport(token_store=store)
    return RuntimeBundle(transport=transport, auth_context=bundle, settings=settings)


def _require_runtime_secrets(settings: HFMCPSettings) -> None:
    for env_name in ("HF_MCP_CLIENT_ID", "HF_MCP_CLIENT_SECRET"):
        value = settings.runtime_env.get(env_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing required environment variable: {env_name}")


def _tool_description(tool_name: str, operation: str) -> str:
    locality = "local" if tool_name == "formatting.preflight" or tool_name.startswith("drafts.") else "remote"
    return f"Hack Forums {locality} {operation} tool for {tool_name}."


def _build_unimplemented_handler(tool_name: str) -> Any:
    def _handler(**kwargs: object) -> object:
        del kwargs
        raise NotImplementedError(
            f"Tool '{tool_name}' is registered from the coverage registry but its handler is not implemented yet."
        )

    return _handler


def _shape_live_input_schema(tool_name: str, input_schema: dict[str, object], handler: Any) -> dict[str, object]:
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return input_schema

    schema = dict(input_schema)
    shaped_properties: dict[str, object] = {}
    handler_parameters = inspect.signature(handler).parameters
    for parameter_name, parameter_schema in properties.items():
        if tool_name == "me.read" and parameter_name == "uid":
            continue

        if not isinstance(parameter_schema, dict):
            shaped_properties[parameter_name] = parameter_schema
            continue

        shaped_schema = dict(parameter_schema)
        handler_parameter = handler_parameters.get(parameter_name)
        if "default" not in shaped_schema and handler_parameter is not None:
            default = handler_parameter.default
            if default is not inspect.Parameter.empty and default is not None:
                shaped_schema["default"] = default
        shaped_properties[parameter_name] = shaped_schema

    schema["properties"] = shaped_properties
    required_values = schema.get("required")
    if isinstance(required_values, list):
        required = [value for value in required_values if isinstance(value, str) and value in shaped_properties]
        if required:
            schema["required"] = required
        else:
            schema.pop("required", None)
    return schema


def _register_via_register_tool(
    server: Any,
    *,
    name: str,
    description: str,
    input_schema: dict[str, object],
    annotations: dict[str, object],
    output_schema: dict[str, object] | None,
    handler: Any,
) -> bool:
    register_tool = getattr(server, "register_tool", None)
    if not callable(register_tool):
        return False

    register_tool(
        name=name,
        description=description,
        input_schema=input_schema,
        annotations=annotations,
        output_schema=output_schema,
        handler=handler,
    )
    return True


def register_tools(server: Any, policy: CapabilityPolicy, runtime: RuntimeBundle) -> None:
    draft_dir = runtime.settings.draft_dir if runtime.settings is not None else DEFAULT_DRAFT_DIR
    concrete_handlers: dict[str, Any] = build_formatting_handlers(draft_dir=draft_dir)
    concrete_handlers.update(build_draft_handlers(draft_dir=draft_dir))
    transport = runtime.transport

    if isinstance(transport, HFTransport):
        concrete_handlers.update(build_core_read_handlers(policy, transport))
        concrete_handlers.update(build_extended_read_handlers(policy, transport))
        concrete_handlers.update(build_write_handlers(policy, transport, draft_dir=draft_dir))

    specs = list(get_tool_specs(policy))
    known_names = {spec.tool_name for spec in specs}
    enabled_capabilities = frozenset(
        getattr(getattr(policy, "_settings", None), "enabled_capabilities", frozenset())
    )
    for spec in get_documented_write_specs():
        if spec.tool_name in known_names:
            continue
        if spec.tool_name in enabled_capabilities:
            specs.append(spec)
            known_names.add(spec.tool_name)

    for spec in specs:
        handler = concrete_handlers.get(spec.tool_name, _build_unimplemented_handler(spec.tool_name))
        schema = _shape_live_input_schema(spec.tool_name, build_tool_schema(spec, policy), handler)
        output_schema = build_tool_output_schema(spec)
        annotations = build_annotations(spec)
        registered = _register_via_register_tool(
            server,
            name=mcp_tool_name(spec.tool_name),
            description=_tool_description(spec.tool_name, spec.operation),
            input_schema=schema,
            annotations=annotations,
            output_schema=output_schema,
            handler=handler,
        )
        if not registered:
            raise TypeError("Server does not expose a compatible register_tool(name=..., ...) API.")


__all__ = ["RuntimeBundle", "register_tools", "resolve_runtime_bundle"]
