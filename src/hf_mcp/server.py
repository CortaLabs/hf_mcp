from __future__ import annotations

import inspect
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from .capabilities import CapabilityPolicy
from .config import HFMCPSettings, load_settings
from .dispatcher import register_tools, resolve_runtime_bundle

_RUNTIME_MODULE = "mcp.server.fastmcp"


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    name: str
    description: str
    input_schema: dict[str, object]
    annotations: dict[str, object]
    handler: Any


class HFServer:
    def __init__(self, name: str = "hf-mcp") -> None:
        self.name = name
        self.tools: dict[str, RegisteredTool] = {}

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, object],
        annotations: dict[str, object],
        handler: Any,
    ) -> None:
        self.tools[name] = RegisteredTool(
            name=name,
            description=description,
            input_schema=input_schema,
            annotations=annotations,
            handler=handler,
        )


class _FastMCPToolAdapter:
    def __init__(self, app: Any) -> None:
        self._app = app

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, object],
        annotations: dict[str, object],
        handler: Any,
    ) -> None:
        wrapped_handler = _with_schema_signature(handler, input_schema)
        fastmcp_annotations = _build_fastmcp_annotations(annotations)
        self._app.add_tool(
            wrapped_handler,
            name=name,
            description=description,
            annotations=fastmcp_annotations,
        )


def _schema_annotation(parameter_schema: object) -> object:
    if not isinstance(parameter_schema, dict):
        return object

    schema_type = parameter_schema.get("type")
    if isinstance(schema_type, list):
        non_null_types = [value for value in schema_type if value != "null"]
        schema_type = non_null_types[0] if non_null_types else None

    if schema_type is None:
        any_of = parameter_schema.get("anyOf")
        if isinstance(any_of, list):
            for candidate in any_of:
                if not isinstance(candidate, dict):
                    continue
                candidate_type = candidate.get("type")
                if candidate_type == "null":
                    continue
                schema_type = candidate_type
                break

    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[object]
    if schema_type == "object":
        return dict[str, object]
    return object


def _signature_from_schema(handler: Any, input_schema: dict[str, object]) -> inspect.Signature:
    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return inspect.Signature()

    required_values = input_schema.get("required")
    required = (
        {value for value in required_values if isinstance(value, str)}
        if isinstance(required_values, list)
        else set()
    )

    handler_parameters = inspect.signature(handler).parameters
    parameters: list[inspect.Parameter] = []
    for parameter_name, parameter_schema in properties.items():
        if not isinstance(parameter_name, str) or not parameter_name.isidentifier():
            raise ValueError(f"Unsupported parameter name in tool schema: {parameter_name!r}")

        default = inspect.Parameter.empty
        if parameter_name not in required:
            if isinstance(parameter_schema, dict) and "default" in parameter_schema:
                default = parameter_schema["default"]
            else:
                handler_parameter = handler_parameters.get(parameter_name)
                if handler_parameter is not None and handler_parameter.default is not inspect.Parameter.empty:
                    default = handler_parameter.default
                else:
                    default = None
        parameters.append(
            inspect.Parameter(
                name=parameter_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=_schema_annotation(parameter_schema),
            )
        )

    return inspect.Signature(parameters=parameters)


def _with_schema_signature(handler: Any, input_schema: dict[str, object]) -> Any:
    signature = _signature_from_schema(handler, input_schema)

    def _wrapped_handler(**kwargs: Any) -> Any:
        return handler(**kwargs)

    _wrapped_handler.__name__ = getattr(handler, "__name__", "tool_handler")
    _wrapped_handler.__doc__ = getattr(handler, "__doc__", "")
    _wrapped_handler.__module__ = getattr(handler, "__module__", __name__)
    _wrapped_handler.__signature__ = signature
    _wrapped_handler.__annotations__ = {
        parameter.name: parameter.annotation
        for parameter in signature.parameters.values()
        if parameter.annotation is not inspect.Parameter.empty
    }
    _wrapped_handler.__annotations__["return"] = object
    return _wrapped_handler


def _build_fastmcp_annotations(annotations: dict[str, object]) -> Any:
    module = import_module("mcp.types")
    tool_annotations_class = getattr(module, "ToolAnnotations")
    return tool_annotations_class(**annotations)


def _load_fastmcp_class() -> Any:
    try:
        module = import_module(_RUNTIME_MODULE)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing runtime dependency 'mcp'. Install required runtime dependencies "
            "for hf-mcp before launching the server."
        ) from exc

    fastmcp_class = getattr(module, "FastMCP", None)
    if fastmcp_class is None:
        raise RuntimeError(
            "Missing runtime dependency 'mcp'. Install required runtime dependencies "
            "for hf-mcp before launching the server."
        )
    return fastmcp_class


def create_server(settings: HFMCPSettings | None = None) -> Any:
    resolved_settings = settings if settings is not None else load_settings(config_path=None)
    policy = CapabilityPolicy(resolved_settings)
    runtime = resolve_runtime_bundle(resolved_settings)
    server = HFServer(name="hf-mcp")
    register_tools(server, policy, runtime)
    return server


def serve_stdio(settings: HFMCPSettings | None = None) -> None:
    resolved_settings = settings if settings is not None else load_settings(config_path=None)
    policy = CapabilityPolicy(resolved_settings)
    runtime = resolve_runtime_bundle(resolved_settings)
    fastmcp_class = _load_fastmcp_class()
    app = fastmcp_class(name="hf-mcp")
    register_tools(_FastMCPToolAdapter(app), policy, runtime)
    app.run(transport="stdio")


__all__ = ["HFServer", "RegisteredTool", "create_server", "serve_stdio"]
