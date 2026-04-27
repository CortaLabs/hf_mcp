from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.dispatcher import RuntimeBundle, register_tools
from hf_mcp.registry import mcp_tool_name
from hf_mcp.tools.forum_index import build_forum_index_handlers


class _CaptureServer:
    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}

    def register_tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        annotations: dict[str, Any],
        handler: Any,
        output_schema: dict[str, object] | None = None,
    ) -> None:
        self.tools[name] = {
            "description": description,
            "input_schema": input_schema,
            "annotations": annotations,
            "handler": handler,
            "output_schema": output_schema,
        }


def _policy() -> CapabilityPolicy:
    return CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset({"forums.read"}),
            enabled_parameter_families=frozenset({"selectors.forum", "filters.pagination"}),
        )
    )


def _extract_action_fids(next_actions: list[dict[str, Any]]) -> set[int]:
    fids: set[int] = set()
    for action in next_actions:
        arguments = action.get("arguments")
        if not isinstance(arguments, dict):
            continue
        fid = arguments.get("fid")
        if isinstance(fid, int):
            fids.add(fid)
    return fids


def test_forums_index_handler_supports_no_selector_invocation() -> None:
    handlers = build_forum_index_handlers()
    result = handlers["forums.index"]()

    assert isinstance(result, dict)
    assert isinstance(result.get("content"), list)
    assert isinstance(result.get("structuredContent"), dict)
    assert result["structuredContent"]["view"] == "flat"
    assert result["structuredContent"]["include_inactive"] is False


def test_forums_index_handler_supports_flat_and_tree_views() -> None:
    handler = build_forum_index_handlers()["forums.index"]
    flat_result = handler(view="flat")
    tree_result = handler(view="tree")

    flat_nodes = flat_result["structuredContent"]["nodes"]
    tree_nodes = tree_result["structuredContent"]["nodes"]
    assert isinstance(flat_nodes, list)
    assert isinstance(tree_nodes, list)
    assert flat_result["structuredContent"]["view"] == "flat"
    assert tree_result["structuredContent"]["view"] == "tree"
    assert all("children" not in node for node in flat_nodes)
    assert all("children" in node for node in tree_nodes)


def test_forums_index_registers_without_transport_and_keeps_structured_content_protocol() -> None:
    policy = _policy()
    server = _CaptureServer()

    register_tools(server, policy, RuntimeBundle())

    assert mcp_tool_name("forums.index") in server.tools
    assert mcp_tool_name("forums.read") not in server.tools
    handler = server.tools[mcp_tool_name("forums.index")]["handler"]
    result = handler()
    assert isinstance(result.get("structuredContent"), dict)
    assert "_hf_flow" in result["structuredContent"]


def test_forums_index_hf_flow_targets_forums_read_only_for_real_forums() -> None:
    handler = build_forum_index_handlers()["forums.index"]
    flat_result = handler()
    tree_result = handler(view="tree")
    flow = flat_result["structuredContent"]["_hf_flow"]
    tree_flow = tree_result["structuredContent"]["_hf_flow"]

    assert flow["version"] == 1
    assert flow["entry_tool"] == "forums.index"
    assert flow["breadcrumbs"] == ["forum_catalog", "forums.index"]
    assert 375 in flow["entities"]["forum_ids"]
    assert 261 in flow["entities"]["forum_ids"]
    next_actions = flow["next_actions"]
    assert isinstance(next_actions, list)
    assert next_actions
    assert all(action["tool"] == "forums.read" for action in next_actions)

    action_fids = _extract_action_fids(next_actions)
    assert 375 in action_fids
    assert 261 in action_fids
    assert 444 not in action_fids
    assert 241 not in action_fids
    assert 105 not in action_fids
    assert 7 not in action_fids
    assert 53 not in action_fids
    assert tree_flow["entities"]["forum_ids"] == flow["entities"]["forum_ids"]
    assert _extract_action_fids(tree_flow["next_actions"]) == action_fids


def test_forums_index_raw_output_uses_local_catalog_resource_without_claiming_upstream_raw_payload() -> None:
    handler = build_forum_index_handlers()["forums.index"]
    raw_mode_result = handler(output_mode="raw")
    include_raw_result = handler(output_mode="structured", include_raw_payload=True)

    for result in (raw_mode_result, include_raw_result):
        resources = [entry for entry in result["content"] if entry.get("type") == "resource"]
        assert len(resources) == 1
        resource = resources[0]["resource"]
        assert resource["uri"] == "hf-mcp://catalog/forums.index"
        payload = json.loads(resource["text"])
        assert payload["source"] == "hf-mcp curated package catalog"
        assert isinstance(result["structuredContent"], dict)


def test_forums_index_include_inactive_controls_payload_and_actions() -> None:
    handler = build_forum_index_handlers()["forums.index"]
    default_result = handler()
    include_inactive_result = handler(include_inactive=True)

    default_fids = {node["fid"] for node in default_result["structuredContent"]["nodes"]}
    include_inactive_fids = {node["fid"] for node in include_inactive_result["structuredContent"]["nodes"]}
    assert default_fids == include_inactive_fids

    default_action_fids = _extract_action_fids(default_result["structuredContent"]["_hf_flow"]["next_actions"])
    include_action_fids = _extract_action_fids(include_inactive_result["structuredContent"]["_hf_flow"]["next_actions"])
    assert default_action_fids == include_action_fids
