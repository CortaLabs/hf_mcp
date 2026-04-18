from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import yaml

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from hf_mcp.onboarding import run_doctor, run_setup_init

_HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI = "https://cortalabs.github.io/hf_mcp/oauth_callback.html"


def _load_yaml(path: Path) -> dict[str, object]:
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    return content if isinstance(content, dict) else {}


def test_setup_init_writes_reader_first_yaml_and_next_steps(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"

    exit_code = run_setup_init(config_path=config_path, token_path=None, profile="reader")
    out = capsys.readouterr().out

    assert exit_code == 0
    assert config_path.exists()
    assert _load_yaml(config_path) == {"profile": "reader"}
    assert "HF_MCP_CLIENT_ID" in out
    assert "HF_MCP_CLIENT_SECRET" in out
    assert "HF_MCP_EXTERNAL_REDIRECT_URI" in out
    assert "HF_MCP_REDIRECT_URI" in out
    assert "http://127.0.0.1:8765/callback" in out
    assert "docs/oauth_callback.html" in out
    assert _HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI in out
    assert "hf-mcp auth bootstrap" in out
    assert "hf-mcp doctor" in out
    assert "hf-mcp serve" in out


def test_setup_init_respects_force_before_overwrite(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("profile: full_api\n", encoding="utf-8")

    exit_code = run_setup_init(config_path=config_path, token_path=None, profile="reader", force=False)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Config already exists" in out
    assert "Use --force to overwrite it." in out
    assert _load_yaml(config_path) == {"profile": "full_api"}


def test_setup_init_force_overwrites_and_persists_token_path(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    token_path = (tmp_path / "tokens" / "token.json").resolve()
    config_path.write_text("profile: full_api\n", encoding="utf-8")

    exit_code = run_setup_init(
        config_path=config_path,
        token_path=token_path,
        profile="reader",
        force=True,
    )

    assert exit_code == 0
    assert _load_yaml(config_path) == {"profile": "reader", "token_path": str(token_path)}
    assert "HF_MCP_CLIENT_ID" not in config_path.read_text(encoding="utf-8")
    assert "HF_MCP_CLIENT_SECRET" not in config_path.read_text(encoding="utf-8")


def test_doctor_reports_missing_config_secrets_and_token(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = tmp_path / "missing-config.yaml"
    token_path = (tmp_path / "token.json").resolve()
    monkeypatch.delenv("HF_MCP_CLIENT_ID", raising=False)
    monkeypatch.delenv("HF_MCP_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("HF_MCP_CONFIG", raising=False)

    exit_code = run_doctor(config_path=config_path, token_path=token_path, profile=None)
    out = capsys.readouterr().out

    assert exit_code == 2
    assert f"Config path: {config_path.resolve(strict=False)}" in out
    assert "Config file: missing" in out
    assert "HF_MCP_CLIENT_ID: missing" in out
    assert "HF_MCP_CLIENT_SECRET: missing" in out
    assert "Token file: missing" in out
    assert "Ready to serve: no" in out
    assert "HF_MCP_EXTERNAL_REDIRECT_URI" in out
    assert "HF_MCP_REDIRECT_URI" in out
    assert "http://127.0.0.1:8765/callback" in out
    assert "docs/oauth_callback.html" in out
    assert _HOSTED_EXTERNAL_REDIRECT_EXAMPLE_URI in out


def test_doctor_reports_ready_to_serve_with_local_state(tmp_path: Path, monkeypatch, capsys) -> None:
    config_path = (tmp_path / "config.yaml").resolve()
    token_path = (tmp_path / "token.json").resolve()
    run_setup_init(config_path=config_path, token_path=token_path, profile="reader", force=False)
    capsys.readouterr()

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(
        json.dumps(
            {
                "access_token": "token",
                "token_type": "Bearer",
                "scope": ["posts.read", "threads.read"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    token_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    monkeypatch.setenv("HF_MCP_CLIENT_ID", "client")
    monkeypatch.setenv("HF_MCP_CLIENT_SECRET", "secret")

    exit_code = run_doctor(config_path=config_path, token_path=token_path, profile=None)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Config file: present" in out
    assert "HF_MCP_CLIENT_ID: set" in out
    assert "HF_MCP_CLIENT_SECRET: set" in out
    assert "Token file: present" in out
    assert "Granted scopes: posts.read threads.read" in out
    assert "Ready to serve: yes" in out


def test_doctor_profile_override_is_validated(tmp_path: Path, capsys) -> None:
    config_path = (tmp_path / "config.yaml").resolve()
    run_setup_init(config_path=config_path, token_path=None, profile="reader", force=False)
    capsys.readouterr()

    exit_code = run_doctor(config_path=config_path, token_path=None, profile="not-a-profile")
    out = capsys.readouterr().out

    assert exit_code == 2
    assert "Unknown profile 'not-a-profile'" in out
    assert "Ready to serve: no" in out
