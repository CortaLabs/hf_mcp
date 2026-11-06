#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PACKAGE_ROOT="$(dirname "$SCRIPT_DIR")"
OUT_DIR="${1:-}"
PYTHON="${HF_BUILD_PYTHON:-python}"

if [[ -z "$OUT_DIR" || "$OUT_DIR" != /* ]]; then
  echo "Refusing build: output directory must be an absolute path." >&2
  exit 2
fi
if [[ ! -f "$PACKAGE_ROOT/pyproject.toml" ]]; then
  echo "Refusing build: expected pyproject.toml under package root." >&2
  exit 2
fi
if [[ ! -x "$(command -v "$PYTHON" || true)" ]]; then
  echo "Refusing build: configured Python interpreter is unavailable." >&2
  exit 2
fi

"$PYTHON" - "$PACKAGE_ROOT" "$OUT_DIR" "$PYTHON" <<'PY'
from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path
from zipfile import ZipFile

package_root = Path(sys.argv[1]).resolve(strict=True)
requested_out = Path(sys.argv[2])
python = sys.argv[3]
if not requested_out.is_absolute():
    raise SystemExit("Refusing build: output directory must be absolute.")
if requested_out.is_symlink():
    raise SystemExit("Refusing build: output directory may not be a symlink.")
out_dir = requested_out.resolve(strict=False)
home = Path.home().resolve()
if out_dir == Path("/") or out_dir == home or out_dir == package_root or out_dir in package_root.parents or package_root in out_dir.parents:
    raise SystemExit("Refusing build: unsafe output directory overlaps the home or product tree.")
if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
    raise SystemExit("Refusing build: output directory must be fresh and empty.")
out_dir.mkdir(parents=True, exist_ok=True)

ignored_names = {
    ".git", ".council", ".scribe", ".claude", ".codex", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", "__pycache__", ".github", "build", "dist",
}

def ignore(directory: str, names: list[str]) -> set[str]:
    ignored = set()
    for name in names:
        if name in ignored_names or name.endswith(".egg-info"):
            ignored.add(name)
        elif name.startswith(".") and name not in {".github"}:
            ignored.add(name)
    return ignored

with tempfile.TemporaryDirectory(prefix="hf-mcp-build-stage-") as stage_name:
    stage_root = Path(stage_name) / "product"
    shutil.copytree(package_root, stage_root, ignore=ignore)
    stage_out = Path(stage_name) / "artifacts"
    stage_out.mkdir()
    build = subprocess.run(
        [python, "-m", "build", "--sdist", "--wheel", "--no-isolation", "--outdir", str(stage_out), str(stage_root)],
        cwd=stage_root,
        check=False,
    )
    if build.returncode:
        raise SystemExit(build.returncode)

    sdists = sorted(stage_out.glob("*.tar.gz"))
    wheels = sorted(stage_out.glob("*.whl"))
    if len(sdists) != 1 or len(wheels) != 1:
        raise SystemExit("Build must produce exactly one wheel and one sdist.")
    twine = subprocess.run(
        [python, "-m", "twine", "check", str(wheels[0]), str(sdists[0])],
        cwd=stage_root,
        check=False,
    )
    if twine.returncode:
        raise SystemExit(twine.returncode)

    forbidden_dir_markers = ("/.council/", "/.scribe/", "/.claude/", "/.codex/")
    forbidden_file_names = {"tool_calls.jsonl", "AGENTS.md", "CLAUDE.md"}

    def audit_names(archive: Path, names: list[str]) -> None:
        normalized = [name.replace("\\", "/") for name in names]
        forbidden = []
        for name in normalized:
            parts = [part for part in name.split("/") if part not in ("", ".")]
            if any(marker in f"/{'/'.join(parts)}/" for marker in forbidden_dir_markers):
                forbidden.append(name)
            elif parts and parts[-1] in forbidden_file_names:
                forbidden.append(name)
        if forbidden:
            raise SystemExit(f"Forbidden release payload found in {archive.name}: {', '.join(forbidden)}")

    with tarfile.open(sdists[0], "r:gz") as archive:
        sdist_names = [member.name for member in archive.getmembers() if member.isfile()]
    with ZipFile(wheels[0]) as archive:
        wheel_names = archive.namelist()
    audit_names(sdists[0], sdist_names)
    audit_names(wheels[0], wheel_names)

    version = tomllib.loads(
        (stage_root / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    required_modules = {"__init__.py", "cli.py", "server.py", "dispatcher.py", "transport.py"}
    required_skills = {
        "hf-api-v2", "hf-mcp", "hf-mcp-bootstrap", "hf-mcp-reads", "hf-mcp-writes", "hf-mycode",
    }
    for label, names in (("sdist", sdist_names), ("wheel", wheel_names)):
        if not any(name.endswith(f"hf_mcp-{version}.dist-info/METADATA") for name in names):
            if not any(name.endswith(f"hf_mcp-{version}.egg-info/PKG-INFO") for name in names) and not any(name.endswith("/PKG-INFO") for name in names):
                raise SystemExit(f"{label} is missing expected {version} package metadata.")
        if label == "sdist":
            package_root = next(
                name.split("/", 1)[0]
                for name in names
                if name.endswith("/PKG-INFO")
            )
            if version not in package_root:
                raise SystemExit("sdist root does not match the expected package version.")
            package_prefix = f"{package_root}/"
            required = [
                "README.md", "pyproject.toml", "MANIFEST.in", "config.example.yaml",
                "export_manifest.toml", "scripts/build_release_dists.sh", "scripts/smoke_installed.py",
            ]
            missing = [item for item in required if f"{package_prefix}{item}" not in names]
            missing.extend(f"{package_prefix}src/hf_mcp/{module}" for module in required_modules if f"{package_prefix}src/hf_mcp/{module}" not in names)
            missing.extend(f"{package_prefix}skills/{skill}/SKILL.md" for skill in required_skills if f"{package_prefix}skills/{skill}/SKILL.md" not in names)
            if f"{package_prefix}skills/hf-mycode/references/MYCODE_REFERENCE.md" not in names:
                missing.append("skills/hf-mycode/references/MYCODE_REFERENCE.md")
            if not any(name.startswith(package_prefix + "src/hf_mcp/data/") and name.endswith("forums_index.json") for name in names):
                missing.append("src/hf_mcp/data/forums_index.json")
            if not any(name.startswith(package_prefix + "docs/") and name.endswith(".md") for name in names):
                missing.append("docs/*.md")
        else:
            required = ["hf_mcp/__init__.py", "hf_mcp/cli.py", "hf_mcp/server.py", "hf_mcp/dispatcher.py", "hf_mcp/transport.py"]
            missing = [item for item in required if item not in names]
            if not any(name.startswith("hf_mcp/data/") and name.endswith("forums_index.json") for name in names):
                missing.append("hf_mcp/data/forums_index.json")
            if not any(".data/data/docs/" in name and name.endswith(".md") for name in names):
                missing.append("docs/*.md wheel data")
            for skill in required_skills:
                if not any(name.endswith(f".data/data/skills/{skill}/SKILL.md") for name in names):
                    missing.append(f"skills/{skill}/SKILL.md wheel data")
            if not any(name.endswith(".data/data/skills/hf-mycode/references/MYCODE_REFERENCE.md") for name in names):
                missing.append("skills/hf-mycode/references/MYCODE_REFERENCE.md wheel data")
        if missing:
            raise SystemExit(f"{label} is missing required payload: {', '.join(missing)}")

    for artifact in (*sdists, *wheels):
        shutil.copy2(artifact, out_dir / artifact.name)

print(f"Archive audit passed for one {version} wheel and one sdist.")
PY
