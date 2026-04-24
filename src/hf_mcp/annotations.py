from __future__ import annotations

from .metadata import build_tool_meta
from .registry import ToolSpec


def build_annotations(spec: ToolSpec) -> dict[str, object]:
    is_local_tool = spec.tool_name == "formatting.preflight" or spec.tool_name.startswith("drafts.")
    is_read = spec.operation == "read"
    is_read_only = spec.tool_name in {"drafts.list", "drafts.read"} or (is_read and not is_local_tool)
    is_destructive = spec.tool_name == "drafts.delete" or (not is_local_tool and not is_read)
    return {
        "readOnlyHint": is_read_only,
        "destructiveHint": is_destructive,
        "idempotentHint": is_read_only,
        "openWorldHint": not is_local_tool,
        "_meta": build_tool_meta(spec),
    }


__all__ = ["build_annotations"]
