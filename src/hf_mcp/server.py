from __future__ import annotations

import inspect
from copy import deepcopy
from dataclasses import dataclass
from importlib import import_module
from typing import Annotated, Any, cast
from urllib.parse import urljoin

from pydantic import ConfigDict, PrivateAttr, RootModel, ValidationError
from pydantic_core import InitErrorDetails

from . import __version__
from .capabilities import CapabilityPolicy
from .config import HFMCPSettings, load_settings
from .dispatcher import register_tools, resolve_runtime_bundle

_RUNTIME_MODULE = "mcp.server.mcpserver"


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


class _MCPServerToolAdapter:
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
        schema_copy, validator = _compile_input_schema(name, input_schema)
        tool_manager = _require_tool_manager(self._app)
        wrapped_handler = _with_schema_signature(
            name, handler, schema_copy, output_schema
        )
        fastmcp_annotations = _build_fastmcp_annotations(annotations)
        add_tool_kwargs: dict[str, object] = {
            "name": name,
            "description": description,
            "annotations": fastmcp_annotations,
        }
        if self._supports_output_schema:
            add_tool_kwargs["output_schema"] = output_schema
        # SDK2 protocol annotations contain standard hints only. HF extensions
        # belong to the supported tool-level metadata seam (wire: Tool._meta).
        if _supports_add_tool_keyword(self._app, "meta"):
            add_tool_kwargs["meta"] = annotations.get("_meta")
        self._app.add_tool(wrapped_handler, **add_tool_kwargs)
        try:
            tool = tool_manager.get_tool(name)
            if tool is None:
                raise RuntimeError(
                    "registered tool is unavailable through the SDK tool manager"
                )
            _install_original_schema_contract(
                tool,
                tool_name=name,
                input_schema=schema_copy,
                validator=validator,
                handler=handler,
            )
        except Exception as exc:
            tool_manager.remove_tool(name)
            if isinstance(
                exc, RuntimeError
            ) and "tool manager metadata capability" in str(exc):
                raise
            raise RuntimeError(
                f"MCP SDK tool manager metadata capability is incompatible for {name}"
            ) from exc


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


def _require_tool_manager(app: Any) -> Any:
    manager = getattr(app, "_tool_manager", None)
    if (
        manager is None
        or not callable(getattr(manager, "get_tool", None))
        or not callable(getattr(manager, "remove_tool", None))
    ):
        raise RuntimeError(
            "MCP SDK tool manager metadata capability is required for original-schema validation"
        )
    return manager


def _compile_input_schema(
    tool_name: str, input_schema: dict[str, object]
) -> tuple[dict[str, Any], Any]:
    if not isinstance(input_schema, dict):
        raise TypeError(f"Input schema for {tool_name} must be an object")
    schema_copy = deepcopy(input_schema)
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012

        Draft202012Validator.check_schema(schema_copy)
        resource = Resource.from_contents(
            schema_copy, default_specification=DRAFT202012
        )
        root_uri = resource.id() or ""
        # Registry has no retrieval callback by default, so only local resources are addressable.
        registry = Registry().with_resource(root_uri, resource).crawl()
        _require_local_schema_references(resource, registry, "")
        return schema_copy, Draft202012Validator(schema_copy, registry=registry)
    except Exception as exc:
        raise ValueError(
            f"Invalid Draft 2020-12 input schema for tool {tool_name}"
        ) from exc


def _require_local_schema_references(
    resource: Any, registry: Any, base_uri: str
) -> None:
    contents = resource.contents
    if not isinstance(contents, dict):
        return

    resource_id = resource.id()
    if resource_id is not None:
        base_uri = urljoin(base_uri, resource_id)

    for keyword in ("$ref", "$dynamicRef"):
        reference = contents.get(keyword)
        if reference is None:
            continue
        if not isinstance(reference, str) or not reference.startswith("#"):
            raise ValueError(f"input schema uses an unsupported nonlocal {keyword}")
        registry.resolver(base_uri=base_uri).lookup(reference)

    for subresource in resource.subresources():
        _require_local_schema_references(subresource, registry, base_uri)


def _install_original_schema_contract(
    tool: Any,
    *,
    tool_name: str,
    input_schema: dict[str, Any],
    validator: Any,
    handler: Any,
) -> None:
    parameters = getattr(tool, "parameters", None)
    metadata: Any = getattr(tool, "fn_metadata", None)
    if (
        not isinstance(parameters, dict)
        or not callable(getattr(metadata, "validate_arguments", None))
        or not all(
            hasattr(metadata, name)
            for name in ("arg_model", "output_schema", "output_model", "wrap_output")
        )
    ):
        raise RuntimeError("MCP SDK tool manager metadata capability is incompatible")

    published_schema = deepcopy(input_schema)
    if "title" not in published_schema:
        generated_title = parameters.get("title")
        published_schema["title"] = (
            generated_title
            if isinstance(generated_title, str) and generated_title
            else f"{_tool_handler_name(tool_name)}Arguments"
        )
    tool.parameters = published_schema

    properties = input_schema.get("properties")
    required = input_schema.get("required")
    required_names = (
        {name for name in required if isinstance(name, str)}
        if isinstance(required, list)
        else set()
    )
    handler_parameters = inspect.signature(handler).parameters
    defaults: dict[str, Any] = {}
    if isinstance(properties, dict):
        for name, property_schema in properties.items():
            handler_parameter = (
                handler_parameters.get(name) if isinstance(name, str) else None
            )
            if (
                isinstance(property_schema, dict)
                and name not in required_names
                and "default" in property_schema
                and handler_parameter is not None
                and handler_parameter.default is inspect.Parameter.empty
            ):
                defaults[name] = deepcopy(property_schema["default"])

    metadata_type = type(metadata)

    # The base class is the SDK's runtime-selected metadata type, so mypy cannot see it.
    class _OriginalSchemaFuncMetadata(metadata_type):  # type: ignore[valid-type,misc]
        _tool_name: str = PrivateAttr()
        _input_schema: dict[str, Any] = PrivateAttr()
        _input_validator: Any = PrivateAttr()
        _required_defaults: dict[str, Any] = PrivateAttr()

        def validate_arguments(
            self, arguments_to_validate: dict[str, Any]
        ) -> dict[str, Any]:
            if not isinstance(arguments_to_validate, dict):
                raise _argument_validation_error(self._tool_name, [((), "type")])
            failures = [
                (tuple(error.absolute_path), str(error.validator))
                for error in self._input_validator.iter_errors(arguments_to_validate)
            ]
            if failures:
                raise _argument_validation_error(self._tool_name, failures)

            validated = dict(arguments_to_validate)
            for name, default in self._required_defaults.items():
                if name in validated:
                    continue
                properties = self._input_schema.get("properties")
                property_schema = (
                    properties.get(name) if isinstance(properties, dict) else None
                )
                if not isinstance(property_schema, dict):
                    raise _argument_validation_error(
                        self._tool_name, [((name,), "default")]
                    )
                try:
                    default_errors = list(
                        self._input_validator.descend(
                            default,
                            property_schema,
                            path=name,
                            schema_path=("properties", name),
                        )
                    )
                except Exception as exc:
                    raise _argument_validation_error(
                        self._tool_name, [((name,), "default")]
                    ) from exc
                if default_errors:
                    raise _argument_validation_error(
                        self._tool_name,
                        [
                            ((name, *tuple(error.absolute_path)), str(error.validator))
                            for error in default_errors
                        ],
                    )
                validated[name] = deepcopy(default)
            return validated

    try:
        specialized_metadata = _OriginalSchemaFuncMetadata(
            arg_model=metadata.arg_model,
            output_schema=metadata.output_schema,
            output_model=metadata.output_model,
            wrap_output=metadata.wrap_output,
        )
        specialized_metadata._tool_name = tool_name
        specialized_metadata._input_schema = deepcopy(input_schema)
        specialized_metadata._input_validator = validator
        specialized_metadata._required_defaults = defaults
        tool.fn_metadata = specialized_metadata
    except Exception as exc:
        raise RuntimeError(
            "MCP SDK tool manager metadata capability is incompatible"
        ) from exc


def _argument_validation_error(
    tool_name: str,
    failures: list[tuple[tuple[int | str, ...], str]],
) -> ValidationError:
    constraint_messages = {
        "additionalProperties": "contains an unknown property",
        "anyOf": "does not satisfy any allowed alternative",
        "const": "does not match the required constant",
        "enum": "is not one of the allowed values",
        "items": "contains an item that violates its schema",
        "maximum": "exceeds the maximum constraint",
        "maxItems": "exceeds the maximum item count",
        "maxLength": "exceeds the maximum length",
        "minimum": "is below the minimum constraint",
        "minItems": "is below the minimum item count",
        "minLength": "is below the minimum length",
        "not": "matches a forbidden schema",
        "oneOf": "does not satisfy exactly one allowed alternative",
        "pattern": "does not match the required pattern",
        "required": "is missing a required property",
        "type": "does not match the declared JSON type",
        "default": "has a schema default that violates its property schema",
    }
    details: list[InitErrorDetails] = []
    for path, constraint in failures:
        path_text = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}" for part in path
        )
        message = f"{constraint}: {constraint_messages.get(constraint, 'violates its JSON Schema constraint')}"
        details.append(
            {
                "type": "value_error",
                "loc": path,
                "input": "<redacted>",
                "ctx": {
                    "error": ValueError(
                        f"tool {tool_name} argument {path_text} {message}"
                    )
                },
            }
        )
    return ValidationError.from_exception_data(f"{tool_name} arguments", details)


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
    if schema_type in {"integer", "number"}:
        return int if schema_type == "integer" else float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        return list[object]
    if schema_type == "object":
        return dict[str, object]
    return object


def _signature_from_schema(
    handler: Any, input_schema: dict[str, object]
) -> inspect.Signature:
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
            raise ValueError(
                f"Unsupported parameter name in tool schema: {parameter_name!r}"
            )

        default: Any = inspect.Parameter.empty
        if parameter_name not in required:
            handler_parameter = handler_parameters.get(parameter_name)
            if (
                handler_parameter is not None
                and handler_parameter.default is not inspect.Parameter.empty
            ):
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


def _tool_handler_name(tool_name: str) -> str:
    return f"{tool_name.replace('.', '_').replace('-', '_')}_handler"


def _with_schema_signature(
    tool_name: str,
    handler: Any,
    input_schema: dict[str, object],
    output_schema: dict[str, object] | None = None,
) -> Any:
    signature = _signature_from_schema(handler, input_schema)
    if output_schema is not None:
        # MCPServer supports Annotated[CallToolResult, OutputModel]. Keep the
        # existing open object contract without compiling a parallel schema.
        class _StructuredOutput(RootModel[dict[str, Any]]):
            model_config = ConfigDict(json_schema_extra=cast(Any, output_schema))

        module = import_module("mcp.types")
        result_type = getattr(module, "CallToolResult")
        signature = signature.replace(
            return_annotation=Annotated[result_type, _StructuredOutput]
        )

    if inspect.iscoroutinefunction(handler):

        async def _wrapped_handler(**kwargs: Any) -> Any:
            return _normalize_handler_result(await handler(**kwargs))
    else:
        # Sync/async variants intentionally differ in return type.
        def _wrapped_handler(**kwargs: Any) -> Any:  # type: ignore[misc]
            return _normalize_handler_result(handler(**kwargs))

    handler_name = _tool_handler_name(tool_name)
    _wrapped_handler.__name__ = handler_name
    _wrapped_handler.__qualname__ = handler_name
    _wrapped_handler.__doc__ = getattr(handler, "__doc__", "")
    _wrapped_handler.__module__ = getattr(handler, "__module__", __name__)
    setattr(_wrapped_handler, "__signature__", signature)
    _wrapped_handler.__annotations__ = {
        parameter.name: parameter.annotation
        for parameter in signature.parameters.values()
        if parameter.annotation is not inspect.Parameter.empty
    }
    _wrapped_handler.__annotations__["return"] = signature.return_annotation
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


def _load_mcpserver_class() -> Any:
    try:
        module = import_module(_RUNTIME_MODULE)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing runtime dependency 'mcp'. Install required runtime dependencies "
            "for hf-mcp before launching the server."
        ) from exc

    fastmcp_class = getattr(module, "MCPServer", None)
    if fastmcp_class is None:
        raise RuntimeError(
            "Missing runtime dependency 'mcp'. Install required runtime dependencies "
            "for hf-mcp before launching the server."
        )
    return fastmcp_class


def create_server(settings: HFMCPSettings | None = None) -> Any:
    resolved_settings = (
        settings if settings is not None else load_settings(config_path=None)
    )
    policy = CapabilityPolicy(resolved_settings)
    runtime = resolve_runtime_bundle(resolved_settings)
    server = HFServer(name="hf-mcp")
    register_tools(server, policy, runtime)
    return server


def serve_stdio(settings: HFMCPSettings | None = None) -> None:
    resolved_settings = (
        settings if settings is not None else load_settings(config_path=None)
    )
    policy = CapabilityPolicy(resolved_settings)
    runtime = resolve_runtime_bundle(resolved_settings)
    fastmcp_class = _load_mcpserver_class()
    app = fastmcp_class(name="hf-mcp", version=__version__)
    register_tools(_MCPServerToolAdapter(app), policy, runtime)
    app.run(transport="stdio")


__all__ = ["HFServer", "RegisteredTool", "create_server", "serve_stdio"]
