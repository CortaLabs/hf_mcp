from __future__ import annotations

from pathlib import Path
import tomllib

import pytest
import yaml


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
