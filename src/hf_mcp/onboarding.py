from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

import yaml

from .config import (
    DEFAULT_CONFIG_PATH,
    HFMCPSettings,
    PRESET_CAPABILITIES,
    PRESET_PARAMETER_FAMILIES,
    load_settings,
)
from .token_store import TokenBundle, TokenStore, load_token_store

_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/callback"


def run_setup_init(
    config_path: Path | None,
    token_path: Path | None,
    profile: str,
    force: bool = False,
) -> int:
    selected_config_path = _resolve_config_path(config_path)
    selected_profile = _validate_profile(profile)
    selected_token_path = _normalize_token_path(token_path) if token_path is not None else None

    if selected_config_path.exists() and not force:
        print(f"Config already exists: {selected_config_path}")
        print("Use --force to overwrite it.")
        _print_next_steps(config_path=selected_config_path, token_path=selected_token_path)
        return 0

    payload: dict[str, object] = {"profile": selected_profile}
    if selected_token_path is not None:
        payload["token_path"] = str(selected_token_path)

    selected_config_path.parent.mkdir(parents=True, exist_ok=True)
    with selected_config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, default_flow_style=False, sort_keys=True)

    print(f"Config written: {selected_config_path}")
    print(f"Profile: {selected_profile}")
    if selected_token_path is not None:
        print(f"Token path persisted: {selected_token_path}")
    _print_next_steps(config_path=selected_config_path, token_path=selected_token_path)
    return 0


def run_doctor(config_path: Path | None, token_path: Path | None, profile: str | None = None) -> int:
    selected_config_path = _resolve_config_path(config_path)
    env_override: Mapping[str, str] | None = None
    issues: list[str] = []
    selected_token_path = token_path

    if token_path is not None:
        try:
            selected_token_path = _normalize_token_path(token_path)
            env_override = _build_env_override(selected_token_path)
        except ValueError as exc:
            issues.append(str(exc))
            selected_token_path = token_path

    settings: HFMCPSettings | None = None
    store: TokenStore | None = None
    bundle: TokenBundle | None = None
    token_status = "not checked"
    granted_scopes = "(none)"

    try:
        settings = load_settings(config_path=config_path, env=env_override)
        settings = _apply_profile_override(settings, profile)
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        issues.append(f"Config resolution failed: {exc}")

    config_present = selected_config_path.exists()
    if not config_present:
        issues.append(f"Missing config file: {selected_config_path}")

    client_id_status = "missing"
    client_secret_status = "missing"
    if settings is not None:
        client_id_status = _env_status(settings.runtime_env.get("HF_MCP_CLIENT_ID"))
        client_secret_status = _env_status(settings.runtime_env.get("HF_MCP_CLIENT_SECRET"))
        if client_id_status == "missing":
            issues.append("Missing required environment variable: HF_MCP_CLIENT_ID")
        if client_secret_status == "missing":
            issues.append("Missing required environment variable: HF_MCP_CLIENT_SECRET")

        try:
            store = load_token_store(settings)
            bundle = store.load_bundle()
            if bundle is None:
                token_status = "missing"
                issues.append(f"Missing token file content at: {store.path}")
            else:
                token_status = "present"
                granted_scopes = _format_scopes(bundle)
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            token_status = "invalid"
            issues.append(f"Token state invalid: {exc}")

    effective_profile = profile.strip() if profile is not None else (settings.profile if settings is not None else "(unknown)")
    effective_token_path = store.path if store is not None else (selected_token_path if selected_token_path is not None else "(unresolved)")

    print("hf-mcp doctor (local-only)")
    print(f"Config path: {selected_config_path}")
    print(f"Config file: {'present' if config_present else 'missing'}")
    print(f"Profile: {effective_profile}")
    print(f"HF_MCP_CLIENT_ID: {client_id_status}")
    print(f"HF_MCP_CLIENT_SECRET: {client_secret_status}")
    print(f"Token path: {effective_token_path}")
    print(f"Token file: {token_status}")
    print(f"Granted scopes: {granted_scopes}")

    if issues:
        print("Ready to serve: no")
        print("Missing or invalid prerequisites:")
        for issue in issues:
            print(f"- {issue}")
        print("Next steps:")
        print(f"- Run: {_command_with_paths('hf-mcp setup init', selected_config_path, selected_token_path)}")
        print("- Set: HF_MCP_CLIENT_ID")
        print("- Set: HF_MCP_CLIENT_SECRET")
        print(f"- Run: {_command_with_paths('hf-mcp auth bootstrap', selected_config_path, selected_token_path)}")
        print(f"- Re-run: {_command_with_paths('hf-mcp doctor', selected_config_path, selected_token_path)}")
        return 2

    print("Ready to serve: yes")
    print(f"Run: {_command_with_paths('hf-mcp serve', selected_config_path, selected_token_path)}")
    return 0


def _resolve_config_path(config_path: Path | None) -> Path:
    if config_path is not None:
        return config_path.expanduser().resolve(strict=False)

    config_env = os.environ.get("HF_MCP_CONFIG")
    if config_env and config_env.strip():
        return Path(config_env).expanduser().resolve(strict=False)
    return DEFAULT_CONFIG_PATH.expanduser().resolve(strict=False)


def _validate_profile(profile: str) -> str:
    normalized = profile.strip()
    if normalized not in PRESET_CAPABILITIES:
        valid = ", ".join(sorted(PRESET_CAPABILITIES))
        raise ValueError(f"Unknown profile '{normalized}'. Valid profiles: {valid}.")
    return normalized


def _normalize_token_path(token_path: Path) -> Path:
    selected_token_path = token_path.expanduser()
    if not selected_token_path.is_absolute():
        raise ValueError("--token-path must be an absolute path.")
    return selected_token_path.resolve(strict=False)


def _build_env_override(token_path: Path) -> Mapping[str, str]:
    env_override = dict(os.environ)
    env_override["HF_MCP_TOKEN_PATH"] = str(token_path)
    return env_override


def _apply_profile_override(settings: HFMCPSettings, profile: str | None) -> HFMCPSettings:
    if profile is None:
        return settings

    selected_profile = _validate_profile(profile)
    return HFMCPSettings(
        profile=selected_profile,
        enabled_capabilities=PRESET_CAPABILITIES[selected_profile],
        enabled_parameter_families=PRESET_PARAMETER_FAMILIES[selected_profile],
        config_path=settings.config_path,
        env_file_path=settings.env_file_path,
        token_path=settings.token_path,
        runtime_env=settings.runtime_env,
    )


def _format_scopes(bundle: TokenBundle | None) -> str:
    if bundle is None or not bundle.scope:
        return "(none)"
    return " ".join(sorted(bundle.scope))


def _env_status(value: str | None) -> str:
    if value is None:
        return "missing"
    if not value.strip():
        return "missing"
    return "set"


def _print_next_steps(config_path: Path, token_path: Path | None) -> None:
    print("Next steps:")
    print("- Create or update your Hack Forums developer app.")
    print(f"- Set the redirect URI to: {_DEFAULT_REDIRECT_URI}")
    print("- Set required environment variables:")
    print("  HF_MCP_CLIENT_ID=your_client_id")
    print("  HF_MCP_CLIENT_SECRET=your_client_secret")
    print(f"- Run: {_command_with_paths('hf-mcp auth bootstrap', config_path, token_path)}")
    print(f"- Run: {_command_with_paths('hf-mcp doctor', config_path, token_path)}")
    print(f"- Run: {_command_with_paths('hf-mcp serve', config_path, token_path)}")


def _command_with_paths(base: str, config_path: Path, token_path: Path | None) -> str:
    parts = [base]
    if config_path != DEFAULT_CONFIG_PATH.expanduser().resolve(strict=False):
        parts.extend(["--config", str(config_path)])
    if token_path is not None:
        parts.extend(["--token-path", str(token_path)])
    return " ".join(parts)


__all__ = ["run_setup_init", "run_doctor"]
