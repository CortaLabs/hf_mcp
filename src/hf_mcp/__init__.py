"""Public package root for the standalone hf-mcp launch surface."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path

__all__ = ["__version__"]

_DIST_NAME = "hf-mcp"
_UNKNOWN_VERSION = "0.0.0+unknown"


def _read_local_pyproject_version() -> str | None:
    """Return the pyproject version only when running from an hf-mcp source tree.

    A source checkout has the ``src/hf_mcp`` layout with the project's own
    ``pyproject.toml`` two levels up. Installed builds never match, so an
    unrelated ``pyproject.toml`` near site-packages cannot influence the result.
    """
    package_dir = Path(__file__).resolve().parent
    if package_dir.parent.name != "src":
        return None
    pyproject_path = package_dir.parents[1] / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8")).get(
            "project", {}
        )
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None
    version = project.get("version")
    if project.get("name") != _DIST_NAME or not isinstance(version, str) or not version:
        return None
    return version


@lru_cache(maxsize=1)
def _resolve_version() -> str:
    source_version = _read_local_pyproject_version()
    if source_version is not None:
        return source_version
    try:
        return distribution_version(_DIST_NAME)
    except PackageNotFoundError:
        return _UNKNOWN_VERSION


__version__ = _resolve_version()
