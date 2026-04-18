#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="${1:-$PACKAGE_ROOT/dist/pypi}"

if [[ ! -f "$PACKAGE_ROOT/pyproject.toml" ]]; then
  echo "Refusing build: expected pyproject.toml under package root $PACKAGE_ROOT" >&2
  exit 1
fi

# Build from a clean package-local tree so stale build outputs cannot leak into
# release artifacts.
rm -rf \
  "$PACKAGE_ROOT/build" \
  "$PACKAGE_ROOT/dist" \
  "$PACKAGE_ROOT/.pytest_cache" \
  "$PACKAGE_ROOT/.ruff_cache" \
  "$PACKAGE_ROOT/src"/*.egg-info
find "$PACKAGE_ROOT" -type d -name '__pycache__' -prune -exec rm -rf {} +

mkdir -p "$OUT_DIR"

python -m build --sdist --wheel --outdir "$OUT_DIR" "$PACKAGE_ROOT"
python -m twine check "$OUT_DIR"/*

python - "$OUT_DIR" <<'PY'
from __future__ import annotations

import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

out_dir = Path(sys.argv[1]).resolve()

sdists = sorted(out_dir.glob("*.tar.gz"))
wheels = sorted(out_dir.glob("*.whl"))

if not sdists:
    raise SystemExit(f"No sdist artifact found in {out_dir}")
if not wheels:
    raise SystemExit(f"No wheel artifact found in {out_dir}")

forbidden_dir_markers = (
    "/.council/",
    "/.scribe/",
    "/.claude/",
    "/.codex/",
)
forbidden_file_names = {"tool_calls.jsonl", "AGENTS.md", "CLAUDE.md"}


def _is_forbidden(member_name: str) -> bool:
    normalized = member_name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]

    for marker in forbidden_dir_markers:
        if marker in f"/{'/'.join(parts)}/":
            return True

    if parts:
        tail = parts[-1]
        if tail in forbidden_file_names:
            return True
    return False


def _assert_clean(archive_name: str, names: list[str]) -> None:
    forbidden = sorted(name for name in names if _is_forbidden(name))
    if forbidden:
        rendered = "\n  - ".join(forbidden)
        raise SystemExit(
            f"Forbidden release payload found in {archive_name}:\n  - {rendered}"
        )


for sdist in sdists:
    with tarfile.open(sdist, "r:gz") as tf:
        names = [member.name for member in tf.getmembers()]
    _assert_clean(sdist.name, names)

for wheel in wheels:
    with ZipFile(wheel) as zf:
        names = zf.namelist()
    _assert_clean(wheel.name, names)

print(f"Archive audit passed for {len(sdists)} sdist(s) and {len(wheels)} wheel(s).")
PY
