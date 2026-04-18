#!/usr/bin/env python3
"""Fail release publishing when the target package version already exists on PyPI."""

from __future__ import annotations

import json
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

PACKAGE_NAME = "hf-mcp"


def main() -> int:
    package_root = Path(__file__).resolve().parents[1]
    pyproject_path = package_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    project = data.get("project", {})
    pyproject_name = str(project.get("name", ""))
    version = str(project.get("version", ""))

    if pyproject_name != PACKAGE_NAME:
        print(
            f"Refusing release check: expected package name {PACKAGE_NAME!r} in {pyproject_path}, "
            f"found {pyproject_name!r}.",
            file=sys.stderr,
        )
        return 1

    if not version:
        print(f"Refusing release check: missing project.version in {pyproject_path}.", file=sys.stderr)
        return 1

    url = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(
                f"PyPI package {PACKAGE_NAME!r} does not exist yet; version {version} is available."
            )
            return 0
        print(f"PyPI version check failed for {PACKAGE_NAME!r}: HTTP {exc.code}.", file=sys.stderr)
        return 1
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(
            f"PyPI version check failed for {PACKAGE_NAME!r}: {exc.__class__.__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    releases = payload.get("releases", {})
    if version in releases:
        print(
            f"Refusing to publish duplicate PyPI release: {PACKAGE_NAME} {version} already exists.",
            file=sys.stderr,
        )
        print(
            "Bump products/hf_mcp/pyproject.toml to a new version before releasing.",
            file=sys.stderr,
        )
        return 1

    print(f"PyPI version check passed: {PACKAGE_NAME} {version} is not published yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
