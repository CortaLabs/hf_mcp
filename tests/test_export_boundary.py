from __future__ import annotations

from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]
EXPORT_MANIFEST_PATH = REPO_ROOT / "products/hf_mcp/export_manifest.toml"
SDIST_MANIFEST_PATH = REPO_ROOT / "products/hf_mcp/MANIFEST.in"
PYPROJECT_PATH = REPO_ROOT / "products/hf_mcp/pyproject.toml"
CONFIGURATION_DOC_PATH = REPO_ROOT / "products/hf_mcp/docs/configuration.md"
EXPORT_BOUNDARY_DOC_PATH = REPO_ROOT / "products/hf_mcp/docs/export_boundary.md"
ALLOWED_PREFIX = "products/hf_mcp/"
YAML_EXAMPLE = "products/hf_mcp/config.example.yaml"
TOML_EXAMPLE = "products/hf_mcp/config.example.toml"
FORBIDDEN_EXPORT_REFERENCES = (".council", ".scribe", ".claude", ".codex", "../", "..\\")
EXPECTED_MANIFEST_LINES = {
    "include README.md",
    "include pyproject.toml",
    "include MANIFEST.in",
    "include config.example.yaml",
    "include export_manifest.toml",
    "recursive-include docs *.md",
    "recursive-include tests *.py",
    "recursive-include src/hf_mcp *.py",
    "global-exclude __pycache__ *.py[cod]",
}


def _validate_allowlist(entries: list[str]) -> None:
    for entry in entries:
        assert entry.startswith(ALLOWED_PREFIX), f"Allowlist entry escapes product subtree: {entry}"
        assert ".." not in entry, f"Allowlist entry contains parent traversal: {entry}"


def test_export_manifest_is_product_subtree_only() -> None:
    manifest = tomllib.loads(EXPORT_MANIFEST_PATH.read_text(encoding="utf-8"))
    allowlist = manifest["allowlist"]

    assert isinstance(allowlist, list)
    assert allowlist, "allowlist must not be empty"
    _validate_allowlist(allowlist)
    assert YAML_EXAMPLE in allowlist
    assert TOML_EXAMPLE not in allowlist


def test_public_runtime_example_is_yaml_only() -> None:
    assert (REPO_ROOT / YAML_EXAMPLE).exists()
    assert not (REPO_ROOT / TOML_EXAMPLE).exists()


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


def test_pyproject_release_contract_and_metadata_boundary() -> None:
    project = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"]

    assert project["name"] == "hf-mcp"
    assert isinstance(project["version"], str) and project["version"].strip()
    assert project["scripts"]["hf-mcp"] == "hf_mcp.cli:main"
    assert project["keywords"] == ["hackforums", "mcp", "model-context-protocol"]
    assert "Programming Language :: Python :: 3.11" in project["classifiers"]

    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8").lower()
    for forbidden in FORBIDDEN_EXPORT_REFERENCES:
        assert forbidden not in pyproject_text, f"Forbidden reference in pyproject metadata: {forbidden}"


def test_sdist_manifest_is_explicit_and_package_local() -> None:
    manifest_text = SDIST_MANIFEST_PATH.read_text(encoding="utf-8")
    lines = [line.strip() for line in manifest_text.splitlines() if line.strip() and not line.strip().startswith("#")]

    assert set(lines) == EXPECTED_MANIFEST_LINES
    for forbidden in FORBIDDEN_EXPORT_REFERENCES:
        assert forbidden not in manifest_text.lower(), f"Forbidden reference in MANIFEST.in: {forbidden}"
