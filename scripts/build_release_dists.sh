#!/usr/bin/env bash
# Build the sdist and wheel into an absolute, fresh OUT_DIR, then check them.
set -euo pipefail

OUT_DIR="${1:-}"
PYTHON="${HF_BUILD_PYTHON:-python}"
if [[ "$OUT_DIR" != /* ]]; then
  echo "Refusing build: output directory must be an absolute path." >&2
  exit 2
fi
if [[ -d "$OUT_DIR" && -n "$(ls -A "$OUT_DIR")" ]]; then
  echo "Refusing build: output directory must be empty." >&2
  exit 2
fi
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# --no-isolation: build backends come pinned from the dev extra, so the release build uses the reviewed toolchain instead of fetching one.
"$PYTHON" -m build --sdist --wheel --no-isolation --outdir "$OUT_DIR" .
"$PYTHON" -m twine check "$OUT_DIR"/*

"$PYTHON" - "$OUT_DIR" <<'PY'
import sys
from pathlib import Path
from zipfile import ZipFile

(wheel,) = Path(sys.argv[1]).glob("*.whl")
names = ZipFile(wheel).namelist()
missing = {"hf_mcp/__init__.py", "hf_mcp/data/forums_index.json"} - set(names)
stray = [n for n in names if n.split("/")[0] in {"tests", "docs", ".council"} or ".data/" in n]
if missing or stray:
    raise SystemExit(f"{wheel.name}: missing {sorted(missing)}, unexpected {stray}")
print(f"{wheel.name}: payload ok")
PY
