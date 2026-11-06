from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .capabilities import CapabilityPolicy
from .config import HFMCPSettings
from .registry import TOOLS
from .token_store import load_token_store
from .tools.drafts import build_draft_handlers
from .tools.forum_index import build_forum_index_handlers
from .tools.formatting import build_formatting_handlers
from .tools.read_core import build_core_read_handlers
from .tools.read_extended import build_extended_read_handlers
from .tools.write_documented import build_write_handlers
from .transport import HFTransport

Handler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


def resolve_transport(settings: HFMCPSettings) -> HFTransport:
    """Return the transport for ``settings``; fail closed without credentials."""
    _require_runtime_secrets(settings)
    store = load_token_store(settings)
    store.require_bundle()
    return HFTransport(token_store=store)


def _require_runtime_secrets(settings: HFMCPSettings) -> None:
    for env_name in ("HF_MCP_CLIENT_ID", "HF_MCP_CLIENT_SECRET"):
        value = settings.runtime_env.get(env_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing required environment variable: {env_name}")


def build_handlers(
    policy: CapabilityPolicy,
    settings: HFMCPSettings,
    transport: HFTransport | None,
) -> dict[str, Handler]:
    """Return the handler of every registered tool, keyed by canonical tool name.

    Local tools need no transport; remote rows are present only when one is given.
    """
    draft_dir = settings.draft_dir
    available: dict[str, Handler] = {}
    available.update(
        build_formatting_handlers(
            draft_dir=draft_dir, templates_dir=settings.templates_dir
        )
    )
    available.update(build_draft_handlers(draft_dir=draft_dir))
    available.update(build_forum_index_handlers())
    if transport is not None:
        available.update(build_core_read_handlers(policy, transport))
        available.update(build_extended_read_handlers(policy, transport))
        available.update(build_write_handlers(policy, transport, draft_dir=draft_dir))
    return {
        spec.name: available[spec.name]
        for spec in TOOLS
        if spec.name in available and policy.can_register(spec.name)
    }


__all__ = ["Handler", "build_handlers", "resolve_transport"]
