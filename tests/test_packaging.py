from __future__ import annotations

import os
import runpy
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((PRODUCT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
VERSION = PYPROJECT["project"]["version"]


@pytest.mark.core
@pytest.mark.build
def test_manifest_and_package_data_name_existing_files() -> None:
    for line in (PRODUCT_ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines():
        if line.startswith("include "):
            assert (PRODUCT_ROOT / line.removeprefix("include ")).exists(), line
        elif line.startswith("recursive-include "):
            directory, pattern = line.split()[1:3]
            assert list((PRODUCT_ROOT / directory).rglob(pattern)), line
    for pattern in PYPROJECT["tool"]["setuptools"]["package-data"]["hf_mcp"]:
        assert list((PRODUCT_ROOT / "src" / "hf_mcp").glob(pattern)), pattern


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
@pytest.mark.parametrize(
    ("tag", "expect_error"),
    (
        (f"v{VERSION}", False),
        (VERSION, True),
        (f"v{VERSION}.bogus", True),
        ("", True),
        (None, True),
    ),
)
def test_release_tag_must_equal_v_plus_project_version(
    tag: str | None, expect_error: bool
) -> None:
    check = runpy.run_path(
        str(PRODUCT_ROOT / "scripts/check_pypi_version_available.py")
    )

    assert (check["tag_version_error"](tag, VERSION) is not None) is expect_error


@pytest.mark.build
def test_build_script_yields_wheel_and_sdist_with_expected_members(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "dist"
    env = {**os.environ, "HF_BUILD_PYTHON": sys.executable}
    script = PRODUCT_ROOT / "scripts/build_release_dists.sh"
    subprocess.run(
        ["bash", str(script), str(out_dir)], check=True, env=env, timeout=300
    )

    (wheel,) = out_dir.glob("*.whl")
    (sdist,) = out_dir.glob("*.tar.gz")
    wheel_names = ZipFile(wheel).namelist()
    assert "hf_mcp/__init__.py" in wheel_names
    assert "hf_mcp/data/forums_index.json" in wheel_names
    assert not [name for name in wheel_names if ".data/" in name]
    with tarfile.open(sdist) as archive:
        sdist_names = archive.getnames()
    root = f"hf_mcp-{VERSION}"
    for member in (
        "pyproject.toml",
        "MANIFEST.in",
        "skills/hf-mcp/SKILL.md",
        "docs/configuration.md",
    ):
        assert f"{root}/{member}" in sdist_names, member

    refused = subprocess.run(
        ["bash", str(script), "relative/dist"], capture_output=True, check=False
    )
    assert refused.returncode == 2


@pytest.mark.core
@pytest.mark.build
@pytest.mark.regression
def test_version_ignores_unrelated_pyproject_outside_a_source_tree(
    tmp_path: Path,
) -> None:
    from importlib.metadata import version as installed_version

    site = tmp_path / "lib" / "python3.12" / "site-packages" / "hf_mcp"
    site.mkdir(parents=True)
    (site / "__init__.py").write_bytes(
        (PRODUCT_ROOT / "src/hf_mcp/__init__.py").read_bytes()
    )
    (tmp_path / "lib" / "pyproject.toml").write_text(
        '[project]\nname = "hf-mcp"\nversion = "9.9.9"\n', encoding="utf-8"
    )
    namespace = runpy.run_path(str(site / "__init__.py"))
    assert namespace["_read_local_pyproject_version"]() is None
    assert namespace["__version__"] == installed_version("hf-mcp")
