from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import hf_mcp.config as runtime_config
from hf_mcp.config import DEFAULT_CONFIG_PATH, DEFAULT_TOKEN_PATH, load_settings
from hf_mcp.token_store import load_token_store


def _write_yaml(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")


def test_resolution_prefers_explicit_config_path_over_environment(tmp_path: Path) -> None:
    explicit_path = tmp_path / "explicit.yaml"
    env_path = tmp_path / "env.yaml"
    _write_yaml(explicit_path, {"profile": "reader"})
    _write_yaml(env_path, {"profile": "forum_operator"})

    settings = load_settings(config_path=explicit_path, env={"HF_MCP_CONFIG": str(env_path)})

    assert settings.profile == "reader"
    assert settings.config_path == explicit_path.resolve(strict=False)


def test_resolution_uses_hf_mcp_config_when_cli_path_not_provided(tmp_path: Path) -> None:
    env_path = tmp_path / "env.yaml"
    _write_yaml(env_path, {"profile": "reader"})

    settings = load_settings(config_path=None, env={"HF_MCP_CONFIG": str(env_path)})

    assert settings.profile == "reader"
    assert settings.config_path == env_path.resolve(strict=False)


def test_default_path_and_adjacent_env_load_with_process_env_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".config" / "hf_mcp" / "config.yaml"
    _write_yaml(config_path, {"profile": "full_api"})
    adjacent_env = config_path.with_name(".env")
    adjacent_env.write_text(
        "HF_MCP_PROFILE=reader\nHF_MCP_TOKEN_PATH=/tmp/from-dotenv-token.json\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(runtime_config, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setenv("HF_MCP_PROFILE", "forum_operator")
    monkeypatch.setenv("HF_MCP_TOKEN_PATH", "/tmp/from-process-env-token.json")

    settings = load_settings(config_path=None)

    assert settings.config_path == config_path.resolve(strict=False)
    assert settings.env_file_path == adjacent_env.resolve(strict=False)
    assert settings.profile == "full_api"
    assert settings.token_path == Path("/tmp/from-process-env-token.json")


def test_default_path_used_when_config_missing_and_adjacent_env_missing_is_acceptable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = (tmp_path / ".config" / "hf_mcp" / "config.yaml").resolve(strict=False)
    monkeypatch.setattr(runtime_config, "DEFAULT_CONFIG_PATH", expected)
    monkeypatch.delenv("HF_MCP_CONFIG", raising=False)
    monkeypatch.delenv("HF_MCP_ENV_FILE", raising=False)

    settings = load_settings(config_path=None, env={})

    assert settings.config_path == expected
    assert settings.env_file_path is None


def test_explicit_env_file_is_loaded_when_set(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    env_file = tmp_path / "custom.env"
    _write_yaml(config_path, {"profile": "full_api"})
    env_file.write_text("HF_MCP_TOKEN_PATH=/tmp/token-from-dotenv.json\n", encoding="utf-8")

    settings = load_settings(
        config_path=config_path,
        env={"HF_MCP_ENV_FILE": str(env_file)},
    )

    assert settings.profile == "full_api"
    assert settings.token_path == Path("/tmp/token-from-dotenv.json")
    assert settings.env_file_path == env_file.resolve(strict=False)


def test_profile_from_dotenv_is_ignored_when_yaml_omits_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    env_file = tmp_path / "custom.env"
    _write_yaml(config_path, {})
    env_file.write_text("HF_MCP_PROFILE=reader\n", encoding="utf-8")

    settings = load_settings(
        config_path=config_path,
        env={"HF_MCP_ENV_FILE": str(env_file)},
    )

    assert settings.profile == "reader"


def test_profile_from_process_env_is_ignored_when_yaml_omits_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_yaml(config_path, {})

    settings = load_settings(
        config_path=config_path,
        env={"HF_MCP_PROFILE": "reader"},
    )

    assert settings.profile == "reader"


def test_explicit_missing_env_file_fails_closed(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_yaml(config_path, {"profile": "full_api"})

    with pytest.raises(ValueError, match="HF_MCP_ENV_FILE points to a missing file"):
        load_settings(
            config_path=config_path,
            env={"HF_MCP_ENV_FILE": str(tmp_path / "missing.env")},
        )


def test_token_path_from_yaml_must_be_absolute(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    _write_yaml(config_path, {"profile": "full_api", "token_path": "relative-token.json"})

    with pytest.raises(ValueError, match="Token path must be absolute"):
        load_settings(config_path=config_path, env={})


def test_load_token_store_accepts_canonical_user_path_independent_of_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.chdir(home_dir)
    config_path = tmp_path / "config.yaml"
    _write_yaml(config_path, {"profile": "reader"})

    expected = (home_dir / ".config" / "hf_mcp" / "token.json").resolve(strict=False)
    settings = load_settings(config_path=config_path, env={"HF_MCP_TOKEN_PATH": "~/.config/hf_mcp/token.json"})
    store = load_token_store(settings)

    assert settings.token_path == expected
    assert store.path == expected


def test_load_token_store_rejects_repo_internal_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    isolated_cwd = tmp_path / "outside-cwd"
    isolated_cwd.mkdir(parents=True)
    monkeypatch.chdir(isolated_cwd)
    repo_internal = PRODUCT_ROOT / "token.json"
    settings = load_settings(
        config_path=None,
        env={"HF_MCP_TOKEN_PATH": str(repo_internal.resolve(strict=False))},
    )

    with pytest.raises(ValueError, match="inside the tracked repository tree"):
        load_token_store(settings)


def test_missing_required_secret_not_synthesized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    env_file = tmp_path / "runtime.env"
    _write_yaml(config_path, {"profile": "full_api"})
    env_file.write_text("HF_MCP_CLIENT_ID=client\n", encoding="utf-8")
    monkeypatch.delenv("HF_MCP_CLIENT_SECRET", raising=False)

    settings = load_settings(
        config_path=config_path,
        env={"HF_MCP_ENV_FILE": str(env_file)},
    )

    assert settings.runtime_env.get("HF_MCP_CLIENT_ID") == "client"
    assert "HF_MCP_CLIENT_SECRET" not in settings.runtime_env


def test_default_paths_are_exported_for_runtime_contract() -> None:
    assert DEFAULT_CONFIG_PATH.name == "config.yaml"
    assert DEFAULT_TOKEN_PATH.name == "token.json"


def test_configuration_doc_uses_yaml_runtime_example() -> None:
    configuration_doc = (PRODUCT_ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")

    assert "```yaml" in configuration_doc
    assert "```toml" not in configuration_doc
