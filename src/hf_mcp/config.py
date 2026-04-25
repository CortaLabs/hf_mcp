from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

from .output_modes import ReadOutputDefaults, parse_read_output_defaults

ALL_CAPABILITIES: frozenset[str] = frozenset(
    {
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
        "formatting.preflight",
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
        "contracts.write",
        "sigmarket.write",
        "admin.high_risk.write",
    }
)

ALL_PARAMETER_FAMILIES: frozenset[str] = frozenset(
    {
        "selectors.user",
        "selectors.forum",
        "selectors.thread",
        "selectors.post",
        "selectors.bytes",
        "selectors.contract",
        "selectors.dispute",
        "selectors.sigmarket",
        "filters.pagination",
        "fields.me.basic",
        "fields.me.advanced",
        "fields.users.profile",
        "fields.posts.body",
        "fields.bytes.amount",
        "formatting.content",
        "writes.content",
        "writes.bytes",
        "confirm.live",
    }
)

READ_CAPABILITIES: frozenset[str] = frozenset(
    {
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
        "formatting.preflight",
    }
)

WRITE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "threads.create",
        "posts.reply",
        "bytes.transfer",
        "bytes.deposit",
        "bytes.withdraw",
        "bytes.bump",
        "contracts.write",
        "sigmarket.write",
        "admin.high_risk.write",
    }
)

UNVERIFIED_WRITE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "contracts.write",
        "sigmarket.write",
        "admin.high_risk.write",
    }
)

VERIFIED_CONCRETE_CAPABILITIES: frozenset[str] = ALL_CAPABILITIES - UNVERIFIED_WRITE_CAPABILITIES
VERIFIED_CONCRETE_PARAMETER_FAMILIES: frozenset[str] = ALL_PARAMETER_FAMILIES

READ_PARAMETER_FAMILIES: frozenset[str] = frozenset(
    {
        "selectors.user",
        "selectors.forum",
        "selectors.thread",
        "selectors.post",
        "selectors.bytes",
        "selectors.contract",
        "selectors.dispute",
        "selectors.sigmarket",
        "filters.pagination",
        "fields.me.basic",
        "fields.me.advanced",
        "fields.users.profile",
        "fields.posts.body",
        "fields.bytes.amount",
        "formatting.content",
    }
)

FORUM_OPERATOR_CAPABILITIES: frozenset[str] = READ_CAPABILITIES | frozenset(
    {"threads.create", "posts.reply"}
)

FORUM_OPERATOR_PARAMETER_FAMILIES: frozenset[str] = READ_PARAMETER_FAMILIES | frozenset(
    {"writes.content", "confirm.live"}
)

PRESET_CAPABILITIES: dict[str, frozenset[str]] = {
    "reader": READ_CAPABILITIES,
    "forum_operator": FORUM_OPERATOR_CAPABILITIES,
    "full_api": VERIFIED_CONCRETE_CAPABILITIES,
    "custom": frozenset(),
}

PRESET_PARAMETER_FAMILIES: dict[str, frozenset[str]] = {
    "reader": READ_PARAMETER_FAMILIES,
    "forum_operator": FORUM_OPERATOR_PARAMETER_FAMILIES,
    "full_api": VERIFIED_CONCRETE_PARAMETER_FAMILIES,
    "custom": frozenset(),
}

PARAMETER_FAMILY_CAPABILITY_PARENTS: dict[str, frozenset[str]] = {
    "selectors.user": frozenset({"me.read", "users.read", "bratings.read"}),
    "selectors.forum": frozenset({"forums.read", "threads.read", "threads.create"}),
    "selectors.thread": frozenset({"threads.read", "posts.read", "posts.reply"}),
    "selectors.post": frozenset({"posts.read"}),
    "selectors.bytes": frozenset(
        {"bytes.read", "bytes.transfer", "bytes.deposit", "bytes.withdraw", "bytes.bump"}
    ),
    "selectors.contract": frozenset({"contracts.read", "contracts.write"}),
    "selectors.dispute": frozenset({"disputes.read"}),
    "selectors.sigmarket": frozenset(
        {"sigmarket.market.read", "sigmarket.order.read", "sigmarket.write"}
    ),
    "filters.pagination": READ_CAPABILITIES,
    "fields.me.basic": frozenset({"me.read"}),
    "fields.me.advanced": frozenset({"me.read"}),
    "fields.users.profile": frozenset({"users.read"}),
    "fields.posts.body": frozenset({"posts.read"}),
    "fields.bytes.amount": frozenset({"bytes.read"}),
    "formatting.content": frozenset({"formatting.preflight"}),
    "writes.content": frozenset(
        {
            "threads.create",
            "posts.reply",
            "contracts.write",
            "sigmarket.write",
            "admin.high_risk.write",
        }
    ),
    "writes.bytes": frozenset(
        {"bytes.transfer", "bytes.deposit", "bytes.withdraw", "bytes.bump"}
    ),
    "confirm.live": WRITE_CAPABILITIES,
}

DEFAULT_PROFILE = "reader"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "hf_mcp" / "config.yaml"
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "hf_mcp" / "token.json"
DEFAULT_DRAFT_DIR = Path.home() / ".config" / "hf_mcp" / "drafts"
DEFAULT_LOOPBACK_REDIRECT_URI = "http://127.0.0.1:8765/callback"
HOSTED_MODE_LOOPBACK_CALLBACK_URI = "http://127.0.0.1:8765/callback"


@dataclass(frozen=True)
class HFMCPSettings:
    profile: str
    enabled_capabilities: frozenset[str]
    enabled_parameter_families: frozenset[str]
    config_path: Path = DEFAULT_CONFIG_PATH
    env_file_path: Path | None = None
    token_path: Path = DEFAULT_TOKEN_PATH
    draft_dir: Path = DEFAULT_DRAFT_DIR
    runtime_env: Mapping[str, str] = field(default_factory=dict)
    read_output_defaults: ReadOutputDefaults = field(default_factory=ReadOutputDefaults)


def load_settings(
    config_path: Path | None,
    env: Mapping[str, str] | None = None,
) -> HFMCPSettings:
    process_env = dict(os.environ if env is None else env)
    selected_path = _resolve_config_path(config_path=config_path, env=process_env)
    raw_config = _load_yaml_config(selected_path)
    env_file_path = _resolve_env_file_path(config_path=selected_path, env=process_env)
    dotenv_values = _load_dotenv(env_file_path)
    merged_env = {**dotenv_values, **process_env}

    profile_value = raw_config.get("profile", DEFAULT_PROFILE)
    if not isinstance(profile_value, str):
        raise ValueError("`profile` must be a string.")
    profile = profile_value.strip()
    if profile not in PRESET_CAPABILITIES:
        valid = ", ".join(sorted(PRESET_CAPABILITIES))
        raise ValueError(f"Unknown profile '{profile}'. Valid profiles: {valid}.")

    enabled_capabilities = _parse_string_set(raw_config.get("enabled_capabilities"), "enabled_capabilities")
    enabled_parameter_families = _parse_string_set(
        raw_config.get("enabled_parameter_families"),
        "enabled_parameter_families",
    )
    disabled_capabilities = _parse_string_set(raw_config.get("disabled_capabilities"), "disabled_capabilities")
    disabled_parameter_families = _parse_string_set(
        raw_config.get("disabled_parameter_families"),
        "disabled_parameter_families",
    )

    _validate_known_values(enabled_capabilities | disabled_capabilities, ALL_CAPABILITIES, "capability")
    _validate_known_values(
        enabled_parameter_families | disabled_parameter_families,
        ALL_PARAMETER_FAMILIES,
        "parameter family",
    )

    resolved_capabilities = (PRESET_CAPABILITIES[profile] | enabled_capabilities) - disabled_capabilities
    resolved_parameter_families = (
        PRESET_PARAMETER_FAMILIES[profile] | enabled_parameter_families
    ) - disabled_parameter_families

    _validate_parameter_family_parents(resolved_capabilities, resolved_parameter_families)
    token_path = _resolve_token_path(raw_config.get("token_path", merged_env.get("HF_MCP_TOKEN_PATH")))
    draft_dir = _resolve_draft_dir(raw_config.get("draft_dir"), merged_env)
    read_output_defaults = parse_read_output_defaults(raw_config.get("read_output_defaults"))

    return HFMCPSettings(
        profile=profile,
        enabled_capabilities=frozenset(resolved_capabilities),
        enabled_parameter_families=frozenset(resolved_parameter_families),
        config_path=selected_path,
        env_file_path=env_file_path,
        token_path=token_path,
        draft_dir=draft_dir,
        runtime_env=dict(merged_env),
        read_output_defaults=read_output_defaults,
    )


def _resolve_config_path(config_path: Path | None, env: Mapping[str, str]) -> Path:
    if config_path is not None:
        return config_path.expanduser().resolve(strict=False)

    config_env = env.get("HF_MCP_CONFIG")
    if config_env and config_env.strip():
        return Path(config_env).expanduser().resolve(strict=False)

    return DEFAULT_CONFIG_PATH.expanduser().resolve(strict=False)


def _load_yaml_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {}

    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError("Config file must decode to a mapping.")
    return loaded


def _resolve_env_file_path(config_path: Path, env: Mapping[str, str]) -> Path | None:
    explicit_env_file = env.get("HF_MCP_ENV_FILE")
    if explicit_env_file is not None and explicit_env_file.strip():
        selected = Path(explicit_env_file).expanduser().resolve(strict=False)
        if not selected.exists():
            raise ValueError(f"HF_MCP_ENV_FILE points to a missing file: {selected}")
        return selected

    adjacent_env = config_path.with_name(".env")
    if adjacent_env.exists():
        return adjacent_env.resolve(strict=False)
    return None


def _load_dotenv(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = value
    return values


def _resolve_token_path(raw_value: object) -> Path:
    if raw_value is None:
        return DEFAULT_TOKEN_PATH.expanduser().resolve(strict=False)
    if not isinstance(raw_value, str):
        raise ValueError("`token_path` must be a string.")

    token_path = Path(raw_value).expanduser()
    if not token_path.is_absolute():
        raise ValueError("Token path must be absolute.")
    return token_path.resolve(strict=False)


def _resolve_draft_dir(raw_value: object, env: Mapping[str, str]) -> Path:
    candidate_value = raw_value
    if candidate_value is None:
        env_value = env.get("HF_MCP_DRAFT_DIR")
        if env_value is not None and env_value.strip():
            candidate_value = env_value.strip()
        else:
            candidate_value = None
    if candidate_value is None:
        return DEFAULT_DRAFT_DIR.expanduser().resolve(strict=False)
    if not isinstance(candidate_value, str):
        raise ValueError("`draft_dir` must be a string.")

    draft_dir = Path(candidate_value).expanduser()
    if not draft_dir.is_absolute():
        raise ValueError("Draft directory must be absolute.")
    return draft_dir.resolve(strict=False)


def _parse_string_set(raw_value: object, field_name: str) -> frozenset[str]:
    if raw_value is None:
        return frozenset()
    if not isinstance(raw_value, list):
        raise ValueError(f"`{field_name}` must be a list of strings.")

    parsed: set[str] = set()
    for entry in raw_value:
        if not isinstance(entry, str):
            raise ValueError(f"`{field_name}` must be a list of strings.")
        value = entry.strip()
        if not value:
            raise ValueError(f"`{field_name}` entries must not be empty.")
        parsed.add(value)
    return frozenset(parsed)


def _validate_known_values(values: frozenset[str], known_values: frozenset[str], label: str) -> None:
    unknown = values - known_values
    if unknown:
        listed = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown {label}(s): {listed}.")


def _validate_parameter_family_parents(
    capabilities: frozenset[str],
    parameter_families: frozenset[str],
) -> None:
    for family in sorted(parameter_families):
        parents = PARAMETER_FAMILY_CAPABILITY_PARENTS.get(family, frozenset())
        if not parents.intersection(capabilities):
            parent_text = ", ".join(sorted(parents))
            raise ValueError(
                "Parameter family "
                f"'{family}' requires at least one enabled capability from: {parent_text}."
            )


__all__ = [
    "ALL_CAPABILITIES",
    "ALL_PARAMETER_FAMILIES",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_DRAFT_DIR",
    "DEFAULT_LOOPBACK_REDIRECT_URI",
    "DEFAULT_PROFILE",
    "DEFAULT_TOKEN_PATH",
    "HFMCPSettings",
    "HOSTED_MODE_LOOPBACK_CALLBACK_URI",
    "PARAMETER_FAMILY_CAPABILITY_PARENTS",
    "PRESET_CAPABILITIES",
    "PRESET_PARAMETER_FAMILIES",
    "load_settings",
]
