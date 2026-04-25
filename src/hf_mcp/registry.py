from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from .capabilities import CAPABILITY_PARAMETER_FAMILIES

Operation = Literal["read", "write"]
TransportKind = Literal["generic", "helper"]

_MCP_TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_name: str
    coverage_family: str
    capability_family: str
    operation: Operation
    helper_path: str | None
    transport_kind: TransportKind
    parameter_families: tuple[str, ...]

    @property
    def name(self) -> str:
        return self.tool_name


@dataclass(frozen=True, slots=True)
class _MatrixRow:
    tool_name: str
    coverage_family: str
    capability_family: str
    operation: Operation
    helper_path: str | None
    transport_kind: TransportKind
    parameter_families: tuple[str, ...] | None = None


_EXPECTED_COVERAGE_FAMILIES = frozenset(
    {
        "me.read",
        "users.read",
        "forums.index",
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
        "formatting.preflight",
        "drafts.list",
        "drafts.read",
        "drafts.update",
        "drafts.delete",
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
    }
)

_PLACEHOLDER_ONLY_TOOLS: frozenset[str] = frozenset()

_MATRIX_ROWS: tuple[_MatrixRow, ...] = (
    _MatrixRow(
        tool_name="me.read",
        coverage_family="me.read",
        capability_family="me.read",
        operation="read",
        helper_path="me",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="users.read",
        coverage_family="users.read",
        capability_family="users.read",
        operation="read",
        helper_path="users",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="forums.index",
        coverage_family="forums.index",
        capability_family="forums.read",
        operation="read",
        helper_path=None,
        transport_kind="generic",
        parameter_families=(),
    ),
    _MatrixRow(
        tool_name="forums.read",
        coverage_family="forums.read",
        capability_family="forums.read",
        operation="read",
        helper_path="forums",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="threads.read",
        coverage_family="threads.read",
        capability_family="threads.read",
        operation="read",
        helper_path="threads",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="posts.read",
        coverage_family="posts.read",
        capability_family="posts.read",
        operation="read",
        helper_path="posts",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="bytes.read",
        coverage_family="bytes.read",
        capability_family="bytes.read",
        operation="read",
        helper_path="bytes",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="contracts.read",
        coverage_family="contracts.read",
        capability_family="contracts.read",
        operation="read",
        helper_path="contracts",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="disputes.read",
        coverage_family="disputes.read",
        capability_family="disputes.read",
        operation="read",
        helper_path="disputes",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="bratings.read",
        coverage_family="bratings.read",
        capability_family="bratings.read",
        operation="read",
        helper_path="bratings",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="sigmarket.market.read",
        coverage_family="sigmarket.market.read",
        capability_family="sigmarket.market.read",
        operation="read",
        helper_path="sigmarket/market",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="sigmarket.order.read",
        coverage_family="sigmarket.order.read",
        capability_family="sigmarket.order.read",
        operation="read",
        helper_path="sigmarket/order",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="admin.high_risk.read",
        coverage_family="admin.high_risk.read",
        capability_family="admin.high_risk.read",
        operation="read",
        helper_path="admin/high-risk/read",
        transport_kind="helper",
        parameter_families=("filters.pagination",),
    ),
    _MatrixRow(
        tool_name="formatting.preflight",
        coverage_family="formatting.preflight",
        capability_family="formatting.preflight",
        operation="read",
        helper_path=None,
        transport_kind="generic",
        parameter_families=("formatting.content",),
    ),
    _MatrixRow(
        tool_name="drafts.list",
        coverage_family="drafts.list",
        capability_family="formatting.preflight",
        operation="read",
        helper_path=None,
        transport_kind="generic",
        parameter_families=("drafts.filters",),
    ),
    _MatrixRow(
        tool_name="drafts.read",
        coverage_family="drafts.read",
        capability_family="formatting.preflight",
        operation="read",
        helper_path=None,
        transport_kind="generic",
        parameter_families=("drafts.selector",),
    ),
    _MatrixRow(
        tool_name="drafts.update",
        coverage_family="drafts.update",
        capability_family="formatting.preflight",
        operation="write",
        helper_path=None,
        transport_kind="generic",
        parameter_families=("drafts.selector", "drafts.metadata"),
    ),
    _MatrixRow(
        tool_name="drafts.delete",
        coverage_family="drafts.delete",
        capability_family="formatting.preflight",
        operation="write",
        helper_path=None,
        transport_kind="generic",
        parameter_families=("drafts.selector", "drafts.confirm_delete"),
    ),
    _MatrixRow(
        tool_name="threads.create",
        coverage_family="threads.create",
        capability_family="threads.create",
        operation="write",
        helper_path="threads",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="posts.reply",
        coverage_family="posts.reply",
        capability_family="posts.reply",
        operation="write",
        helper_path="posts",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="bytes.transfer",
        coverage_family="bytes.transfer",
        capability_family="bytes.transfer",
        operation="write",
        helper_path="bytes",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="bytes.deposit",
        coverage_family="bytes.deposit",
        capability_family="bytes.deposit",
        operation="write",
        helper_path="bytes/deposit",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="bytes.withdraw",
        coverage_family="bytes.withdraw",
        capability_family="bytes.withdraw",
        operation="write",
        helper_path="bytes/withdraw",
        transport_kind="helper",
    ),
    _MatrixRow(
        tool_name="bytes.bump",
        coverage_family="bytes.bump",
        capability_family="bytes.bump",
        operation="write",
        helper_path="bytes/bump",
        transport_kind="helper",
    ),
)


def _resolve_parameter_families(row: _MatrixRow) -> tuple[str, ...]:
    if row.parameter_families is not None:
        return tuple(dict.fromkeys(row.parameter_families))
    return tuple(sorted(CAPABILITY_PARAMETER_FAMILIES.get(row.capability_family, frozenset())))


def _build_tool_spec(row: _MatrixRow) -> ToolSpec:
    return ToolSpec(
        tool_name=row.tool_name,
        coverage_family=row.coverage_family,
        capability_family=row.capability_family,
        operation=row.operation,
        helper_path=row.helper_path,
        transport_kind=row.transport_kind,
        parameter_families=_resolve_parameter_families(row),
    )


def has_concrete_handler(tool_name: str) -> bool:
    return tool_name not in _PLACEHOLDER_ONLY_TOOLS


def mcp_tool_name(canonical_tool_name: str) -> str:
    """Return the public MCP-safe tool name for a canonical HF tool id."""
    public_name = canonical_tool_name.replace(".", "_")
    if not _MCP_TOOL_NAME_PATTERN.fullmatch(public_name):
        raise ValueError(
            f"Canonical tool '{canonical_tool_name}' maps to invalid MCP tool name '{public_name}'."
        )
    return public_name


def _validate_registry(specs: list[ToolSpec]) -> None:
    tool_names = [spec.tool_name for spec in specs]
    duplicate_tool_names = sorted(name for name in set(tool_names) if tool_names.count(name) > 1)
    if duplicate_tool_names:
        dupes = ", ".join(duplicate_tool_names)
        raise ValueError(f"Duplicate tool_name entries in registry: {dupes}")

    public_tool_names = [mcp_tool_name(spec.tool_name) for spec in specs]
    duplicate_public_tool_names = sorted(
        name for name in set(public_tool_names) if public_tool_names.count(name) > 1
    )
    if duplicate_public_tool_names:
        dupes = ", ".join(duplicate_public_tool_names)
        raise ValueError(f"Duplicate MCP tool name entries in registry: {dupes}")

    coverage_families = [spec.coverage_family for spec in specs]
    duplicate_coverage_families = sorted(
        family for family in set(coverage_families) if coverage_families.count(family) > 1
    )
    if duplicate_coverage_families:
        dupes = ", ".join(duplicate_coverage_families)
        raise ValueError(f"Duplicate coverage_family entries in registry: {dupes}")

    actual = set(coverage_families)
    missing = sorted(_EXPECTED_COVERAGE_FAMILIES - actual)
    extras = sorted(actual - _EXPECTED_COVERAGE_FAMILIES)
    if missing or extras:
        details: list[str] = []
        if missing:
            details.append(f"Missing documented coverage families: {', '.join(missing)}")
        if extras:
            details.append(f"Unexpected coverage families: {', '.join(extras)}")
        raise ValueError("; ".join(details))


def build_registry() -> list[ToolSpec]:
    specs = [_build_tool_spec(row) for row in _MATRIX_ROWS]
    _validate_registry(specs)
    return specs


def get_tool_spec(tool_name: str) -> ToolSpec:
    for spec in build_registry():
        if spec.tool_name == tool_name:
            return spec
    raise KeyError(f"Unknown tool '{tool_name}'.")


def get_core_read_specs() -> tuple[ToolSpec, ...]:
    core_families = {"me.read", "users.read", "forums.read", "threads.read", "posts.read"}
    return tuple(spec for spec in build_registry() if spec.coverage_family in core_families)


def get_extended_read_specs() -> tuple[ToolSpec, ...]:
    extended_families = {
        "bytes.read",
        "contracts.read",
        "disputes.read",
        "bratings.read",
        "sigmarket.market.read",
        "sigmarket.order.read",
        "admin.high_risk.read",
    }
    return tuple(spec for spec in build_registry() if spec.coverage_family in extended_families)


def get_local_formatting_specs() -> tuple[ToolSpec, ...]:
    local_families = {"formatting.preflight", "drafts.list", "drafts.read", "drafts.update", "drafts.delete"}
    return tuple(spec for spec in build_registry() if spec.coverage_family in local_families)


def get_documented_write_specs() -> tuple[ToolSpec, ...]:
    write_families = {
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
    }
    return tuple(
        spec
        for spec in build_registry()
        if spec.coverage_family in write_families and has_concrete_handler(spec.tool_name)
    )


__all__ = [
    "ToolSpec",
    "build_registry",
    "get_documented_write_specs",
    "get_tool_spec",
    "get_core_read_specs",
    "get_extended_read_specs",
    "has_concrete_handler",
    "get_local_formatting_specs",
    "mcp_tool_name",
]
