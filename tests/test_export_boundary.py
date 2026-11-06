from __future__ import annotations

import io
import re
import json
import os
import runpy
import socket
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from importlib.metadata import version as installed_version
from pathlib import Path

import pytest
import pytest_socket
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
SECURITY_MODEL_DOC_PATH = PRODUCT_ROOT / "docs/security_model.md"
README_PATH = PRODUCT_ROOT / "README.md"
ALLOWED_PREFIX = "products/hf_mcp/"
YAML_EXAMPLE = "products/hf_mcp/config.example.yaml"
TOML_EXAMPLE = "products/hf_mcp/config.example.toml"
SKILLS_SUBTREE = "products/hf_mcp/skills/**"
CATALOG_DATA_SUBTREE = "products/hf_mcp/src/hf_mcp/data/**"
FORBIDDEN_EXPORT_REFERENCES = (
    ".council",
    ".scribe",
    ".claude",
    ".codex",
    "../",
    "..\\",
)
EXPECTED_MANIFEST_LINES = {
    "include README.md",
    "include pyproject.toml",
    "include MANIFEST.in",
    "include config.example.yaml",
    "include export_manifest.toml",
    "include scripts/build_release_dists.sh",
    "include scripts/smoke_installed.py",
    "recursive-include docs *.md",
    "recursive-include skills *.md",
    "recursive-include tests *.py",
    "recursive-include src/hf_mcp *.py",
    "recursive-include src/hf_mcp/data *.json",
    "global-exclude __pycache__ *.py[cod]",
}


def _validate_allowlist(entries: list[str]) -> None:
    for entry in entries:
        assert entry.startswith(ALLOWED_PREFIX), (
            f"Allowlist entry escapes product subtree: {entry}"
        )
        assert ".." not in entry, f"Allowlist entry contains parent traversal: {entry}"


def _allowlist_product_path(entry: str) -> Path:
    assert entry.startswith(ALLOWED_PREFIX), (
        f"Allowlist entry escapes product subtree: {entry}"
    )
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
@pytest.mark.parametrize(
    ("tag", "version", "expect_error"),
    (
        ("v1.2.3", "1.2.3", False),
        ("v1.2.4", "1.2.3", True),
        ("1.2.3", "1.2.3", True),
        ("v1.2.3-rc1", "1.2.3", True),
        ("", "1.2.3", True),
        (None, "1.2.3", True),
    ),
)
def test_release_tag_must_equal_v_plus_project_version(
    tag: str | None, version: str, expect_error: bool
) -> None:
    check = runpy.run_path(
        str(PRODUCT_ROOT / "scripts/check_pypi_version_available.py")
    )

    assert (check["tag_version_error"](tag, version) is not None) is expect_error


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_release_check_rejects_missing_or_mismatched_tag_before_network() -> None:
    script = PRODUCT_ROOT / "scripts/check_pypi_version_available.py"
    version = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"][
        "version"
    ]

    for args in ([], ["--tag", ""], ["--tag", f"v{version}.bogus"]):
        result = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode != 0, args


@pytest.mark.core
@pytest.mark.build
def test_docs_define_yaml_env_and_token_path_responsibilities() -> None:
    configuration_doc = CONFIGURATION_DOC_PATH.read_text(encoding="utf-8")

    assert (
        "YAML is the canonical runtime config input for non-secret policy"
        in configuration_doc
    )
    assert "must not be used to choose non-secret runtime policy" in configuration_doc
    assert (
        "must resolve to an absolute path outside the tracked repository"
        in configuration_doc
    )


@pytest.mark.core
@pytest.mark.build
def test_live_write_boundary_language_is_published_in_docs_and_config() -> None:
    security_doc = SECURITY_MODEL_DOC_PATH.read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")
    config_yaml = _allowlist_product_path(YAML_EXAMPLE).read_text(encoding="utf-8")

    assert "`confirm_live=true`" in security_doc
    assert "`confirm_live=true`" in readme

    assert "profile: reader" in config_yaml
    assert "enabled_capabilities: []" in config_yaml
    assert "enabled_parameter_families: []" in config_yaml
    assert "no automated live writes" in config_yaml
    assert "concrete writes require confirm_live=true" in config_yaml


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

    assert "setuptools>=77.0.3" in pyproject["build-system"]["requires"]
    assert project["name"] == "hf-mcp"
    assert re.fullmatch(r"\d+\.\d+\.\d+", project["version"])
    assert isinstance(project["version"], str) and project["version"].strip()
    assert project["scripts"]["hf-mcp"] == "hf_mcp.cli:main"
    assert project["keywords"] == ["hackforums", "mcp", "model-context-protocol"]
    for python_minor in ("3.11", "3.12", "3.13"):
        assert (
            f"Programming Language :: Python :: {python_minor}"
            in project["classifiers"]
        )
    assert any(c.startswith("Development Status ::") for c in project["classifiers"])
    assert project["description"].strip()
    assert project["authors"]
    assert set(project["urls"]) >= {"Homepage", "Repository", "Issues", "Changelog"}
    for url in project["urls"].values():
        assert url.startswith("https://github.com/CortaLabs/hf_mcp")
    assert pyproject["tool"]["setuptools"]["package-data"]["hf_mcp"] == ["data/*.json"]
    assert pyproject["tool"]["setuptools"]["data-files"][
        "skills/hf-mycode/references"
    ] == ["skills/hf-mycode/references/MYCODE_REFERENCE.md"]

    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8").lower()
    for forbidden in FORBIDDEN_EXPORT_REFERENCES:
        assert forbidden not in pyproject_text, (
            f"Forbidden reference in pyproject metadata: {forbidden}"
        )


@pytest.mark.core
@pytest.mark.build
def test_sdist_manifest_is_explicit_and_package_local() -> None:
    manifest_text = SDIST_MANIFEST_PATH.read_text(encoding="utf-8")
    lines = [
        line.strip()
        for line in manifest_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert set(lines) == EXPECTED_MANIFEST_LINES
    for forbidden in FORBIDDEN_EXPORT_REFERENCES:
        assert forbidden not in manifest_text.lower(), (
            f"Forbidden reference in MANIFEST.in: {forbidden}"
        )


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_release_build_derives_version_and_preserves_executable_entrypoint() -> None:
    build_script = (PRODUCT_ROOT / "scripts" / "build_release_dists.sh").read_text(
        encoding="utf-8"
    )

    assert "tomllib.loads" in build_script
    assert 'version = "0.6.1"' not in build_script
    assert '"$SCRIPT_DIR/.."' not in build_script
    assert os.access(PRODUCT_ROOT / "scripts" / "build_release_dists.sh", os.X_OK)


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
        requirement.name.lower().replace("_", "-") for requirement in dev_requirements
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
        lambda _name: pytest.fail(
            "installed metadata must not override the source version"
        ),
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


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
@pytest.mark.parametrize("target_kind", ["relative", "source", "nonempty"])
def test_release_build_rejects_unsafe_output_without_mutating_source(
    target_kind: str, tmp_path: Path, isolated_child_context
) -> None:
    if target_kind == "relative":
        target = Path("relative-build-output")
    elif target_kind == "source":
        target = PRODUCT_ROOT
    else:
        target = tmp_path / "not-empty"
        target.mkdir()
        sentinel = target / "preserve.txt"
        sentinel.write_text("keep", encoding="utf-8")

    child_env = isolated_child_context.environment()
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        ["bash", str(PRODUCT_ROOT / "scripts" / "build_release_dists.sh"), str(target)],
        cwd=PRODUCT_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    if target_kind == "nonempty":
        assert sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_smoke_rejects_missing_artifacts_without_writing_a_pass_receipt(
    tmp_path: Path, isolated_child_context
) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    work_dir = tmp_path / "work"
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "provisioned.whl").touch()
    receipt = tmp_path / "receipt.json"
    result = subprocess.run(
        [
            sys.executable,
            str(PRODUCT_ROOT / "scripts" / "smoke_installed.py"),
            "--artifact-dir",
            str(artifact_dir),
            "--work-dir",
            str(work_dir),
            "--wheelhouse",
            str(wheelhouse),
            "--source-revision",
            "a" * 40,
            "--expected-version",
            "0.4.5",
            "--receipt",
            str(receipt),
        ],
        cwd=tmp_path,
        env=isolated_child_context.environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "failed"
    assert "artifact" in (result.stdout + result.stderr).lower()


def _make_controlled_release_archives(
    tmp_path: Path, *, failure_mode: str | None = None
) -> tuple[Path, Path, Path]:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    wheel_name = "hf_mcp-0.4.5-py3-none-any.whl"
    if failure_mode == "stale_filename":
        wheel_name = "hf_mcp-0.4.4-py3-none-any.whl"
    wheel_path = artifact_dir / wheel_name
    wheel_files = {
        "hf_mcp/__init__.py": b"__version__ = '0.4.5'\n",
        "hf_mcp/cli.py": b"",
        "hf_mcp/server.py": b"",
        "hf_mcp/dispatcher.py": b"",
        "hf_mcp/transport.py": b"",
        "hf_mcp/data/forums_index.json": b"{}\n",
        "hf_mcp-0.4.5.dist-info/METADATA": (
            b"Name: hf-mcp\nVersion: 0.4.4\n"
            if failure_mode == "version"
            else b"Name: hf-mcp\nVersion: 0.4.5\n"
        ),
        "hf_mcp-0.4.5.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
        "hf_mcp-0.4.5.data/data/docs/configuration.md": b"config\n",
    }
    if failure_mode != "resource":
        wheel_files["hf_mcp/data/forums_index.json"] = b"{}\n"
    else:
        wheel_files.pop("hf_mcp/data/forums_index.json")
    for skill in (
        "hf-api-v2",
        "hf-mcp",
        "hf-mcp-bootstrap",
        "hf-mcp-reads",
        "hf-mcp-writes",
        "hf-mycode",
    ):
        wheel_files[f"hf_mcp-0.4.5.data/data/skills/{skill}/SKILL.md"] = b"skill\n"
    if failure_mode != "skill_reference":
        wheel_files[
            "hf_mcp-0.4.5.data/data/skills/hf-mycode/references/MYCODE_REFERENCE.md"
        ] = b"reference\n"
    if failure_mode == "contamination":
        wheel_files["private/.council/AGENTS.md"] = b"forbidden\n"
    with zipfile.ZipFile(wheel_path, "w") as archive:
        for name, content in wheel_files.items():
            archive.writestr(name, content)

    sdist_path = artifact_dir / "hf-mcp-0.4.5.tar.gz"
    sdist_files = {
        "README.md": b"README\n",
        "pyproject.toml": (
            b'[build-system]\nrequires = ["setuptools>=77.0.3", "wheel"]\n'
            b'build-backend = "setuptools.build_meta"\n'
            b'[project]\nname = "hf-mcp"\nversion = "0.4.5"\n'
        ),
        "MANIFEST.in": b"",
        "config.example.yaml": b"profile: custom\n",
        "export_manifest.toml": b"",
        "scripts/build_release_dists.sh": b"",
        "scripts/smoke_installed.py": b"",
        "src/hf_mcp/__init__.py": b"",
        "src/hf_mcp/cli.py": b"",
        "src/hf_mcp/server.py": b"",
        "src/hf_mcp/dispatcher.py": b"",
        "src/hf_mcp/transport.py": b"",
        "src/hf_mcp/data/forums_index.json": b"{}\n",
        "docs/configuration.md": b"config\n",
        "PKG-INFO": b"Name: hf-mcp\nVersion: 0.4.5\n",
    }
    if failure_mode != "resource":
        for skill in (
            "hf-api-v2",
            "hf-mcp",
            "hf-mcp-bootstrap",
            "hf-mcp-reads",
            "hf-mcp-writes",
            "hf-mycode",
        ):
            sdist_files[f"skills/{skill}/SKILL.md"] = b"skill\n"
    else:
        sdist_files.pop("src/hf_mcp/data/forums_index.json")
    if failure_mode != "skill_reference":
        sdist_files["skills/hf-mycode/references/MYCODE_REFERENCE.md"] = b"reference\n"
    if failure_mode == "unsafe_tar":
        sdist_files["../escape.txt"] = b"outside\n"
    with tarfile.open(sdist_path, "w:gz") as archive:
        for name, content in sdist_files.items():
            info = tarfile.TarInfo(f"hf-mcp-0.4.5/{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        if failure_mode == "symlink_tar":
            link = tarfile.TarInfo("hf-mcp-0.4.5/skills/outside")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../outside"
            archive.addfile(link)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "provisioned.whl").touch()
    return artifact_dir, wheelhouse, wheel_path


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
@pytest.mark.parametrize(
    ("failure_mode", "expected_step"),
    [
        ("contamination", "archive_audit"),
        ("version", "version_audit"),
        ("resource", "resource_audit"),
        ("skill_reference", "resource_audit"),
        ("unsafe_tar", "archive_audit"),
        ("symlink_tar", "archive_audit"),
        ("stale_filename", "version_audit"),
        ("duplicate", "artifact_inventory"),
        ("unsafe_work", "arguments"),
    ],
)
def test_installed_smoke_cli_records_controlled_failure(
    failure_mode: str, expected_step: str, tmp_path: Path, isolated_child_context
) -> None:
    artifact_dir, wheelhouse, wheel_path = _make_controlled_release_archives(
        tmp_path, failure_mode=failure_mode
    )
    if failure_mode == "duplicate":
        (artifact_dir / "hf_mcp-0.4.5-duplicate.whl").write_bytes(
            wheel_path.read_bytes()
        )
    work_dir = PRODUCT_ROOT if failure_mode == "unsafe_work" else tmp_path / "work"
    receipt = tmp_path / "receipt.json"
    child_env = isolated_child_context.environment()
    child_env.pop("PYTHONPATH", None)
    child_env.pop("HF_BUILD_SRC", None)
    result = subprocess.run(
        [
            sys.executable,
            str(PRODUCT_ROOT / "scripts" / "smoke_installed.py"),
            "--artifact-dir",
            str(artifact_dir),
            "--work-dir",
            str(work_dir),
            "--wheelhouse",
            str(wheelhouse),
            "--source-revision",
            "a" * 40,
            "--expected-version",
            "0.4.5",
            "--receipt",
            str(receipt),
        ],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    failure_receipt = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure_receipt["status"] == "failed"
    assert failure_receipt["failed_step"] == expected_step
    assert str(Path.home()) not in result.stdout + result.stderr


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_sdist_smoke_extractor_materializes_only_the_validated_project(
    tmp_path: Path,
) -> None:
    artifact_dir, _, _ = _make_controlled_release_archives(tmp_path)
    smoke = runpy.run_path(str(PRODUCT_ROOT / "scripts" / "smoke_installed.py"))
    source_root = smoke["_extract_sdist"](
        artifact_dir / "hf-mcp-0.4.5.tar.gz",
        tmp_path / "extracted",
        "0.4.5",
    )

    assert source_root.is_dir()
    assert (source_root / "pyproject.toml").is_file()
    assert (source_root / "src" / "hf_mcp" / "__init__.py").is_file()
    assert not (tmp_path / "escape.txt").exists()


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_sdist_backend_bootstrap_rejects_stale_setuptools() -> None:
    smoke = runpy.run_path(str(PRODUCT_ROOT / "scripts" / "smoke_installed.py"))
    requirements = smoke["_build_system_requirements"](PRODUCT_ROOT)
    install_args = smoke["_build_requirement_install_args"](
        Path("/offline-wheelhouse"), requirements
    )

    assert "--upgrade" in install_args
    assert "setuptools>=77.0.3" in install_args
    assert all(requirement in install_args for requirement in requirements)
    assert smoke["_build_requirement_failures"](
        requirements, {"setuptools": "65.5.0", "wheel": "0.48.0"}
    ) == ["setuptools>=77.0.3 (installed 65.5.0)"]
    assert (
        smoke["_build_requirement_failures"](
            requirements, {"setuptools": "77.0.3", "wheel": "0.48.0"}
        )
        == []
    )


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_failed_subprocess_diagnostics_redact_paths_and_secret_text(
    tmp_path: Path,
) -> None:
    smoke = runpy.run_path(str(PRODUCT_ROOT / "scripts" / "smoke_installed.py"))
    records = []
    child_code = (
        "import sys; "
        f"print({str(tmp_path)!r} + ' not a directory token=smoke-secret', file=sys.stderr); "
        "print('stdout-poison-marker'); raise SystemExit(4)"
    )

    with pytest.raises(smoke["SmokeFailure"]) as failure:
        smoke["_run"](
            "controlled_failure",
            [sys.executable, "-I", "-c", child_code],
            cwd=tmp_path,
            env={"PATH": os.defpath},
            records=records,
        )

    detail = str(failure.value)
    assert "not a directory" in detail
    assert str(tmp_path) not in detail
    assert "smoke-secret" not in detail
    assert "stdout-poison-marker" not in detail
    assert records[0]["exit_code"] == 4
    assert records[0]["result"] == "fail"
    assert records[0]["diagnostic"] == detail.removeprefix(
        "check failed: controlled_failure: "
    )


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
@pytest.mark.parametrize(
    "state_target", ["config", "token", "explicit_draft", "default_draft"]
)
@pytest.mark.parametrize("install_kind", ["wheel", "sdist_derived"])
def test_installed_probe_state_guard_passes_clean_state_and_receipts_each_write(
    state_target: str,
    install_kind: str,
    tmp_path: Path,
    isolated_child_context,
) -> None:
    smoke = runpy.run_path(str(PRODUCT_ROOT / "scripts" / "smoke_installed.py"))
    home = isolated_child_context.state.home
    explicit_state = tmp_path / "explicit-state"
    explicit_drafts = explicit_state / "drafts"
    explicit_drafts.mkdir(parents=True)
    config_path = explicit_state / "config.yaml"
    config_path.write_text("profile: reader\n", encoding="utf-8")
    token_path = explicit_state / "token.json"
    default_draft = home / ".config" / "hf_mcp" / "drafts" / "smoke-draft.json"
    child_env = isolated_child_context.environment()
    child_env.update(
        {
            "HOME": str(home),
            "HF_MCP_CONFIG": str(config_path),
            "HF_MCP_TOKEN_PATH": str(token_path),
            "HF_MCP_DRAFT_DIR": str(explicit_drafts),
        }
    )
    state_roots = (explicit_state, home)
    records = []
    clean_result = smoke["_run_state_guarded_probe"](
        f"{install_kind}_installed_probe",
        [sys.executable, "-I", "-c", "print('clean probe')"],
        cwd=tmp_path,
        env=child_env,
        records=records,
        state_roots=state_roots,
    )
    assert clean_result.returncode == 0
    assert records[-1]["result"] == "pass"

    target_path = {
        "config": config_path,
        "token": token_path,
        "explicit_draft": explicit_drafts / "synthetic.json",
        "default_draft": default_draft,
    }[state_target]
    write_code = (
        "from pathlib import Path; "
        f"Path({str(target_path)!r}).write_text('synthetic-state-write', encoding='utf-8')"
    )
    with pytest.raises(smoke["SmokeFailure"]) as failure:
        smoke["_run_state_guarded_probe"](
            f"{install_kind}_installed_probe",
            [sys.executable, "-I", "-c", write_code],
            cwd=tmp_path,
            env=child_env,
            records=records,
            state_roots=state_roots,
        )

    receipt_path = tmp_path / "state-leak-receipt.json"
    receipt = smoke["_failure_receipt_document"](
        smoke["argparse"].Namespace(source_revision="a" * 40, expected_version="0.6.1"),
        failure.value,
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    failed_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert failed_receipt["status"] == "failed"
    assert failed_receipt["failed_step"] == "state_leak"
    assert failed_receipt["failed_check"]["result"] == "fail"
    assert "filesystem state" in failed_receipt["diagnostic"]
    assert str(tmp_path) not in json.dumps(failed_receipt)


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_smoke_failure_receipt_binds_safe_check_exit_and_argv(
    tmp_path: Path, isolated_child_context
) -> None:
    artifact_dir, wheelhouse, _ = _make_controlled_release_archives(tmp_path)
    work_dir = tmp_path / "work"
    receipt = tmp_path / "receipt.json"
    child_env = isolated_child_context.environment()
    child_env.pop("PYTHONPATH", None)
    child_env.pop("HF_BUILD_SRC", None)
    result = subprocess.run(
        [
            sys.executable,
            str(PRODUCT_ROOT / "scripts" / "smoke_installed.py"),
            "--artifact-dir",
            str(artifact_dir),
            "--work-dir",
            str(work_dir),
            "--wheelhouse",
            str(wheelhouse),
            "--source-revision",
            "a" * 40,
            "--expected-version",
            "0.4.5",
            "--receipt",
            str(receipt),
        ],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
    )

    failure_receipt = json.loads(receipt.read_text(encoding="utf-8"))
    failed_check = failure_receipt["failed_check"]
    assert result.returncode != 0
    assert failure_receipt["failed_step"] == "sdist_build_tool"
    assert failed_check["result"] == "fail"
    assert failed_check["exit_code"] != 0
    assert len(failed_check["argv_sha256"]) == 64
    assert str(tmp_path) not in json.dumps(failure_receipt) + result.stderr


@pytest.mark.core
@pytest.mark.build
def test_release_metadata_describes_current_release() -> None:
    version = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"][
        "version"
    ]
    changelog = (PRODUCT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    readme = README_PATH.read_text(encoding="utf-8")

    assert f"## {version}" in changelog
    assert changelog.index(f"## {version}") < changelog.index("## 0.6.1")
    assert "Version 0.4" not in readme
    assert "Current release line" not in readme


@pytest.mark.core
@pytest.mark.build
def test_public_docs_have_no_internal_process_language() -> None:
    banned = re.compile(
        r"this wave|operator-approved|hackforums-council|export boundary"
        r"|\b(?:probes?|readback|truths?|proof|prove[sn]?|proven)\b"
        r"|acceptance|baseline|sandbox"
        r"|(?:tid|fid|thread|forum)\W{0,3}\d{5,}",
        re.IGNORECASE,
    )
    public_files = [
        README_PATH,
        PRODUCT_ROOT / "config.example.yaml",
        *sorted((PRODUCT_ROOT / "docs").glob("*.md")),
        *sorted((PRODUCT_ROOT / "docs").glob("*.html")),
        *sorted((PRODUCT_ROOT / "skills").rglob("*.md")),
    ]
    for path in public_files:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"https?://\S+", "", text)
        match = banned.search(text)
        assert match is None, f"{match.group(0)!r} found in {path.name}"


@pytest.mark.core
@pytest.mark.build
def test_packaging_files_reference_only_existing_files() -> None:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    data_files = pyproject["tool"]["setuptools"]["data-files"]
    for patterns in data_files.values():
        for pattern in patterns:
            assert list(PRODUCT_ROOT.glob(pattern)), (
                f"data-files matches nothing: {pattern}"
            )

    for line in SDIST_MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("include "):
            assert (PRODUCT_ROOT / line.removeprefix("include ")).exists(), line

    assert not (PRODUCT_ROOT / "docs" / "export_boundary.md").exists()
    assert not list((PRODUCT_ROOT / "docs").glob("*.mycode"))
    assert ".council/" in (PRODUCT_ROOT / ".gitignore").read_text(encoding="utf-8")


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_version_ignores_unrelated_pyproject_outside_a_source_tree(
    tmp_path: Path,
) -> None:
    site = tmp_path / "lib" / "python3.12" / "site-packages" / "hf_mcp"
    site.mkdir(parents=True)
    (site / "__init__.py").write_bytes(
        (PRODUCT_ROOT / "src" / "hf_mcp" / "__init__.py").read_bytes()
    )
    (tmp_path / "lib" / "pyproject.toml").write_text(
        '[project]\nname = "hf-mcp"\nversion = "9.9.9"\n', encoding="utf-8"
    )
    namespace = runpy.run_path(str(site / "__init__.py"))
    assert namespace["_read_local_pyproject_version"]() is None
    assert namespace["__version__"] == installed_version("hf-mcp")
