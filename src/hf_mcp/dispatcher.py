from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .annotations import build_annotations
from .capabilities import CapabilityPolicy
from .config import HFMCPSettings
from .metadata import get_tool_specs
from .registry import get_documented_write_specs
from .schemas import build_tool_schema
from .token_store import load_token_store
from .tools.read_core import build_core_read_handlers
from .tools.read_extended import build_extended_read_handlers
from .tools.write_documented import build_write_handlers
from .transport import HFTransport


@dataclass(frozen=True, slots=True)
class RuntimeBundle:
    transport: object | None = None
    auth_context: object | None = None


def resolve_runtime_bundle(settings: HFMCPSettings) -> RuntimeBundle:
    _require_runtime_secrets(settings)
    store = load_token_store(settings)
    bundle = store.require_bundle()
    transport = HFTransport(token_store=store)
    return RuntimeBundle(transport=transport, auth_context=bundle)


def _require_runtime_secrets(settings: HFMCPSettings) -> None:
    for env_name in ("HF_MCP_CLIENT_ID", "HF_MCP_CLIENT_SECRET"):
        value = settings.runtime_env.get(env_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing required environment variable: {env_name}")


def _tool_description(tool_name: str, operation: str) -> str:
    return f"Hack Forums remote {operation} tool for {tool_name}."


def _build_unimplemented_handler(tool_name: str) -> Any:
    def _handler(**kwargs: object) -> object:
        del kwargs
        raise NotImplementedError(
            f"Tool '{tool_name}' is registered from the coverage registry but its handler is not implemented yet."
        )

    return _handler


def _register_via_register_tool(
    server: Any,
    *,
    name: str,
    description: str,
    input_schema: dict[str, object],
    annotations: dict[str, object],
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
        handler=handler,
    )
    return True


def register_tools(server: Any, policy: CapabilityPolicy, runtime: RuntimeBundle) -> None:
    concrete_handlers: dict[str, Any] = {}
    transport = runtime.transport

    if isinstance(transport, HFTransport):
        concrete_handlers.update(build_core_read_handlers(policy, transport))
        concrete_handlers.update(build_extended_read_handlers(policy, transport))
        concrete_handlers.update(build_write_handlers(policy, transport))

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
        schema = build_tool_schema(spec, policy)
        annotations = build_annotations(spec)
        registered = _register_via_register_tool(
            server,
            name=spec.tool_name,
            description=_tool_description(spec.tool_name, spec.operation),
            input_schema=schema,
            annotations=annotations,
            handler=handler,
        )
        if not registered:
            raise TypeError("Server does not expose a compatible register_tool(name=..., ...) API.")


__all__ = ["RuntimeBundle", "register_tools", "resolve_runtime_bundle"]
