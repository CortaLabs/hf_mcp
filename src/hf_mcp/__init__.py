"""Public package root for the standalone hf-mcp launch surface."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
import tomllib

__all__ = ["__version__"]

_DIST_NAME = "hf-mcp"
_UNKNOWN_VERSION = "0.0.0+unknown"


def _read_local_pyproject_version() -> str | None:
    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None

    version = pyproject.get("project", {}).get("version")
    return version if isinstance(version, str) and version else None


@lru_cache(maxsize=1)
def _resolve_version() -> str:
    local_version = _read_local_pyproject_version()
    if local_version is not None:
        return local_version
    try:
        return distribution_version(_DIST_NAME)
    except PackageNotFoundError:
        return _UNKNOWN_VERSION


__version__ = _resolve_version()
