from __future__ import annotations

from .capabilities import CapabilityPolicy
from .registry import ToolSpec, build_registry, has_concrete_handler

_LOCAL_INSPECTION_TOOLS = frozenset({"formatting.preflight", "drafts.list", "drafts.read", "forums.index"})
_LOCAL_MUTATION_TOOLS = frozenset({"drafts.update", "drafts.delete"})
_REMOTE_LOCALITY = "remote"
_REMOTE_RUNTIME_TIER = 4
_LOCAL_LOCALITY = "local"
_LOCAL_INSPECTION_RUNTIME_TIER = 1
_LOCAL_MUTATION_RUNTIME_TIER = 2
_READ_OUTPUT_DEFAULT = "readable"
_WRITE_OUTPUT_DEFAULT = "structured"
_OUTPUT_READABLE = "additive"
_OUTPUT_FIELD_BUNDLES = "separate_from_rendering"


def build_tool_meta(spec: ToolSpec) -> dict[str, object]:
    output_default = _READ_OUTPUT_DEFAULT if spec.operation == "read" else _WRITE_OUTPUT_DEFAULT
    if spec.tool_name in _LOCAL_INSPECTION_TOOLS:
        locality = _LOCAL_LOCALITY
        runtime_tier = _LOCAL_INSPECTION_RUNTIME_TIER
    elif spec.tool_name in _LOCAL_MUTATION_TOOLS:
        locality = _LOCAL_LOCALITY
        runtime_tier = _LOCAL_MUTATION_RUNTIME_TIER
    else:
        locality = _REMOTE_LOCALITY
        runtime_tier = _REMOTE_RUNTIME_TIER
    return {
        "x-hf-locality": locality,
        "x-hf-runtime-tier": runtime_tier,
        "x-hf-operation": spec.operation,
        "x-hf-capability-family": spec.capability_family,
        "x-hf-coverage-family": spec.coverage_family,
        "x-hf-helper-path": spec.helper_path,
        "x-hf-transport-kind": spec.transport_kind,
        "x-hf-output-default": output_default,
        "x-hf-output-readable": _OUTPUT_READABLE,
        "x-hf-output-field-bundles": _OUTPUT_FIELD_BUNDLES,
    }


def get_tool_specs(policy: CapabilityPolicy | None = None) -> list[ToolSpec]:
    concrete_specs = [spec for spec in build_registry() if has_concrete_handler(spec.tool_name)]
    if policy is None:
        return concrete_specs

    allow_local_drafts = policy.can_register("formatting.preflight")
    return [
        spec
        for spec in concrete_specs
        if policy.can_register(spec.tool_name) or (allow_local_drafts and spec.tool_name.startswith("drafts."))
    ]


__all__ = ["build_tool_meta", "get_tool_specs"]
