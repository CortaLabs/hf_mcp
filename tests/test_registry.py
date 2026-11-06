from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from hf_mcp import registry
from hf_mcp.registry import (
    DRAFT_ID_PATTERN,
    FAMILY_KEY,
    TOOLS,
    WIRE_KEY,
    get_specs,
    get_tool_spec,
)

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"

# A9: the (tool, property) pairs that mirror the Hack Forums v2 wire.
EXPECTED_WIRE_PAIRS = {
    ("bytes.read", "id"),
    ("bytes.read", "from_uid"),
    ("bytes.read", "to_uid"),
    ("contracts.read", "cid"),
    ("disputes.read", "cdid"),
    ("disputes.read", "cid"),
    ("disputes.read", "claimantuid"),
    ("disputes.read", "defendantuid"),
    ("bratings.read", "crid"),
    ("bratings.read", "cid"),
    ("bratings.read", "from_uid"),
    ("bratings.read", "to_uid"),
    ("sigmarket.order.read", "smid"),
    ("sigmarket.order.read", "oid"),
    ("sigmarket.order.read", "seller"),
    ("sigmarket.order.read", "buyer"),
    *{
        (name, "per_page")
        for name in (
            "users.read",
            "forums.read",
            "threads.read",
            "posts.read",
            "bytes.read",
            "contracts.read",
            "disputes.read",
            "bratings.read",
            "sigmarket.market.read",
            "sigmarket.order.read",
            "admin.high_risk.read",
        )
    },
    ("me.read", "include_basic_fields"),
    ("me.read", "include_advanced_fields"),
    ("users.read", "include_profile_fields"),
    ("posts.read", "include_post_body"),
    ("bytes.read", "include_amount"),
    *{
        (name, prop)
        for name in (
            "me.read",
            "users.read",
            "forums.read",
            "threads.read",
            "posts.read",
            "bytes.read",
            "contracts.read",
            "disputes.read",
            "bratings.read",
            "sigmarket.market.read",
            "sigmarket.order.read",
            "admin.high_risk.read",
            "forums.index",
        )
        for prop in ("output_mode", "include_raw_payload")
    },
}


def test_table_declares_the_24_published_tools_once() -> None:
    assert len(TOOLS) == 24
    assert len({spec.name for spec in TOOLS}) == 24
    assert len({spec.mcp_name for spec in TOOLS}) == 24
    assert get_tool_spec("threads.read").mcp_name == "threads_read"
    with pytest.raises(KeyError):
        get_tool_spec("hf.doctor")


def test_groups_select_the_handler_modules() -> None:
    assert [s.name for s in get_specs("core_read")] == [
        "me.read",
        "users.read",
        "forums.read",
        "threads.read",
        "posts.read",
    ]
    assert len(get_specs("extended_read")) == 7
    assert {s.name for s in get_specs("write")} == {
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
    }
    assert {s.name for s in get_specs("local")} == {
        "forums.index",
        "formatting.preflight",
        "drafts.list",
        "drafts.read",
        "drafts.update",
        "drafts.delete",
    }


def test_every_row_is_a_closed_draft_2020_12_object_with_tagged_properties() -> None:
    for spec in TOOLS:
        schema = spec.input_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        properties = schema["properties"]
        assert all(FAMILY_KEY in prop for prop in properties.values()), spec.name
        assert set(schema.get("required", ())) <= set(properties), spec.name
        for branch in schema.get("anyOf", ()):
            assert set(branch["required"]) <= set(properties), spec.name
        assert spec.required_families <= spec.families, spec.name


def test_amount_minimum_and_any_of_live_in_their_own_rows() -> None:
    assert (
        get_tool_spec("bytes.deposit").input_schema["properties"]["amount"]["minimum"]
        == 100
    )
    assert (
        get_tool_spec("bytes.transfer").input_schema["properties"]["amount"]["minimum"]
        == 1
    )
    assert get_tool_spec("threads.read").input_schema["anyOf"] == [
        {"required": ["fid"]},
        {"required": ["tid"]},
        {"required": ["uid"]},
    ]


def test_wire_tagged_properties_match_the_expected_list() -> None:
    tagged = {
        (spec.name, name)
        for spec in TOOLS
        for name, prop in spec.input_schema["properties"].items()
        if prop.get(WIRE_KEY) is True
    }
    assert tagged == EXPECTED_WIRE_PAIRS


def test_drafts_delete_requires_a_const_confirmation_without_default() -> None:
    schema = get_tool_spec("drafts.delete").input_schema
    assert "confirm_delete" in schema["required"]
    confirm = schema["properties"]["confirm_delete"]
    assert confirm["type"] == "boolean"
    assert confirm["const"] is True
    assert "default" not in confirm


def test_no_published_default_contradicts_its_own_const_or_enum() -> None:
    def walk(spec_name: str, name: str, prop: dict[str, Any]) -> None:
        if "default" not in prop:
            return
        if "const" in prop:
            assert prop["default"] == prop["const"], (spec_name, name)
        if "enum" in prop:
            assert prop["default"] in prop["enum"], (spec_name, name)

    for spec in TOOLS:
        for name, prop in spec.input_schema["properties"].items():
            walk(spec.name, name, prop)


def test_draft_id_pattern_is_defined_once_in_the_registry() -> None:
    assert DRAFT_ID_PATTERN == "^[a-f0-9]{32}$"
    for tool in ("drafts.read", "drafts.update", "drafts.delete", "posts.reply"):
        prop = get_tool_spec(tool).input_schema["properties"]["draft_id"]
        assert prop["pattern"] == DRAFT_ID_PATTERN


def test_annotation_flags_and_output_schemas() -> None:
    for spec in TOOLS:
        assert set(spec.annotations) == {
            "readOnlyHint",
            "destructiveHint",
            "idempotentHint",
            "openWorldHint",
        }
        if spec.group == "write":
            assert spec.output_schema is None
        elif spec.operation != "write":
            assert spec.output_schema == {
                "type": "object",
                "additionalProperties": True,
            }
    assert get_tool_spec("drafts.delete").annotations["destructiveHint"] is True
    assert get_tool_spec("formatting.preflight").annotations["readOnlyHint"] is False


def test_registry_imports_nothing_from_hf_mcp() -> None:
    tree = ast.parse(Path(registry.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0 and not (node.module or "").startswith("hf_mcp")
        elif isinstance(node, ast.Import):
            assert not any(alias.name.startswith("hf_mcp") for alias in node.names)


@pytest.mark.parametrize(
    "order",
    [
        ("hf_mcp.registry", "hf_mcp.config", "hf_mcp.capabilities"),
        ("hf_mcp.capabilities", "hf_mcp.config", "hf_mcp.registry"),
    ],
)
def test_modules_import_without_cycles_in_either_order(order: tuple[str, ...]) -> None:
    code = "import " + "\nimport ".join(order)
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(SRC_PATH), "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_deleted_modules_are_gone() -> None:
    for name in ("schemas", "metadata", "annotations"):
        assert not (SRC_PATH / "hf_mcp" / f"{name}.py").exists()
