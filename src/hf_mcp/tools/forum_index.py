from __future__ import annotations

import json
from typing import Any

from hf_mcp.flow import attach_hf_flow, build_hf_flow
from hf_mcp.forum_catalog import build_forum_index_payload, load_forum_catalog
from hf_mcp.mycode import coerce_body_format

_VALID_OUTPUT_MODES: frozenset[str] = frozenset({"readable", "structured", "raw"})


def _coerce_output_mode(raw_value: str | None) -> str:
    if raw_value is None:
        return "readable"
    if not isinstance(raw_value, str):
        raise ValueError("`output_mode` must be a string.")
    mode = raw_value.strip()
    if mode not in _VALID_OUTPUT_MODES:
        valid = ", ".join(sorted(_VALID_OUTPUT_MODES))
        raise ValueError(f"Unknown read output mode '{mode}'. Valid modes: {valid}.")
    return mode


def _coerce_bool(raw_value: bool | None, *, field_name: str, default: bool) -> bool:
    if raw_value is None:
        return default
    if not isinstance(raw_value, bool):
        raise ValueError(f"`{field_name}` must be a boolean.")
    return raw_value


def _iter_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for node in nodes:
        flattened.append(node)
        children = node.get("children")
        if isinstance(children, list):
            child_entries = [entry for entry in children if isinstance(entry, dict)]
            flattened.extend(_iter_nodes(child_entries))
    return flattened


def _build_summary(*, nodes: list[dict[str, Any]], view: str, include_inactive: bool) -> str:
    flattened_nodes = _iter_nodes(nodes)
    categories = sum(1 for node in flattened_nodes if bool(node.get("is_category")))
    forums = sum(1 for node in flattened_nodes if not bool(node.get("is_category")))
    return (
        "forums.index loaded "
        f"{len(flattened_nodes)} node(s) in {view} view "
        f"(forums={forums}, categories={categories}, include_inactive={include_inactive})."
    )


def build_forum_index_handlers() -> dict[str, Any]:
    def _forums_index_handler(
        *,
        view: str | None = "flat",
        include_inactive: bool | None = False,
        output_mode: str | None = None,
        include_raw_payload: bool | None = None,
        body_format: str | None = None,
    ) -> dict[str, Any]:
        resolved_view = "flat" if view is None else view
        resolved_include_inactive = _coerce_bool(
            include_inactive,
            field_name="include_inactive",
            default=False,
        )
        resolved_mode = _coerce_output_mode(output_mode)
        resolved_include_raw_payload = _coerce_bool(
            include_raw_payload,
            field_name="include_raw_payload",
            default=False,
        )
        if body_format is not None:
            coerce_body_format(body_format, field_name="body_format")

        payload = build_forum_index_payload(
            view=resolved_view,
            include_inactive=resolved_include_inactive,
        )
        catalog_payload = load_forum_catalog()
        structured_content: dict[str, Any] = dict(payload)
        for key in ("catalog_version", "source"):
            value = catalog_payload.get(key)
            if value is not None:
                structured_content[key] = value
        flow = build_hf_flow(
            tool_name="forums.index",
            normalized_payload=structured_content,
            arguments={
                "view": resolved_view,
                "include_inactive": resolved_include_inactive,
            },
            source="forum_catalog",
        )
        structured_content = attach_hf_flow(structured_content, flow)

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": _build_summary(
                    nodes=payload["nodes"],
                    view=resolved_view,
                    include_inactive=resolved_include_inactive,
                ),
            }
        ]
        if resolved_mode == "raw" or resolved_include_raw_payload:
            content.append(
                {
                    "type": "resource",
                    "resource": {
                        "uri": "hf-mcp://catalog/forums.index",
                        "mimeType": "application/json",
                        "text": json.dumps(catalog_payload, ensure_ascii=False),
                    },
                }
            )
        return {
            "content": content,
            "structuredContent": structured_content,
        }

    return {"forums.index": _forums_index_handler}


__all__ = ["build_forum_index_handlers"]
