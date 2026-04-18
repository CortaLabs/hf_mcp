from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PRODUCT_ROOT / "pyproject.toml"
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.cli import build_cli, main

_HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI = "https://cortalabs.github.io/hf_mcp/oauth_callback.html"


def _parse_hf_mcp_script_target(pyproject_text: str) -> str:
    in_scripts = False
    for raw_line in pyproject_text.splitlines():
        line = raw_line.strip()
        if line == "[project.scripts]":
            in_scripts = True
            continue
        if in_scripts and line.startswith("["):
            break
        if in_scripts and line.startswith("hf-mcp"):
            _, value = line.split("=", 1)
            return value.strip().strip('"').strip("'")
    raise AssertionError("hf-mcp script entrypoint missing from pyproject.toml")


def test_console_script_entrypoint_resolves_to_public_main() -> None:
    script_target = _parse_hf_mcp_script_target(PYPROJECT_PATH.read_text(encoding="utf-8"))
    assert script_target == "hf_mcp.cli:main"
    assert callable(main)
    assert callable(build_cli)


def test_pyproject_includes_stdio_runtime_dependency() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    dependencies: list[str] = pyproject["project"]["dependencies"]

    assert any(dependency.split(">=", 1)[0].split("==", 1)[0] == "mcp" for dependency in dependencies)


def test_python_module_entrypoint_help_runs_without_council_coupling() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_PATH)
    result = subprocess.run(
        [sys.executable, "-m", "hf_mcp", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "hf-mcp" in result.stdout
    assert "council" not in (result.stdout + result.stderr).lower()


def test_bare_command_aliases_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    def _fake_serve_stdio(*, settings: object | None = None) -> None:
        called.append(True)

    monkeypatch.setattr("hf_mcp.cli.serve_stdio", _fake_serve_stdio)
    exit_code = main([])

    assert exit_code == 0
    assert called == [True]


def test_serve_help_exists() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_PATH)
    result = subprocess.run(
        [sys.executable, "-m", "hf_mcp", "serve", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "--config" in result.stdout
    assert "--token-path" in result.stdout
    assert "--profile" in result.stdout


def test_auth_bootstrap_help_exists() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_PATH)
    result = subprocess.run(
        [sys.executable, "-m", "hf_mcp", "auth", "bootstrap", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "--config" in result.stdout
    assert "--token-path" in result.stdout
    assert "--no-browser" in result.stdout
    assert "HF_MCP_EXTERNAL_REDIRECT_URI" in result.stdout
    assert "HF_MCP_REDIRECT_URI" in result.stdout
    assert "http://127.0.0.1:8765/callback" in result.stdout
    assert "docs/oauth_callback.html" in result.stdout
    assert _HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI in result.stdout


def test_auth_status_help_exists() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_PATH)
    result = subprocess.run(
        [sys.executable, "-m", "hf_mcp", "auth", "status", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "--config" in result.stdout
    assert "--token-path" in result.stdout


def test_setup_init_help_exists() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_PATH)
    result = subprocess.run(
        [sys.executable, "-m", "hf_mcp", "setup", "init", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "--config" in result.stdout
    assert "--profile" in result.stdout
    assert "--token-path" in result.stdout
    assert "--force" in result.stdout


def test_doctor_help_exists() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_PATH)
    result = subprocess.run(
        [sys.executable, "-m", "hf_mcp", "doctor", "--help"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "--config" in result.stdout
    assert "--token-path" in result.stdout
    assert "--profile" in result.stdout
    assert "HF_MCP_EXTERNAL_REDIRECT_URI" in result.stdout
    assert "HF_MCP_REDIRECT_URI" in result.stdout
    assert "http://127.0.0.1:8765/callback" in result.stdout
    assert "docs/oauth_callback.html" in result.stdout
    assert _HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI in result.stdout


def test_serve_startup_failure_returns_clear_launch_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _raise_startup(*, settings: object | None = None) -> None:
        raise RuntimeError("Missing runtime dependency 'mcp'.")

    monkeypatch.setattr("hf_mcp.cli.serve_stdio", _raise_startup)
    exit_code = main(["serve"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Launch error: Missing runtime dependency 'mcp'" in captured.err
    assert "council" not in captured.err.lower()
