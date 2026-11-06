from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .capabilities import CapabilityPolicy
from .config import DEFAULT_DRAFT_DIR, HFMCPSettings
from .registry import TOOLS
from .token_store import load_token_store
from .tools.drafts import build_draft_handlers
from .tools.forum_index import build_forum_index_handlers
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


def register_tools(
    server: Any, policy: CapabilityPolicy, runtime: RuntimeBundle
) -> None:
    draft_dir = (
        runtime.settings.draft_dir
        if runtime.settings is not None
        else DEFAULT_DRAFT_DIR
    )
    concrete_handlers: dict[str, Any] = build_formatting_handlers(draft_dir=draft_dir)
    concrete_handlers.update(build_draft_handlers(draft_dir=draft_dir))
    concrete_handlers.update(build_forum_index_handlers())
    transport = runtime.transport

    if isinstance(transport, HFTransport):
        concrete_handlers.update(build_core_read_handlers(policy, transport))
        concrete_handlers.update(build_extended_read_handlers(policy, transport))
        concrete_handlers.update(
            build_write_handlers(policy, transport, draft_dir=draft_dir)
        )

    for spec in TOOLS:
        handler = concrete_handlers.get(spec.name)
        if handler is None or not policy.can_register(spec.name):
            continue
        output_schema = deepcopy(spec.output_schema)
        registered = _register_via_register_tool(
            server,
            name=spec.mcp_name,
            description=spec.description,
            input_schema=policy.input_schema(spec),
            annotations=spec.annotations,
            output_schema=output_schema,
            handler=handler,
        )
        if not registered:
            raise TypeError(
                "Server does not expose a compatible register_tool(name=..., ...) API."
            )


__all__ = ["RuntimeBundle", "register_tools", "resolve_runtime_bundle"]
