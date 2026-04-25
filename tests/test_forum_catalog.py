from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp import forum_catalog
from hf_mcp.forum_catalog import build_forum_index_payload, load_forum_catalog


class _FakeCatalogResource:
    def __init__(self, text: str) -> None:
        self._text = text

    def read_text(self, *, encoding: str = "utf-8") -> str:
        del encoding
        return self._text


class _FakePackageRoot:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def joinpath(self, *parts: str) -> _FakeCatalogResource:
        assert parts == ("data", "forums_index.json")
        return _FakeCatalogResource(json.dumps(self._payload))


def _patch_catalog_payload(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(forum_catalog, "files", lambda _package: _FakePackageRoot(payload))


def test_load_forum_catalog_returns_valid_nodes() -> None:
    catalog = load_forum_catalog()

    assert isinstance(catalog, dict)
    assert catalog["nodes"]
    assert all("fid" in node and "name" in node for node in catalog["nodes"])


def test_build_forum_index_payload_flat_and_tree_use_same_catalog() -> None:
    flat = build_forum_index_payload(view="flat")
    tree = build_forum_index_payload(view="tree")

    assert flat["view"] == "flat"
    assert tree["view"] == "tree"
    assert len(flat["nodes"]) == 4
    flat_fids = {node["fid"] for node in flat["nodes"]}

    tree_fids: set[int] = set()

    def _collect(entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            tree_fids.add(entry["fid"])
            _collect(entry["children"])

    _collect(tree["nodes"])
    assert tree_fids == flat_fids
    assert 169 not in tree_fids


def test_build_forum_index_payload_include_inactive_true_retains_inactive_nodes() -> None:
    payload = build_forum_index_payload(view="flat", include_inactive=True)
    fids = {node["fid"] for node in payload["nodes"]}
    assert 169 in fids


def test_load_forum_catalog_rejects_duplicate_fid(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_catalog_payload(
        monkeypatch,
        {
            "nodes": [
                {"fid": 2, "name": "A", "is_category": True},
                {"fid": 2, "name": "B", "parent_fid": 2, "category_fid": 2},
            ]
        },
    )

    with pytest.raises(ValueError, match="Duplicate forum id"):
        load_forum_catalog()


def test_load_forum_catalog_rejects_invalid_parent_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_catalog_payload(
        monkeypatch,
        {
            "nodes": [
                {"fid": 2, "name": "A", "is_category": True},
                {"fid": 3, "name": "B", "parent_fid": 99, "category_fid": 2},
            ]
        },
    )

    with pytest.raises(ValueError, match="unknown parent_fid"):
        load_forum_catalog()


def test_load_forum_catalog_rejects_invalid_category_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_catalog_payload(
        monkeypatch,
        {
            "nodes": [
                {"fid": 2, "name": "A", "is_category": False},
                {"fid": 3, "name": "B", "parent_fid": 2, "category_fid": 2},
            ]
        },
    )

    with pytest.raises(ValueError, match="must reference a category node"):
        load_forum_catalog()


def test_load_forum_catalog_rejects_missing_name(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_catalog_payload(monkeypatch, {"nodes": [{"fid": 2, "active": True}]})

    with pytest.raises(ValueError, match="non-empty `name`"):
        load_forum_catalog()


def test_build_forum_index_payload_rejects_unsupported_view() -> None:
    with pytest.raises(ValueError, match="Unsupported view"):
        build_forum_index_payload(view="grid")
