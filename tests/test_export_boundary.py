from __future__ import annotations

import os
import socket
import subprocess
import sys
import tomllib
from importlib.metadata import version as installed_version
from pathlib import Path

import pytest
import pytest_socket
import yaml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet

import hf_mcp
from hf_mcp import config as hf_config
from hf_mcp.config import _resolve_config_path


def _product_root(test_file: Path) -> Path:
    return test_file.resolve().parents[1]


PRODUCT_ROOT = _product_root(Path(__file__))
EXPORT_MANIFEST_PATH = PRODUCT_ROOT / "export_manifest.toml"
SDIST_MANIFEST_PATH = PRODUCT_ROOT / "MANIFEST.in"
PYPROJECT_PATH = PRODUCT_ROOT / "pyproject.toml"
CONFIGURATION_DOC_PATH = PRODUCT_ROOT / "docs/configuration.md"
EXPORT_BOUNDARY_DOC_PATH = PRODUCT_ROOT / "docs/export_boundary.md"
PUBLISH_WORKFLOW_PATH = PRODUCT_ROOT / ".github/workflows/publish-hf-mcp-pypi.yml"
ALLOWED_PREFIX = "products/hf_mcp/"
YAML_EXAMPLE = "products/hf_mcp/config.example.yaml"
TOML_EXAMPLE = "products/hf_mcp/config.example.toml"
SKILLS_SUBTREE = "products/hf_mcp/skills/**"
CATALOG_DATA_SUBTREE = "products/hf_mcp/src/hf_mcp/data/**"
FORBIDDEN_EXPORT_REFERENCES = (".council", ".scribe", ".claude", ".codex", "../", "..\\")
EXPECTED_MANIFEST_LINES = {
    "include README.md",
    "include pyproject.toml",
    "include MANIFEST.in",
    "include config.example.yaml",
    "include export_manifest.toml",
    "recursive-include docs *.md",
    "recursive-include skills *.md",
    "recursive-include tests *.py",
    "recursive-include src/hf_mcp *.py",
    "recursive-include src/hf_mcp/data *.json",
    "global-exclude __pycache__ *.py[cod]",
}


def _validate_allowlist(entries: list[str]) -> None:
    for entry in entries:
        assert entry.startswith(ALLOWED_PREFIX), f"Allowlist entry escapes product subtree: {entry}"
        assert ".." not in entry, f"Allowlist entry contains parent traversal: {entry}"


def _allowlist_product_path(entry: str) -> Path:
    assert entry.startswith(ALLOWED_PREFIX), f"Allowlist entry escapes product subtree: {entry}"
    return PRODUCT_ROOT / entry.removeprefix(ALLOWED_PREFIX)


@pytest.mark.core
@pytest.mark.build
def test_export_manifest_is_product_subtree_only() -> None:
    manifest = tomllib.loads(EXPORT_MANIFEST_PATH.read_text(encoding="utf-8"))
    allowlist = manifest["allowlist"]

    assert isinstance(allowlist, list)
    assert allowlist, "allowlist must not be empty"
    _validate_allowlist(allowlist)
    assert YAML_EXAMPLE in allowlist
    assert SKILLS_SUBTREE in allowlist
    assert CATALOG_DATA_SUBTREE in allowlist
    assert TOML_EXAMPLE not in allowlist


@pytest.mark.core
@pytest.mark.build
def test_public_runtime_example_is_yaml_only() -> None:
    assert _allowlist_product_path(YAML_EXAMPLE).exists()
    assert not _allowlist_product_path(TOML_EXAMPLE).exists()


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_export_root_resolves_from_standalone_product_checkout(tmp_path: Path) -> None:
    product_root = tmp_path / "standalone-hf-mcp"
    tests_dir = product_root / "tests"
    tests_dir.mkdir(parents=True)
    test_file = tests_dir / "test_export_boundary.py"
    test_file.touch()

    assert _product_root(test_file) == product_root


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_publisher_trigger_containment() -> None:
    workflow = yaml.load(PUBLISH_WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    triggers = workflow["on"]
    event_cases = (
        ("source push", "push", False),
        ("docs push", "push", False),
        ("ordinary branch push", "push", False),
        ("tag push", "push", False),
        ("fork pull request", "pull_request", False),
        ("manual workflow dispatch", "workflow_dispatch", True),
    )

    assert set(triggers) == {"workflow_dispatch"}
    for description, event_name, expected_match in event_cases:
        assert (event_name in triggers) is expected_match, description


@pytest.mark.core
@pytest.mark.build
def test_docs_define_yaml_env_and_token_path_responsibilities() -> None:
    configuration_doc = CONFIGURATION_DOC_PATH.read_text(encoding="utf-8")
    export_boundary_doc = EXPORT_BOUNDARY_DOC_PATH.read_text(encoding="utf-8")

    assert "YAML is the canonical runtime config input for non-secret policy" in configuration_doc
    assert "must not be used to choose non-secret runtime policy" in configuration_doc
    assert "must resolve to an absolute path outside the tracked repository" in configuration_doc

    assert "Runtime policy is YAML-first: non-secret policy belongs in `config.yaml`." in export_boundary_doc
    assert "reserved for secrets and machine-local overrides" in export_boundary_doc
    assert "must not define" in export_boundary_doc
    assert "profile/capability/parameter policy" in export_boundary_doc
    assert "Token-store location must be an absolute path outside the tracked repository" in export_boundary_doc


@pytest.mark.core
@pytest.mark.build
def test_live_write_boundary_language_is_published_in_docs_and_config() -> None:
    export_boundary_doc = EXPORT_BOUNDARY_DOC_PATH.read_text(encoding="utf-8")
    config_yaml = _allowlist_product_path(YAML_EXAMPLE).read_text(encoding="utf-8")

    required_boundary_markers = [
        "posts.reply",
        "TID 6083735",
        "at most one `threads.create` in `FID 375`",
        "No Bytes live writes are in scope for this wave.",
        "Placeholder writes remain out of scope in this wave",
    ]
    for marker in required_boundary_markers:
        assert marker in export_boundary_doc

    assert "posts.reply on TID 6083735" in config_yaml
    assert "at most one threads.create in FID 375" in config_yaml
    assert "no Bytes live writes in this wave" in config_yaml
    assert "placeholder writes remain out of scope in this wave" in config_yaml


@pytest.mark.core
@pytest.mark.build
def test_export_manifest_rejects_root_level_assets() -> None:
    bad_allowlist = [
        "products/hf_mcp/README.md",
        "README.md",
    ]

    try:
        _validate_allowlist(bad_allowlist)
    except AssertionError:
        return
    raise AssertionError("Expected root-level asset to fail export boundary validation")


@pytest.mark.core
@pytest.mark.build
def test_pyproject_release_contract_and_metadata_boundary() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert project["name"] == "hf-mcp"
    assert isinstance(project["version"], str) and project["version"].strip()
    assert project["scripts"]["hf-mcp"] == "hf_mcp.cli:main"
    assert project["keywords"] == ["hackforums", "mcp", "model-context-protocol"]
    assert "Programming Language :: Python :: 3.11" in project["classifiers"]
    assert pyproject["tool"]["setuptools"]["package-data"]["hf_mcp"] == ["data/*.json"]

    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8").lower()
    for forbidden in FORBIDDEN_EXPORT_REFERENCES:
        assert forbidden not in pyproject_text, f"Forbidden reference in pyproject metadata: {forbidden}"


@pytest.mark.core
@pytest.mark.build
def test_sdist_manifest_is_explicit_and_package_local() -> None:
    manifest_text = SDIST_MANIFEST_PATH.read_text(encoding="utf-8")
    lines = [line.strip() for line in manifest_text.splitlines() if line.strip() and not line.strip().startswith("#")]

    assert set(lines) == EXPECTED_MANIFEST_LINES
    for forbidden in FORBIDDEN_EXPORT_REFERENCES:
        assert forbidden not in manifest_text.lower(), f"Forbidden reference in MANIFEST.in: {forbidden}"


@pytest.mark.core
@pytest.mark.build
def test_dev_tools_are_exactly_pinned_without_runtime_dependency_drift() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    project = pyproject["project"]

    runtime_requirements = {
        requirement.name.lower(): str(requirement.specifier)
        for requirement in map(Requirement, project["dependencies"])
    }
    assert runtime_requirements["pyyaml"] == ">=6.0"
    assert SpecifierSet(runtime_requirements["mcp"]) == SpecifierSet(">=2.3.0,<3")
    assert "council-mcp" not in runtime_requirements

    dev_requirements = [
        Requirement(requirement)
        for requirement in project["optional-dependencies"]["dev"]
    ]
    dev_names = [
        requirement.name.lower().replace("_", "-")
        for requirement in dev_requirements
    ]
    assert len(dev_names) == len(set(dev_names))
    assert {
        "build",
        "jsonschema",
        "mypy",
        "packaging",
        "pytest",
        "pytest-randomly",
        "pytest-socket",
        "pytest-xdist",
        "ruff",
        "setuptools",
        "twine",
        "wheel",
    } <= set(dev_names)
    for requirement in dev_requirements:
        specifiers = list(requirement.specifier)
        assert len(specifiers) == 1
        assert specifiers[0].operator == "=="
        assert installed_version(requirement.name) == specifiers[0].version
    ruff_options = pyproject["tool"]["ruff"]
    assert ruff_options["target-version"] == "py311"
    assert ruff_options["src"] == ["src"]
    assert ruff_options["lint"]["isort"]["known-first-party"] == ["hf_mcp"]
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]
    assert pytest_options["strict_markers"] is True
    assert pytest_options["addopts"].split() == [
        "--disable-socket",
        "--allow-unix-socket",
    ]
    assert {marker.split(":", 1)[0] for marker in pytest_options["markers"]} == {
        "core",
        "regression",
        "formatting",
        "registry",
        "build",
    }
    assert Path(hf_mcp.__file__).resolve().is_relative_to(PRODUCT_ROOT / "src")


@pytest.mark.core
@pytest.mark.build
def test_version_resolution_prefers_source_then_distribution_then_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hf_mcp, "_read_local_pyproject_version", lambda: "9.8.7")
    monkeypatch.setattr(
        hf_mcp,
        "distribution_version",
        lambda _name: pytest.fail("installed metadata must not override the source version"),
    )
    hf_mcp._resolve_version.cache_clear()
    try:
        assert hf_mcp._resolve_version() == "9.8.7"
    finally:
        hf_mcp._resolve_version.cache_clear()

    monkeypatch.setattr(hf_mcp, "_read_local_pyproject_version", lambda: None)
    monkeypatch.setattr(hf_mcp, "distribution_version", lambda _name: "7.6.5")
    hf_mcp._resolve_version.cache_clear()
    try:
        assert hf_mcp._resolve_version() == "7.6.5"
    finally:
        hf_mcp._resolve_version.cache_clear()

    def missing_distribution(name: str) -> str:
        raise hf_mcp.PackageNotFoundError(name)

    monkeypatch.setattr(hf_mcp, "distribution_version", missing_distribution)
    hf_mcp._resolve_version.cache_clear()
    try:
        assert hf_mcp._resolve_version() == hf_mcp._UNKNOWN_VERSION
    finally:
        hf_mcp._resolve_version.cache_clear()


@pytest.mark.core
@pytest.mark.build
def test_hermetic_hf_test_environment_is_ephemeral_and_test_overrides_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = Path(os.environ["HOME"]).resolve()
    config_path = hf_config.DEFAULT_CONFIG_PATH.resolve()
    token_path = Path(os.environ["HF_MCP_TOKEN_PATH"]).resolve()
    draft_dir = Path(os.environ["HF_MCP_DRAFT_DIR"]).resolve()

    assert home.is_relative_to(tmp_path.resolve())
    assert config_path.is_relative_to(home)
    assert token_path.is_relative_to(home)
    assert draft_dir.is_relative_to(home)

    override = (tmp_path / "test-local-config.yaml").resolve()
    monkeypatch.setenv("HF_MCP_CONFIG", str(override))
    assert _resolve_config_path(None, os.environ) == override


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_hermetic_parent_socket_guard_blocks_ipv4_and_ipv6() -> None:
    for family in (socket.AF_INET, socket.AF_INET6):
        with pytest.warns(UserWarning, match="test tried to use socket.socket"):
            with pytest.raises(pytest_socket.SocketBlockedError):
                socket.socket(family, socket.SOCK_STREAM)


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_hermetic_child_environment_drops_credentials_and_blocks_outbound_sockets(
    isolated_child_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    client_poison = "hf-build-poison-client-id"
    secret_poison = "hf-build-poison-client-secret"
    monkeypatch.setenv("HF_MCP_CLIENT_ID", client_poison)
    monkeypatch.setenv("HF_MCP_CLIENT_SECRET", secret_poison)

    child_env = isolated_child_context.environment()
    assert "HF_MCP_CLIENT_ID" not in child_env
    assert "HF_MCP_CLIENT_SECRET" not in child_env

    child_script = """
import os
import socket
from pathlib import Path

import hf_mcp
from hf_mcp.config import load_settings

settings = load_settings(config_path=None)
assert settings.config_path == Path(os.environ["HF_MCP_CONFIG"])
assert settings.token_path == Path(os.environ["HF_MCP_TOKEN_PATH"])
assert settings.draft_dir == Path(os.environ["HF_MCP_DRAFT_DIR"])
assert Path(hf_mcp.__file__).resolve().is_relative_to(Path(os.environ["HF_BUILD_SRC"]).resolve())
credentials_absent = not any(os.environ.get(name) for name in ("HF_MCP_CLIENT_ID", "HF_MCP_CLIENT_SECRET"))
blocked = []
for host in ("203.0.113.1", "2001:db8::1"):
    try:
        socket.create_connection((host, 443), timeout=0.1)
    except Exception as exc:
        blocked.append(type(exc).__name__ == "SocketBlockedError")
    else:
        blocked.append(False)
print(f"credentials_absent={credentials_absent}; outbound_blocked={all(blocked)}")
if not credentials_absent or not all(blocked):
    raise SystemExit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", child_script],
        cwd=PRODUCT_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "credentials_absent=True; outbound_blocked=True" in result.stdout
    assert client_poison not in result.stdout + result.stderr
    assert secret_poison not in result.stdout + result.stderr
