from __future__ import annotations

import inspect
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import anyio
import anyio.to_thread
import mcp.types as types
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from . import __version__
from .capabilities import CapabilityPolicy
from .config import HFMCPSettings, load_settings
from .dispatcher import Handler, build_handlers, resolve_transport
from .flow import prune_flow_actions
from .registry import TOOLS
from .transport import HFAPIError, build_error
from .write_preflight import WritePreflightError


@dataclass(frozen=True, slots=True)
class _Entry:
    canonical_name: str
    tool: types.Tool
    validator: Draft202012Validator
    handler: Handler


_PARAMETER_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")


def _path_text(path: tuple[str | int, ...]) -> str:
    """Render a path of schema-declared names and indices (never caller text)."""
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else part)
    return text or "(arguments)"


def _failing_paths(error: ValidationError) -> list[str]:
    """Name the failing parameter paths of one schema error, never the values.

    jsonschema reports ``required`` and ``additionalProperties`` failures at the
    parent path, so those name the missing or unexpected property instead. An
    unexpected name is echoed only when it looks like a parameter name (so a
    caller typo is visible); any other caller text is masked.
    """
    parent = tuple(error.absolute_path)
    if error.validator == "required" and isinstance(error.validator_value, list):
        instance = error.instance if isinstance(error.instance, Mapping) else {}
        return [
            _path_text((*parent, name))
            for name in error.validator_value
            if name not in instance
        ]
    if error.validator == "additionalProperties" and isinstance(
        error.instance, Mapping
    ):
        declared = error.schema.get("properties", {})
        return [
            _path_text((*parent, name))
            if not parent and _PARAMETER_NAME.fullmatch(str(name))
            else "(unknown parameter)"
            for name in sorted(error.instance, key=str)
            if name not in declared
        ]
    if error.validator == "anyOf" and not parent:
        names = sorted(
            {n for b in error.validator_value for n in b.get("required", ())}
        )
        return [f"one of {', '.join(names)}" if names else "(arguments)"]
    return [_path_text(parent)]


def _invalid_arguments_message(entry: _Entry, arguments: Any) -> str:
    paths = sorted(
        {
            path
            for error in entry.validator.iter_errors(arguments)
            for path in _failing_paths(error)
        }
    )
    shown = paths[:5]
    extra = len(paths) - len(shown)
    return (
        "Invalid arguments: "
        + ", ".join(shown)
        + (f" and {extra} more" if extra else "")
    )


def _error_result(
    code: str, tool: str | None = None, message: str | None = None
) -> types.CallToolResult:
    """One local ErrorV1 error result; ``message`` is a package-authored sentence."""
    return _error_v1_result(
        build_error(code, operation="local", tool=tool, message=message)
    )


def _error_v1_result(error_v1: dict[str, object]) -> types.CallToolResult:
    text = f"{error_v1['code']}: {error_v1['message']}"
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content={"error": error_v1},
        is_error=True,
    )


def _error_call_tool_result(tool: str, error: Exception) -> types.CallToolResult:
    if isinstance(error, HFAPIError):
        return _error_v1_result({**error.error, "tool": tool})
    if isinstance(error, WritePreflightError):
        return _error_result("FORMAT_NOT_READY", tool, str(error))
    # Only plain ValueError and errno-less PermissionError carry package sentences.
    if type(error) is ValueError or (
        type(error) is PermissionError and error.errno is None
    ):
        return _error_result("INVALID_ARGUMENT", tool, str(error))
    if isinstance(error, (ValueError, TypeError, PermissionError)):
        # Stdlib or OS text (paths, decoder positions): fixed sentence only.
        return _error_result("INVALID_ARGUMENT", tool)
    return _error_result("INTERNAL_ERROR", tool)


def build_server(policy: CapabilityPolicy, handlers: Mapping[str, Handler]) -> Server:
    """Serve the registered ``handlers`` through the SDK's lowlevel ``Server``."""
    entries: dict[str, _Entry] = {}
    for spec in TOOLS:
        handler = handlers.get(spec.name)
        if handler is None:
            continue
        tool = types.Tool(
            name=spec.mcp_name,
            description=spec.description,
            input_schema=policy.input_schema(spec),
            output_schema=spec.output_schema,
            annotations=types.ToolAnnotations(
                read_only_hint=spec.read_only,
                destructive_hint=spec.destructive,
                idempotent_hint=spec.idempotent,
                open_world_hint=spec.open_world,
            ),
        )
        # The validator compiles the very schema object the Tool publishes.
        Draft202012Validator.check_schema(tool.input_schema)
        entries[spec.mcp_name] = _Entry(
            spec.name,
            tool,
            Draft202012Validator(tool.input_schema),
            handler,
        )
    enabled_tools = frozenset(entry.canonical_name for entry in entries.values())

    async def list_tools(
        ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[entry.tool for entry in entries.values()])

    async def call_tool(
        ctx: ServerRequestContext[Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        entry = entries.get(params.name)
        if entry is None:
            return _error_result("INVALID_ARGUMENT", message="Unknown tool.")
        arguments = params.arguments if params.arguments is not None else {}
        if not entry.validator.is_valid(arguments):
            message = _invalid_arguments_message(entry, arguments)
            return _error_result("INVALID_ARGUMENT", params.name, message)
        try:
            envelope = await anyio.to_thread.run_sync(
                partial(entry.handler, **arguments)
            )
            if inspect.isawaitable(envelope):
                envelope = await envelope
        except Exception as error:
            return _error_call_tool_result(params.name, error)
        try:
            result = types.CallToolResult.model_validate(envelope)
        except Exception:
            # A handler broke the envelope contract: report it without detail.
            return _error_result("INTERNAL_ERROR", params.name)
        if result.structured_content is not None:
            result.structured_content = prune_flow_actions(
                result.structured_content, enabled_tools
            )
        return result

    return Server(
        "hf-mcp", version=__version__, on_list_tools=list_tools, on_call_tool=call_tool
    )


def create_server(settings: HFMCPSettings | None = None) -> Server:
    resolved = settings if settings is not None else load_settings(config_path=None)
    policy = CapabilityPolicy(resolved)
    transport = resolve_transport(resolved)
    return build_server(policy, build_handlers(policy, resolved, transport))


def serve_stdio(settings: HFMCPSettings | None = None) -> None:
    server = create_server(settings)

    async def _serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    anyio.run(_serve)


__all__ = ["build_server", "create_server", "serve_stdio"]
