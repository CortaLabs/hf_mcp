from __future__ import annotations

import sys
from pathlib import Path

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.metadata import get_tool_specs
from hf_mcp.registry import build_registry, get_tool_spec, mcp_tool_name
from hf_mcp.schemas import build_tool_schema
import hf_mcp.registry as registry_module


def _policy(capabilities: set[str], parameter_families: set[str]) -> CapabilityPolicy:
    settings = HFMCPSettings(
        profile="test",
        enabled_capabilities=frozenset(capabilities),
        enabled_parameter_families=frozenset(parameter_families),
    )
    return CapabilityPolicy(settings=settings)


def test_registry_covers_documented_matrix_once() -> None:
    specs = build_registry()
    tool_names = {spec.tool_name for spec in specs}
    mcp_tool_names = {mcp_tool_name(spec.tool_name) for spec in specs}

    assert len(specs) == len(registry_module._EXPECTED_COVERAGE_FAMILIES)
    assert {spec.coverage_family for spec in specs} == registry_module._EXPECTED_COVERAGE_FAMILIES
    assert len(tool_names) == len(specs)
    assert len(mcp_tool_names) == len(specs)
    assert "transport.read" not in tool_names
    assert "transport.write" not in tool_names
    assert "." not in "".join(mcp_tool_names)
    local_generic_tools = {"formatting.preflight", "drafts.list", "drafts.read", "drafts.update", "drafts.delete"}
    assert all(
        spec.transport_kind == ("generic" if spec.tool_name in local_generic_tools else "helper")
        for spec in specs
    )


def test_mcp_tool_names_are_desktop_client_safe() -> None:
    assert mcp_tool_name("posts.read") == "posts_read"
    assert mcp_tool_name("threads.create") == "threads_create"
    assert mcp_tool_name("sigmarket.order.read") == "sigmarket_order_read"
    assert mcp_tool_name("admin.high_risk.read") == "admin_high_risk_read"
    assert mcp_tool_name("formatting.preflight") == "formatting_preflight"
    assert mcp_tool_name("drafts.list") == "drafts_list"
    assert mcp_tool_name("drafts.read") == "drafts_read"
    assert mcp_tool_name("drafts.update") == "drafts_update"
    assert mcp_tool_name("drafts.delete") == "drafts_delete"

    for spec in build_registry():
        public_name = mcp_tool_name(spec.tool_name)
        assert len(public_name) <= 64
        assert all(character.isalnum() or character in "_-" for character in public_name)


def test_get_tool_spec_returns_helper_row_metadata() -> None:
    spec = get_tool_spec("threads.read")
    assert spec.operation == "read"
    assert spec.helper_path == "threads"
    assert spec.coverage_family == "threads.read"
    assert spec.transport_kind == "helper"


def test_build_tool_schema_prunes_to_allowed_parameter_families() -> None:
    spec = get_tool_spec("threads.read")
    policy = _policy(
        capabilities={"threads.read"},
        parameter_families={"selectors.thread"},
    )

    schema = build_tool_schema(spec, policy)

    assert set(schema["properties"]) == {"tid", "uid", "output_mode", "include_raw_payload", "body_format"}
    assert "required" not in schema
    assert schema["anyOf"] == [{"required": ["tid"]}, {"required": ["uid"]}]
    assert schema["x-hf-coverage-family"] == "threads.read"


def test_build_tool_schema_fails_closed_when_capability_disabled() -> None:
    spec = get_tool_spec("threads.read")
    policy = _policy(
        capabilities=set(),
        parameter_families={"selectors.thread"},
    )

    schema = build_tool_schema(spec, policy)

    assert schema == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def test_posts_schema_supports_pid_tid_uid_selector_anyof() -> None:
    spec = get_tool_spec("posts.read")
    policy = _policy(
        capabilities={"posts.read"},
        parameter_families={"selectors.thread", "selectors.post", "filters.pagination", "fields.posts.body"},
    )

    schema = build_tool_schema(spec, policy)

    assert {"pid", "tid", "uid", "page", "per_page"} <= set(schema["properties"])
    assert "required" not in schema
    assert schema["anyOf"] == [{"required": ["pid"]}, {"required": ["tid"]}, {"required": ["uid"]}]
    assert schema["additionalProperties"] is False


def test_extended_read_schemas_expose_canonical_selectors_and_alias_compatibility() -> None:
    policy = _policy(
        capabilities={
            "bytes.read",
            "contracts.read",
            "disputes.read",
            "bratings.read",
            "sigmarket.market.read",
            "sigmarket.order.read",
        },
        parameter_families={
            "selectors.bytes",
            "selectors.contract",
            "selectors.dispute",
            "selectors.sigmarket",
            "filters.pagination",
            "fields.bytes.amount",
        },
    )

    bytes_schema = build_tool_schema(get_tool_spec("bytes.read"), policy)
    assert {"id", "uid", "from_uid", "to_uid", "target_uid", "page", "per_page"} <= set(bytes_schema["properties"])
    assert "required" not in bytes_schema

    contracts_schema = build_tool_schema(get_tool_spec("contracts.read"), policy)
    assert {"cid", "uid"} <= set(contracts_schema["properties"])
    assert "contract_id" not in contracts_schema["properties"]

    disputes_schema = build_tool_schema(get_tool_spec("disputes.read"), policy)
    assert {"cdid", "cid", "uid", "claimantuid", "defendantuid"} <= set(disputes_schema["properties"])
    assert "dispute_id" not in disputes_schema["properties"]

    bratings_schema = build_tool_schema(get_tool_spec("bratings.read"), policy)
    assert {"crid", "cid", "uid", "from_uid", "to_uid"} <= set(bratings_schema["properties"])

    order_schema = build_tool_schema(get_tool_spec("sigmarket.order.read"), policy)
    assert {"smid", "oid", "uid", "seller", "buyer"} <= set(order_schema["properties"])
    assert "listing_id" not in order_schema["properties"]


def test_build_registry_rejects_duplicate_tool_names(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate_row = registry_module._MATRIX_ROWS[0]
    monkeypatch.setattr(registry_module, "_MATRIX_ROWS", registry_module._MATRIX_ROWS + (duplicate_row,))

    with pytest.raises(ValueError, match="Duplicate tool_name entries in registry"):
        build_registry()


def test_build_registry_rejects_missing_documented_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        registry_module,
        "_MATRIX_ROWS",
        tuple(
            row
            for row in registry_module._MATRIX_ROWS
            if row.coverage_family != "bytes.bump"
        ),
    )

    with pytest.raises(ValueError, match="Missing documented coverage families: bytes.bump"):
        build_registry()


def test_has_concrete_handler_is_true_for_registered_rows() -> None:
    assert registry_module.has_concrete_handler("threads.read") is True
    assert registry_module.has_concrete_handler("posts.reply") is True


def test_get_tool_specs_omits_forbidden_write_families_when_policy_enables_them() -> None:
    policy = _policy(
        capabilities={
            "threads.read",
            "posts.reply",
            "contracts.write",
            "sigmarket.write",
            "admin.high_risk.write",
            "formatting.preflight",
        },
        parameter_families={"selectors.thread", "writes.content", "confirm.live", "formatting.content"},
    )

    tool_names = {spec.tool_name for spec in get_tool_specs(policy)}
    assert "threads.read" in tool_names
    assert "posts.reply" in tool_names
    assert "contracts.write" not in tool_names
    assert "sigmarket.write" not in tool_names
    assert "admin.high_risk.write" not in tool_names
    assert {"drafts.list", "drafts.read", "drafts.update", "drafts.delete"} <= tool_names


def test_build_registry_does_not_emit_removed_placeholder_write_rows() -> None:
    tool_names = {spec.tool_name for spec in build_registry()}
    assert "contracts.write" not in tool_names
    assert "sigmarket.write" not in tool_names
    assert "admin.high_risk.write" not in tool_names


def test_build_tool_schema_adds_read_output_mode_params_only_for_reads() -> None:
    policy = _policy(
        capabilities={"threads.read", "posts.reply"},
        parameter_families={"selectors.thread", "writes.content", "confirm.live"},
    )

    read_schema = build_tool_schema(get_tool_spec("threads.read"), policy)
    read_properties = read_schema["properties"]
    assert set(read_properties["output_mode"]["enum"]) == {"readable", "structured", "raw"}
    assert read_properties["output_mode"]["default"] == "readable"
    assert read_properties["include_raw_payload"]["type"] == "boolean"
    assert read_properties["include_raw_payload"]["default"] is False
    assert set(read_properties["body_format"]["enum"]) == {"raw", "clean", "markdown"}
    assert read_properties["body_format"]["default"] == "markdown"
    assert "output_mode" not in set(read_schema.get("required", []))
    assert "include_raw_payload" not in set(read_schema.get("required", []))
    assert "body_format" not in set(read_schema.get("required", []))

    write_schema = build_tool_schema(get_tool_spec("posts.reply"), policy)
    write_properties = write_schema["properties"]
    assert "output_mode" not in write_properties
    assert "include_raw_payload" not in write_properties
    assert write_properties["message_format"]["default"] == "mycode"


def test_build_tool_schema_truthful_core_write_shapes() -> None:
    policy = _policy(
        capabilities={
            "threads.create",
            "posts.reply",
            "bytes.transfer",
            "bytes.deposit",
            "bytes.withdraw",
            "bytes.bump",
        },
        parameter_families={
            "selectors.forum",
            "selectors.thread",
            "selectors.bytes",
            "writes.content",
            "writes.bytes",
            "confirm.live",
        },
    )

    expected_shapes: dict[str, tuple[set[str], set[str]]] = {
        "threads.create": (
            {"fid", "subject", "message", "draft_id", "draft_path", "message_format", "confirm_live"},
            {"fid", "subject", "confirm_live"},
        ),
        "posts.reply": (
            {"tid", "message", "draft_id", "draft_path", "message_format", "confirm_live"},
            {"tid", "confirm_live"},
        ),
        "bytes.transfer": ({"target_uid", "amount", "confirm_live"}, {"target_uid", "amount", "confirm_live"}),
        "bytes.deposit": ({"amount", "confirm_live"}, {"amount", "confirm_live"}),
        "bytes.withdraw": ({"amount", "confirm_live"}, {"amount", "confirm_live"}),
        "bytes.bump": ({"tid", "confirm_live"}, {"tid", "confirm_live"}),
    }

    for tool_name, (expected_properties, expected_required) in expected_shapes.items():
        schema = build_tool_schema(get_tool_spec(tool_name), policy)
        assert set(schema["properties"]) == expected_properties
        assert set(schema.get("required", [])) == expected_required
        assert "output_mode" not in schema["properties"]
        assert "include_raw_payload" not in schema["properties"]
        if "message_format" in schema["properties"]:
            assert schema["properties"]["message_format"]["enum"] == ["mycode", "markdown"]
        if "message" in schema["properties"]:
            assert schema["anyOf"] == [{"required": ["message"]}, {"required": ["draft_id"]}, {"required": ["draft_path"]}]


def test_build_tool_schema_truthful_formatting_preflight_shape() -> None:
    policy = _policy(
        capabilities={"formatting.preflight"},
        parameter_families={"formatting.content"},
    )

    schema = build_tool_schema(get_tool_spec("formatting.preflight"), policy)

    assert set(schema["properties"]) == {"message", "source_path", "message_format"}
    assert "required" not in schema
    assert schema["anyOf"] == [{"required": ["message"]}, {"required": ["source_path"]}]
    assert schema["properties"]["message_format"]["default"] == "markdown"
    assert schema["properties"]["message_format"]["enum"] == ["mycode", "markdown"]


def test_build_tool_schema_truthful_local_draft_shapes() -> None:
    policy = _policy(
        capabilities={"formatting.preflight"},
        parameter_families={"formatting.content", "drafts.selector", "drafts.filters", "drafts.metadata", "drafts.confirm_delete"},
    )

    list_schema = build_tool_schema(get_tool_spec("drafts.list"), policy)
    assert list_schema["type"] == "object"
    assert list_schema["additionalProperties"] is False
    assert "anyOf" not in list_schema
    assert set(list_schema["properties"]) == {
        "status",
        "category",
        "title",
        "scheduled_before",
        "scheduled_after",
        "limit",
        "offset",
    }

    read_schema = build_tool_schema(get_tool_spec("drafts.read"), policy)
    assert read_schema["additionalProperties"] is False
    assert set(read_schema["properties"]) == {"draft_id", "draft_path"}
    assert read_schema["anyOf"] == [{"required": ["draft_id"]}, {"required": ["draft_path"]}]

    update_schema = build_tool_schema(get_tool_spec("drafts.update"), policy)
    assert update_schema["additionalProperties"] is False
    assert set(update_schema["properties"]) == {
        "draft_id",
        "draft_path",
        "title",
        "category",
        "status",
        "scheduled_at",
    }
    assert update_schema["anyOf"] == [{"required": ["draft_id"]}, {"required": ["draft_path"]}]
    assert "message" not in update_schema["properties"]
    assert "source_path" not in update_schema["properties"]
    assert "body" not in update_schema["properties"]

    delete_schema = build_tool_schema(get_tool_spec("drafts.delete"), policy)
    assert delete_schema["additionalProperties"] is False
    assert set(delete_schema["properties"]) == {"draft_id", "draft_path", "confirm_delete"}
    assert delete_schema["required"] == ["confirm_delete"]
    assert delete_schema["properties"]["confirm_delete"]["const"] is True
    assert delete_schema["anyOf"] == [{"required": ["draft_id"]}, {"required": ["draft_path"]}]
