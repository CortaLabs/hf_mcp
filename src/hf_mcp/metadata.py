from __future__ import annotations

from .capabilities import CapabilityPolicy
from .registry import ToolSpec, build_registry

_REMOTE_LOCALITY = "remote"
_REMOTE_RUNTIME_TIER = 4


def build_tool_meta(spec: ToolSpec) -> dict[str, object]:
    return {
        "x-hf-locality": _REMOTE_LOCALITY,
        "x-hf-runtime-tier": _REMOTE_RUNTIME_TIER,
        "x-hf-operation": spec.operation,
        "x-hf-capability-family": spec.capability_family,
        "x-hf-coverage-family": spec.coverage_family,
        "x-hf-helper-path": spec.helper_path,
        "x-hf-transport-kind": spec.transport_kind,
    }


def get_tool_specs(policy: CapabilityPolicy) -> list[ToolSpec]:
    return [spec for spec in build_registry() if policy.can_register(spec.tool_name)]


__all__ = ["build_tool_meta", "get_tool_specs"]
