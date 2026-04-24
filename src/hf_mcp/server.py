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
    output_schema: dict[str, object] | None = None


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
        output_schema: dict[str, object] | None = None,
    ) -> None:
        self.tools[name] = RegisteredTool(
            name=name,
            description=description,
            input_schema=input_schema,
            annotations=annotations,
            handler=handler,
            output_schema=output_schema,
        )


class _FastMCPToolAdapter:
    def __init__(self, app: Any) -> None:
        self._app = app
        self._supports_output_schema = _supports_add_tool_keyword(app, "output_schema")

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, object],
        annotations: dict[str, object],
        handler: Any,
        output_schema: dict[str, object] | None = None,
    ) -> None:
        wrapped_handler = _with_schema_signature(handler, input_schema)
        fastmcp_annotations = _build_fastmcp_annotations(annotations)
        add_tool_kwargs: dict[str, object] = {
            "name": name,
            "description": description,
            "annotations": fastmcp_annotations,
        }
        if self._supports_output_schema:
            add_tool_kwargs["output_schema"] = output_schema
        self._app.add_tool(
            wrapped_handler,
            **add_tool_kwargs,
        )


def _supports_add_tool_keyword(app: Any, keyword: str) -> bool:
    add_tool = getattr(app, "add_tool", None)
    if not callable(add_tool):
        return False
    try:
        signature = inspect.signature(add_tool)
    except (TypeError, ValueError):
        return False
    if keyword in signature.parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
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
            handler_parameter = handler_parameters.get(parameter_name)
            if handler_parameter is not None and handler_parameter.default is not inspect.Parameter.empty:
                default = handler_parameter.default
            elif isinstance(parameter_schema, dict) and "default" in parameter_schema:
                default = parameter_schema["default"]
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
        return _normalize_handler_result(handler(**kwargs))

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


def _normalize_handler_result(result: Any) -> Any:
    if not _is_hf_envelope(result):
        return result
    return _build_call_tool_result(result)


def _is_hf_envelope(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    content = result.get("content")
    structured_content = result.get("structuredContent")
    if not isinstance(content, list):
        return False
    return isinstance(structured_content, dict)


def _build_call_tool_result(result: dict[str, Any]) -> Any:
    module = import_module("mcp.types")
    call_tool_result_class = getattr(module, "CallToolResult")
    return call_tool_result_class(
        content=_normalize_content_parts(module, result.get("content", [])),
        structuredContent=result.get("structuredContent"),
        isError=bool(result.get("isError", False)),
    )


def _normalize_content_parts(module: Any, parts: list[Any]) -> list[Any]:
    text_content_class = getattr(module, "TextContent")
    embedded_resource_class = getattr(module, "EmbeddedResource")
    text_resource_class = getattr(module, "TextResourceContents")
    blob_resource_class = getattr(module, "BlobResourceContents")

    normalized_parts: list[Any] = []
    for part in parts:
        if not isinstance(part, dict):
            normalized_parts.append(part)
            continue

        part_type = part.get("type")
        if part_type == "text" and isinstance(part.get("text"), str):
            normalized_parts.append(text_content_class(type="text", text=part["text"]))
            continue

        if part_type == "resource":
            resource = part.get("resource")
            if not isinstance(resource, dict):
                normalized_parts.append(part)
                continue
            uri = resource.get("uri")
            if not isinstance(uri, str):
                normalized_parts.append(part)
                continue
            mime_type = resource.get("mimeType")
            if mime_type is not None and not isinstance(mime_type, str):
                mime_type = None

            if isinstance(resource.get("text"), str):
                normalized_parts.append(
                    embedded_resource_class(
                        type="resource",
                        resource=text_resource_class(
                            uri=uri,
                            mimeType=mime_type,
                            text=resource["text"],
                        ),
                    )
                )
                continue

            if isinstance(resource.get("blob"), str):
                normalized_parts.append(
                    embedded_resource_class(
                        type="resource",
                        resource=blob_resource_class(
                            uri=uri,
                            mimeType=mime_type,
                            blob=resource["blob"],
                        ),
                    )
                )
                continue

        normalized_parts.append(part)

    return normalized_parts


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
