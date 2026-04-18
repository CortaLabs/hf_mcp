from __future__ import annotations

from .metadata import build_tool_meta
from .registry import ToolSpec


def build_annotations(spec: ToolSpec) -> dict[str, object]:
    is_read = spec.operation == "read"
    return {
        "readOnlyHint": is_read,
        "destructiveHint": not is_read,
        "idempotentHint": is_read,
        "openWorldHint": True,
        "_meta": build_tool_meta(spec),
    }


__all__ = ["build_annotations"]
