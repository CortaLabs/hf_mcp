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
from hf_mcp.registry import build_registry, get_tool_spec
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

    assert len(specs) == len(registry_module._EXPECTED_COVERAGE_FAMILIES)
    assert {spec.coverage_family for spec in specs} == registry_module._EXPECTED_COVERAGE_FAMILIES
    assert len({spec.tool_name for spec in specs}) == len(specs)
    assert any(spec.transport_kind == "generic" for spec in specs)
    assert any(spec.transport_kind == "helper" for spec in specs)


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

    assert set(schema["properties"]) == {"tid"}
    assert schema["required"] == ["tid"]
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
            if row.coverage_family != "contracts.write"
        ),
    )

    with pytest.raises(ValueError, match="Missing documented coverage families: contracts.write"):
        build_registry()
