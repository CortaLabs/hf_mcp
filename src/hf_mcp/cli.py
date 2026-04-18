from __future__ import annotations

import os
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from typing import Any, Mapping, Sequence

from .auth import authorize_via_loopback
from .config import HFMCPSettings, PRESET_CAPABILITIES, PRESET_PARAMETER_FAMILIES, load_settings
from .onboarding import (
    _HOSTED_CALLBACK_ARTIFACT_PATH,
    _HOSTED_EXTERNAL_REDIRECT_ENV,
    _HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI,
    _HOSTED_LOCAL_CALLBACK_URI,
    _LEGACY_REDIRECT_ENV,
    run_doctor,
    run_setup_init,
)
from .server import serve_stdio
from .token_store import TokenBundle, TokenStore, load_token_store


def build_cli() -> Any:
    parser = ArgumentParser(
        prog="hf-mcp",
        description="Standalone Hack Forums MCP launch surface",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="hf-mcp 0.1.1",
    )
    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser("serve", help="Start the MCP runtime")
    serve_parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    serve_parser.add_argument("--token-path", type=Path, default=None, help="Absolute path for token JSON")
    serve_parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Optional profile override (reader, forum_operator, full_api, custom)",
    )

    auth_parser = subparsers.add_parser("auth", help="Bootstrap and inspect auth state")
    auth_subparsers = auth_parser.add_subparsers(dest="auth_command")

    bootstrap_parser = auth_subparsers.add_parser(
        "bootstrap",
        help="Run OAuth bootstrap (hosted callback + loopback fallback)",
        description=(
            "Run OAuth bootstrap.\n\n"
            f"Hosted mode: set {_HOSTED_EXTERNAL_REDIRECT_ENV} to your hosted callback page URL "
            f"(artifact path: {_HOSTED_CALLBACK_ARTIFACT_PATH}; example: {_HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI}). "
            f"The hosted page forwards to the fixed local callback target {_HOSTED_LOCAL_CALLBACK_URI}.\n"
            f"Legacy fallback: if {_HOSTED_EXTERNAL_REDIRECT_ENV} is unset, {_LEGACY_REDIRECT_ENV} "
            "keeps loopback-only bootstrap."
        ),
    )
    bootstrap_parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    bootstrap_parser.add_argument("--token-path", type=Path, default=None, help="Absolute path for token JSON")
    bootstrap_parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")

    status_parser = auth_subparsers.add_parser("status", help="Show local token/config status")
    status_parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    status_parser.add_argument("--token-path", type=Path, default=None, help="Absolute path for token JSON")

    setup_parser = subparsers.add_parser("setup", help="First-run local setup helpers")
    setup_subparsers = setup_parser.add_subparsers(dest="setup_command")
    setup_init_parser = setup_subparsers.add_parser("init", help="Create first-run config and print next steps")
    setup_init_parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    setup_init_parser.add_argument("--profile", type=str, default="reader", help="Profile to write into config")
    setup_init_parser.add_argument("--token-path", type=Path, default=None, help="Absolute token path to persist")
    setup_init_parser.add_argument("--force", action="store_true", help="Overwrite existing config file")

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check local onboarding readiness without network calls",
        description=(
            "Check local onboarding readiness without network calls.\n\n"
            f"Hosted callback guidance: {_HOSTED_CALLBACK_ARTIFACT_PATH}, "
            f"{_HOSTED_EXTERNAL_REDIRECT_ENV}, fixed local target {_HOSTED_LOCAL_CALLBACK_URI}, "
            f"example {_HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI}, "
            f"and legacy {_LEGACY_REDIRECT_ENV} fallback."
        ),
    )
    doctor_parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    doctor_parser.add_argument("--token-path", type=Path, default=None, help="Absolute path for token JSON")
    doctor_parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Optional profile override for serve-equivalent local checks",
    )

    parser.set_defaults(command="serve", config=None, token_path=None, profile=None)
    return parser


def _resolve_settings_and_store(config_path: Path | None, token_path: Path | None) -> tuple[HFMCPSettings, TokenStore]:
    env_override: Mapping[str, str] | None = None
    if token_path is not None:
        selected_token_path = token_path.expanduser()
        env_override = dict(os.environ)
        env_override["HF_MCP_TOKEN_PATH"] = str(selected_token_path)

    settings = load_settings(config_path=config_path, env=env_override)
    store = load_token_store(settings)
    return settings, store


def _run_auth_bootstrap(args: Namespace) -> int:
    try:
        settings, store = _resolve_settings_and_store(config_path=args.config, token_path=args.token_path)
        bundle = authorize_via_loopback(settings=settings, open_browser=not args.no_browser)
        store.save_bundle(bundle)
    except (OSError, RuntimeError, TimeoutError, ValueError, PermissionError) as exc:
        print(f"Auth bootstrap failed: {exc}", file=sys.stderr)
        return 2

    print(f"Config path: {settings.config_path}")
    print(f"Token path: {store.path}")
    print("Token saved: yes")
    print(f"Granted scopes: {_format_scopes(bundle)}")
    return 0


def _run_auth_status(args: Namespace) -> int:
    try:
        settings, store = _resolve_settings_and_store(config_path=args.config, token_path=args.token_path)
        bundle = store.load_bundle()
    except (OSError, RuntimeError, ValueError, PermissionError) as exc:
        print(f"Auth status failed: {exc}", file=sys.stderr)
        return 2

    print(f"Config path: {settings.config_path}")
    print(f"Token path: {store.path}")
    print(f"Token present: {'yes' if bundle is not None else 'no'}")
    print(f"Granted scopes: {_format_scopes(bundle)}")
    return 0


def _format_scopes(bundle: TokenBundle | None) -> str:
    if bundle is None or not bundle.scope:
        return "(none)"
    return " ".join(sorted(bundle.scope))


def _resolve_serve_settings(args: Namespace) -> HFMCPSettings:
    env_override: Mapping[str, str] | None = None
    if args.token_path is not None:
        selected_token_path = args.token_path.expanduser()
        env_override = dict(os.environ)
        env_override["HF_MCP_TOKEN_PATH"] = str(selected_token_path)

    settings = load_settings(config_path=args.config, env=env_override)
    if args.profile is None:
        return settings

    profile = args.profile.strip()
    if profile not in PRESET_CAPABILITIES:
        valid = ", ".join(sorted(PRESET_CAPABILITIES))
        raise ValueError(f"Unknown profile '{profile}'. Valid profiles: {valid}.")

    return HFMCPSettings(
        profile=profile,
        enabled_capabilities=PRESET_CAPABILITIES[profile],
        enabled_parameter_families=PRESET_PARAMETER_FAMILIES[profile],
        config_path=settings.config_path,
        env_file_path=settings.env_file_path,
        token_path=settings.token_path,
        runtime_env=settings.runtime_env,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_cli()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "serve":
        try:
            serve_stdio(settings=_resolve_serve_settings(args))
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            print(f"Launch error: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "auth":
        if args.auth_command == "bootstrap":
            return _run_auth_bootstrap(args)
        if args.auth_command == "status":
            return _run_auth_status(args)
        parser.error("auth command requires a subcommand: bootstrap or status")

    if args.command == "setup":
        if args.setup_command == "init":
            try:
                return run_setup_init(
                    config_path=args.config,
                    token_path=args.token_path,
                    profile=args.profile,
                    force=args.force,
                )
            except (OSError, RuntimeError, ValueError, PermissionError) as exc:
                print(f"Setup init failed: {exc}", file=sys.stderr)
                return 2
        parser.error("setup command requires a subcommand: init")

    if args.command == "doctor":
        try:
            return run_doctor(
                config_path=args.config,
                token_path=args.token_path,
                profile=args.profile,
            )
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            print(f"Doctor failed: {exc}", file=sys.stderr)
            return 2

    return 0
