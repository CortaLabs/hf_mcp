from __future__ import annotations

from .metadata import build_tool_meta
from .registry import ToolSpec


def build_annotations(spec: ToolSpec) -> dict[str, object]:
    is_local_tool = spec.locality == "local"
    is_read = spec.operation == "read"
    is_read_only = is_read and spec.tool_name != "formatting.preflight"
    is_destructive = spec.tool_name == "drafts.delete" or (
        not is_local_tool and not is_read
    )
    return {
        "readOnlyHint": is_read_only,
        "destructiveHint": is_destructive,
        "idempotentHint": is_read_only,
        "openWorldHint": not is_local_tool,
        "_meta": build_tool_meta(spec),
    }


__all__ = ["build_annotations"]
