from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.annotations import build_annotations
from hf_mcp.capabilities import CapabilityPolicy
from hf_mcp.config import HFMCPSettings
from hf_mcp.metadata import build_tool_meta, get_tool_specs
from hf_mcp.registry import ToolSpec, build_registry, get_tool_spec, mcp_tool_name
import hf_mcp.registry as registry_module

pytestmark = [pytest.mark.core, pytest.mark.registry]


EXPECTED_FACTS = {
    "me.read": ("me.read", "me.read", "read", "me", "helper", ("fields.me.advanced", "fields.me.basic", "selectors.user"), "remote"),
    "users.read": ("users.read", "users.read", "read", "users", "helper", ("fields.users.profile", "filters.pagination", "selectors.user"), "remote"),
    "forums.index": ("forums.read", "forums.index", "read", None, "generic", (), "local"),
    "forums.read": ("forums.read", "forums.read", "read", "forums", "helper", ("filters.pagination", "selectors.forum"), "remote"),
    "threads.read": ("threads.read", "threads.read", "read", "threads", "helper", ("filters.pagination", "selectors.forum", "selectors.thread"), "remote"),
    "posts.read": ("posts.read", "posts.read", "read", "posts", "helper", ("fields.posts.body", "filters.pagination", "selectors.post", "selectors.thread"), "remote"),
    "bytes.read": ("bytes.read", "bytes.read", "read", "bytes", "helper", ("fields.bytes.amount", "selectors.bytes"), "remote"),
    "contracts.read": ("contracts.read", "contracts.read", "read", "contracts", "helper", ("filters.pagination", "selectors.contract"), "remote"),
    "disputes.read": ("disputes.read", "disputes.read", "read", "disputes", "helper", ("filters.pagination", "selectors.dispute"), "remote"),
    "bratings.read": ("bratings.read", "bratings.read", "read", "bratings", "helper", ("filters.pagination", "selectors.user"), "remote"),
    "sigmarket.market.read": ("sigmarket.market.read", "sigmarket.market.read", "read", "sigmarket/market", "helper", ("filters.pagination", "selectors.sigmarket"), "remote"),
    "sigmarket.order.read": ("sigmarket.order.read", "sigmarket.order.read", "read", "sigmarket/order", "helper", ("filters.pagination", "selectors.sigmarket"), "remote"),
    "admin.high_risk.read": ("admin.high_risk.read", "admin.high_risk.read", "read", "admin/high-risk/read", "helper", ("filters.pagination",), "remote"),
    "formatting.preflight": ("formatting.preflight", "formatting.preflight", "read", None, "generic", ("formatting.content",), "local"),
    "drafts.list": ("formatting.preflight", "drafts.list", "read", None, "generic", ("drafts.filters",), "local"),
    "drafts.read": ("formatting.preflight", "drafts.read", "read", None, "generic", ("drafts.selector",), "local"),
    "drafts.update": ("formatting.preflight", "drafts.update", "write", None, "generic", ("drafts.metadata", "drafts.selector"), "local"),
    "drafts.delete": ("formatting.preflight", "drafts.delete", "write", None, "generic", ("drafts.confirm_delete", "drafts.selector"), "local"),
    "threads.create": ("threads.create", "threads.create", "write", "threads", "helper", ("confirm.live", "selectors.forum", "writes.content"), "remote"),
    "posts.reply": ("posts.reply", "posts.reply", "write", "posts", "helper", ("confirm.live", "selectors.thread", "writes.content"), "remote"),
    "bytes.transfer": ("bytes.transfer", "bytes.transfer", "write", "bytes", "helper", ("confirm.live", "selectors.bytes", "writes.bytes"), "remote"),
    "bytes.deposit": ("bytes.deposit", "bytes.deposit", "write", "bytes/deposit", "helper", ("confirm.live", "selectors.bytes", "writes.bytes"), "remote"),
    "bytes.withdraw": ("bytes.withdraw", "bytes.withdraw", "write", "bytes/withdraw", "helper", ("confirm.live", "selectors.bytes", "writes.bytes"), "remote"),
    "bytes.bump": ("bytes.bump", "bytes.bump", "write", "bytes/bump", "helper", ("confirm.live", "selectors.bytes", "writes.bytes"), "remote"),
    "hf.doctor": ("hf.doctor", "hf.doctor", "read", None, "generic", (), "local"),
}


@pytest.mark.regression
def test_registry_preserves_existing_facts_and_adds_doctor() -> None:
    specs = build_registry()
    assert len(specs) == 25
    assert {spec.tool_name for spec in specs} == set(EXPECTED_FACTS)
    for spec in specs:
        capability, coverage, operation, helper, transport, families, locality = EXPECTED_FACTS[spec.tool_name]
        assert (
            spec.capability_family,
            spec.coverage_family,
            spec.operation,
            spec.helper_path,
            spec.transport_kind,
            spec.parameter_families,
            spec.locality,
        ) == (capability, coverage, operation, helper, transport, families, locality)
        assert mcp_tool_name(spec.tool_name) == spec.tool_name.replace(".", "_")


def test_tool_spec_keeps_seven_argument_compatibility_and_is_frozen_slotted() -> None:
    spec = ToolSpec("custom.read", "custom.read", "custom.read", "read", None, "generic", ())
    assert spec.locality == "remote"
    assert spec.name == "custom.read"
    assert not hasattr(spec, "__dict__")
    with pytest.raises(FrozenInstanceError):
        spec.locality = "local"  # type: ignore[misc]


def test_parameter_families_are_sorted_and_deduplicated() -> None:
    row = registry_module._MatrixRow(
        "custom.read", "custom.read", "custom.read", "read", None, "generic",
        parameter_families=("selectors.user", "fields.me.basic", "selectors.user"),
    )
    assert registry_module._resolve_parameter_families(row) == ("fields.me.basic", "selectors.user")


def test_registry_rejects_duplicate_public_names_invalid_names_and_unknown_tools() -> None:
    base = ToolSpec("first.tool", "first.tool", "first.tool", "read", None, "generic", ())
    collision = ToolSpec("first_tool", "first_tool", "first_tool", "read", None, "generic", ())
    with pytest.raises(ValueError, match="Duplicate MCP tool name"):
        registry_module._validate_registry([base, collision])

    invalid = ToolSpec("invalid/tool", "invalid/tool", "invalid/tool", "read", None, "generic", ())
    with pytest.raises(ValueError, match="invalid MCP tool name"):
        registry_module._validate_registry([invalid])

    with pytest.raises(KeyError, match="Unknown tool"):
        get_tool_spec("not.registered")


@pytest.mark.regression
def test_locality_drives_metadata_and_annotations_without_losing_behavior_hints() -> None:
    expected_hints = {
        "forums.index": (True, False, True, False, 1),
        "hf.doctor": (True, False, True, False, 1),
        "formatting.preflight": (False, False, False, False, 1),
        "drafts.list": (True, False, True, False, 1),
        "drafts.read": (True, False, True, False, 1),
        "drafts.update": (False, False, False, False, 2),
        "drafts.delete": (False, True, False, False, 2),
        "threads.read": (True, False, True, True, 4),
        "threads.create": (False, True, False, True, 4),
    }
    for name, (read_only, destructive, idempotent, open_world, tier) in expected_hints.items():
        spec = get_tool_spec(name)
        annotations = build_annotations(spec)
        assert (
            annotations["readOnlyHint"],
            annotations["destructiveHint"],
            annotations["idempotentHint"],
            annotations["openWorldHint"],
        ) == (read_only, destructive, idempotent, open_world)
        metadata = build_tool_meta(spec)
        assert metadata["x-hf-locality"] == spec.locality
        assert metadata["x-hf-runtime-tier"] == tier
        assert metadata["x-hf-helper-path"] == spec.helper_path
        assert metadata["x-hf-transport-kind"] == spec.transport_kind

    assert set(build_tool_meta(get_tool_spec("hf.doctor"))) == {
        "x-hf-locality", "x-hf-runtime-tier", "x-hf-operation", "x-hf-capability-family",
        "x-hf-coverage-family", "x-hf-helper-path", "x-hf-transport-kind", "x-hf-output-default",
        "x-hf-output-readable", "x-hf-output-field-bundles",
    }


def test_policy_filtering_does_not_special_case_doctor() -> None:
    class Policy:
        def can_register(self, name: str) -> bool:
            return name == "threads.read"

    assert [spec.tool_name for spec in get_tool_specs(Policy())] == ["threads.read"]

    capability_policy = CapabilityPolicy(
        HFMCPSettings(
            profile="test",
            enabled_capabilities=frozenset({"hf.doctor"}),
            enabled_parameter_families=frozenset(),
        )
    )
    assert not capability_policy.can_register("hf.doctor")
    assert get_tool_specs(capability_policy) == []


def test_registry_import_is_independent_of_policy_and_handler_modules() -> None:
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        blocked = ("hf_mcp.capabilities", "hf_mcp.config", "hf_mcp.metadata", "hf_mcp.dispatcher", "hf_mcp.transport", "hf_mcp.handlers", "hf_mcp.tools")

        class BlockImports(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == item or fullname.startswith(item + ".") for item in blocked):
                    raise AssertionError(f"forbidden registry import: {fullname}")
                return None

        sys.meta_path.insert(0, BlockImports())
        from hf_mcp.registry import build_registry
        assert len(build_registry()) == 25
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={"PYTHONPATH": str(SRC_PATH), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
