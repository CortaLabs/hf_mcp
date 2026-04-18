from __future__ import annotations

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
        del input_schema
        del annotations
        self._app.add_tool(
            handler,
            name=name,
            description=description,
        )


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
