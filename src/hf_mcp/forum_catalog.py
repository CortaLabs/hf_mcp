from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import json
from typing import Any

_ALLOWED_VIEWS: frozenset[str] = frozenset({"flat", "tree"})


@dataclass(frozen=True, slots=True)
class _ForumCatalogNode:
    fid: int
    name: str
    active: bool
    is_category: bool
    parent_fid: int | None
    category_fid: int | None


def _coerce_fid(raw_value: object, *, field_name: str) -> int:
    if not isinstance(raw_value, int) or isinstance(raw_value, bool):
        raise ValueError(f"`{field_name}` must be an integer.")
    if raw_value <= 0:
        raise ValueError(f"`{field_name}` must be greater than zero.")
    return raw_value


def _coerce_optional_fid(raw_value: object, *, field_name: str) -> int | None:
    if raw_value is None:
        return None
    return _coerce_fid(raw_value, field_name=field_name)


def _coerce_name(raw_value: object) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ValueError("Each catalog node must include a non-empty `name`.")
    return raw_value.strip()


def _coerce_bool(raw_value: object, *, field_name: str) -> bool:
    if not isinstance(raw_value, bool):
        raise ValueError(f"`{field_name}` must be a boolean.")
    return raw_value


def _load_catalog_payload() -> object:
    catalog_path = files("hf_mcp").joinpath("data", "forums_index.json")
    try:
        return json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to load package forum catalog.") from exc


def _validate_nodes(raw_nodes: object) -> list[_ForumCatalogNode]:
    if not isinstance(raw_nodes, list):
        raise ValueError("`nodes` must be a list.")
    if not raw_nodes:
        raise ValueError("`nodes` must not be empty.")

    nodes: list[_ForumCatalogNode] = []
    seen_fids: set[int] = set()
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            raise ValueError("Each catalog node must be an object.")
        fid = _coerce_fid(raw_node.get("fid"), field_name="fid")
        if fid in seen_fids:
            raise ValueError(f"Duplicate forum id detected: {fid}.")
        seen_fids.add(fid)
        node = _ForumCatalogNode(
            fid=fid,
            name=_coerce_name(raw_node.get("name")),
            active=_coerce_bool(raw_node.get("active", True), field_name=f"nodes[{fid}].active"),
            is_category=_coerce_bool(raw_node.get("is_category", False), field_name=f"nodes[{fid}].is_category"),
            parent_fid=_coerce_optional_fid(raw_node.get("parent_fid"), field_name=f"nodes[{fid}].parent_fid"),
            category_fid=_coerce_optional_fid(raw_node.get("category_fid"), field_name=f"nodes[{fid}].category_fid"),
        )
        nodes.append(node)

    by_fid = {node.fid: node for node in nodes}
    for node in nodes:
        if node.parent_fid is not None and node.parent_fid not in by_fid:
            raise ValueError(f"Node {node.fid} references unknown parent_fid {node.parent_fid}.")
        if node.category_fid is not None and node.category_fid not in by_fid:
            raise ValueError(f"Node {node.fid} references unknown category_fid {node.category_fid}.")
        if node.category_fid is not None and not by_fid[node.category_fid].is_category:
            raise ValueError(
                f"Node {node.fid} category_fid {node.category_fid} must reference a category node."
            )
    return nodes


def _node_to_dict(node: _ForumCatalogNode) -> dict[str, Any]:
    return {
        "fid": node.fid,
        "name": node.name,
        "active": node.active,
        "is_category": node.is_category,
        "parent_fid": node.parent_fid,
        "category_fid": node.category_fid,
    }


def load_forum_catalog() -> dict[str, Any]:
    raw_payload = _load_catalog_payload()
    if not isinstance(raw_payload, dict):
        raise ValueError("Forum catalog root must be an object.")
    if "nodes" not in raw_payload:
        raise ValueError("Forum catalog must include `nodes`.")

    nodes = _validate_nodes(raw_payload["nodes"])
    catalog = dict(raw_payload)
    catalog["nodes"] = [_node_to_dict(node) for node in nodes]
    return catalog


def _filter_nodes(nodes: list[dict[str, Any]], *, include_inactive: bool) -> list[dict[str, Any]]:
    if include_inactive:
        return [dict(node) for node in nodes]
    return [dict(node) for node in nodes if bool(node["active"])]


def _build_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tree_nodes: dict[int, dict[str, Any]] = {}
    for node in nodes:
        tree_nodes[node["fid"]] = {
            "fid": node["fid"],
            "name": node["name"],
            "active": node["active"],
            "is_category": node["is_category"],
            "parent_fid": node["parent_fid"],
            "category_fid": node["category_fid"],
            "children": [],
        }

    roots: list[dict[str, Any]] = []
    for node in nodes:
        entry = tree_nodes[node["fid"]]
        parent_fid = node["parent_fid"]
        if parent_fid is not None and parent_fid in tree_nodes:
            tree_nodes[parent_fid]["children"].append(entry)
        else:
            roots.append(entry)
    return roots


def build_forum_index_payload(*, view: str = "flat", include_inactive: bool = False) -> dict[str, Any]:
    if view not in _ALLOWED_VIEWS:
        raise ValueError(f"Unsupported view '{view}'. Supported views: flat, tree.")

    catalog = load_forum_catalog()
    nodes = catalog["nodes"]
    if not isinstance(nodes, list):
        raise ValueError("Validated catalog must include list-based `nodes`.")
    filtered_nodes = _filter_nodes(nodes, include_inactive=include_inactive)

    payload: dict[str, Any] = {
        "view": view,
        "include_inactive": include_inactive,
        "nodes": filtered_nodes if view == "flat" else _build_tree(filtered_nodes),
    }
    return payload


__all__ = ["build_forum_index_payload", "load_forum_catalog"]
