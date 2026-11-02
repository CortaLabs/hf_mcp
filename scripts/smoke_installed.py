#!/usr/bin/env python3
"""Build and exercise fresh offline installs of the hf-mcp release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tomllib
import venv
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZipFile

from packaging.requirements import Requirement
from packaging.version import Version

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[a-zA-Z0-9.+-]*)$")
REVISION_PATTERN = re.compile(r"^(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})$")
REQUIRED_SKILLS = (
    "hf-api-v2",
    "hf-mcp",
    "hf-mcp-bootstrap",
    "hf-mcp-reads",
    "hf-mcp-writes",
    "hf-mycode",
)
REQUIRED_MODULES = (
    "__init__.py",
    "cli.py",
    "server.py",
    "dispatcher.py",
    "transport.py",
)
FORBIDDEN_DIRS = ("/.council/", "/.scribe/", "/.claude/", "/.codex/")
FORBIDDEN_NAMES = {"tool_calls.jsonl", "AGENTS.md", "CLAUDE.md"}

_NETWORK_GUARD = """\
import socket
def _blocked(*_args, **_kwargs):
    raise RuntimeError('outbound network is disabled in the installed smoke')
socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.socket.sendto = _blocked
socket.create_connection = _blocked
"""

_BUILD_REQUIREMENT_PROBE = """\
import importlib.metadata as metadata
import json
import sys
from importlib.metadata import PackageNotFoundError
from packaging.requirements import Requirement
from packaging.version import Version

requirements = json.loads(sys.argv[1])
versions = {}
failures = []
for raw_requirement in requirements:
    requirement = Requirement(raw_requirement)
    try:
        version = metadata.version(requirement.name)
    except PackageNotFoundError:
        version = None
    versions[requirement.name] = version
    if version is None or Version(version) not in requirement.specifier:
        failures.append(f"{raw_requirement} (installed {version or 'missing'})")
if failures:
    raise SystemExit("unsatisfied build-system requirements: " + ", ".join(failures))
print(json.dumps(versions, sort_keys=True))
"""

_INSTALLED_PROBE = r'''from __future__ import annotations
import importlib.metadata
import importlib.resources
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
REQUIRED_SKILLS = ("hf-api-v2", "hf-mcp", "hf-mcp-bootstrap", "hf-mcp-reads", "hf-mcp-writes", "hf-mycode")
def blocked(*_args, **_kwargs):
    raise RuntimeError("outbound network is disabled in the installed smoke")
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked
socket.create_connection = blocked
import hf_mcp
from hf_mcp.cli import main as cli_main
from hf_mcp.mycode import markdown_to_mycode

expected_version = os.environ["HF_BUILD_EXPECTED_VERSION"]
assert hf_mcp.__version__ == expected_version
assert importlib.metadata.version("hf-mcp") == expected_version
origin = Path(hf_mcp.__file__).resolve()
site_packages = Path(next(path for path in sys.path if path.endswith("site-packages"))).resolve()
assert origin.is_relative_to(site_packages), (str(origin), str(site_packages))
dist = importlib.metadata.distribution("hf-mcp")
direct_url = dist.read_text("direct_url.json")
if direct_url:
    assert not json.loads(direct_url).get("dir_info", {}).get("editable", False)
for name in ("serve_stdio", "_MCPServerToolAdapter"):
    assert hasattr(__import__("hf_mcp.server", fromlist=[name]), name)
assert hasattr(__import__("hf_mcp.schemas", fromlist=["build_tool_schema"]), "build_tool_schema")
data = importlib.resources.files("hf_mcp").joinpath("data/forums_index.json")
assert data.is_file() and json.loads(data.read_text(encoding="utf-8"))
prefix = Path(sys.prefix)
docs = sorted((prefix / "docs").glob("*.md"))
assert docs and any(path.name == "configuration.md" for path in docs)
for skill in ("hf-api-v2", "hf-mcp", "hf-mcp-bootstrap", "hf-mcp-reads", "hf-mcp-writes", "hf-mycode"):
    assert (prefix / "skills" / skill / "SKILL.md").is_file(), skill
assert (prefix / "skills" / "hf-mycode" / "references" / "MYCODE_REFERENCE.md").is_file()

def run_cli(arguments):
    from contextlib import redirect_stdout
    from io import StringIO
    saved = sys.argv
    output = StringIO()
    try:
        sys.argv = ["hf-mcp", *arguments]
        with redirect_stdout(output):
            try:
                cli_main()
            except SystemExit as exc:
                if exc.code not in (0, None):
                    raise
    finally:
        sys.argv = saved
    return output.getvalue()

assert expected_version in run_cli(["--version"])
assert "usage" in run_cli(["--help"]).lower()
entrypoint = Path(sys.prefix) / ("Scripts/hf-mcp.exe" if os.name == "nt" else "bin/hf-mcp")
assert entrypoint.is_file()
formatted = markdown_to_mycode("**portable**")
assert "[b]portable[/b]" in formatted

SERVER = r"""import json, os, socket, sys
def blocked(*_args, **_kwargs):
    raise RuntimeError("outbound network is disabled in the installed smoke")
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.socket.sendto = blocked
socket.create_connection = blocked
from hf_mcp.config import HFMCPSettings
from hf_mcp.dispatcher import RuntimeBundle
from hf_mcp.token_store import TokenBundle
from hf_mcp.transport import HFTransport
import hf_mcp.server as server
from hf_mcp.mycode import markdown_to_mycode
class OfflineTokens:
    def require_bundle(self):
        return TokenBundle(access_token="synthetic", token_type="Bearer", scope=frozenset({"read"}))
calls = []
def offline_post(route, payload, headers):
    assert route == "/read"
    assert headers["Authorization"] == "Bearer synthetic"
    asks = payload["asks"]
    root = next(iter(asks))
    assert root in {"forums", "threads", "posts"}
    calls.append(root)
    row = {"fid": 123, "tid": 456, "pid": 789, "subject": "Offline fixture"}
    if root == "posts":
        assert asks["posts"].get("message") is True
        row["message"] = "[b]Post body[/b]"
    elif root == "threads":
        row["firstpost"] = {"pid": 789, "message": "[b]Thread body[/b]"}
    return {root: [row]}
transport = HFTransport(token_store=OfflineTokens(), base_url="https://example.invalid")
transport._post_json = offline_post
settings = HFMCPSettings(
    profile="custom",
    enabled_capabilities=frozenset({"forums.index", "forums.read", "threads.read", "posts.read"}),
    enabled_parameter_families=frozenset({"selectors.forum", "selectors.thread", "selectors.post", "filters.pagination", "fields.posts.body"}),
)
server.resolve_runtime_bundle = lambda _: RuntimeBundle(transport=transport, settings=settings)
assert "[b]portable[/b]" in markdown_to_mycode("**portable**")
server.serve_stdio(settings)
"""

def run_stdio(variant):
    env = {"PATH": os.defpath, "HOME": os.environ["HOME"], "HF_MCP_CONFIG": os.environ["HF_MCP_CONFIG"], "HF_MCP_TOKEN_PATH": os.environ["HF_MCP_TOKEN_PATH"], "HF_MCP_DRAFT_DIR": os.environ["HF_MCP_DRAFT_DIR"], "PYTHONUNBUFFERED": "1"}
    process = subprocess.Popen([sys.executable, "-I", "-c", SERVER, variant], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=os.getcwd(), env=env, text=True)
    assert process.stdin is not None and process.stdout is not None
    counter = 0
    def send(method, params, notification=False):
        nonlocal counter
        counter += 1
        if variant == "modern":
            params = {**params, "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}}
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            message["id"] = counter
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        if notification:
            return {}
        line = process.stdout.readline()
        assert line, "stdio server exited before a response"
        response = json.loads(line)
        assert response.get("id") == counter and "error" not in response, response
        return response["result"]
    try:
        if variant == "legacy":
            initialized = send("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "hf-build-smoke", "version": "1"}})
            assert initialized["protocolVersion"] == "2025-11-25"
            send("notifications/initialized", {}, notification=True)
        tools = {tool["name"] for tool in send("tools/list", {})["tools"]}
        assert tools == {"forums_index", "forums_read", "threads_read", "posts_read"}
        for name, arguments in (
            ("forums_read", {"fid": 123}),
            ("threads_read", {"fid": 123, "body_format": "markdown"}),
            (
                "posts_read",
                {
                    "tid": 456,
                    "include_post_body": True,
                    "body_format": "markdown",
                },
            ),
        ):
            read_result = send("tools/call", {"name": name, "arguments": arguments})
            assert not read_result.get("isError", False)
            assert isinstance(read_result.get("structuredContent"), dict)
            assert "Offline fixture" in json.dumps(read_result["structuredContent"])
            if name == "threads_read":
                assert read_result["structuredContent"]["threads"][0]["firstpost"][
                    "message"
                ] == "**Thread body**"
            elif name == "posts_read":
                assert read_result["structuredContent"]["posts"][0]["message"] == "**Post body**"
        formatted = markdown_to_mycode("**portable**")
        assert "[b]portable[/b]" in formatted
        return {"wire": variant, "tools": len(tools), "read": "pass", "formatter": "pass"}
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        stderr = process.stderr.read() if process.stderr is not None else ""
        if process.returncode:
            raise RuntimeError("stdio probe failed")

print(json.dumps({"origin": str(origin), "site_packages": str(site_packages), "version": hf_mcp.__version__, "docs": len(docs), "skills": len(REQUIRED_SKILLS), "cli": "pass", "data": "pass", "formatter": "pass", "wires": [run_stdio("legacy"), run_stdio("modern")]}, sort_keys=True))
'''


class SmokeFailure(RuntimeError):
    def __init__(
        self,
        step: str,
        message: str,
        *,
        check_record: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.step = step
        self.check_record = check_record


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_paths(args: argparse.Namespace) -> dict[str, Path]:
    script_root = Path(__file__).resolve().parents[1]
    paths = {
        "artifact_dir": Path(args.artifact_dir),
        "work_dir": Path(args.work_dir),
        "wheelhouse": Path(args.wheelhouse),
        "receipt": Path(args.receipt),
    }
    for label, path in paths.items():
        if not path.is_absolute():
            raise SmokeFailure("arguments", f"{label} must be an absolute path")
        if path.is_symlink():
            raise SmokeFailure("arguments", f"{label} may not be a symlink")
        resolved = path.resolve(strict=False)
        if (
            resolved == script_root
            or resolved in script_root.parents
            or script_root in resolved.parents
        ):
            raise SmokeFailure("arguments", f"{label} overlaps the product source")
        paths[label] = resolved
    directories = ("artifact_dir", "work_dir", "wheelhouse")
    for index, first in enumerate(directories):
        for second in directories[index + 1 :]:
            left, right = paths[first], paths[second]
            if left == right or left in right.parents or right in left.parents:
                raise SmokeFailure(
                    "arguments", "artifact, work and wheelhouse paths must be separate"
                )
        receipt = paths["receipt"]
        directory = paths[first]
        if (
            receipt == directory
            or receipt in directory.parents
            or directory in receipt.parents
        ):
            raise SmokeFailure(
                "arguments",
                "receipt path must be outside artifact, work and wheelhouse directories",
            )
    if paths["work_dir"].exists() and (
        not paths["work_dir"].is_dir() or any(paths["work_dir"].iterdir())
    ):
        raise SmokeFailure("arguments", "work directory must be fresh and empty")
    if paths["receipt"].exists():
        raise SmokeFailure("arguments", "receipt path already exists")
    for label in ("artifact_dir", "wheelhouse"):
        if not paths[label].is_dir():
            raise SmokeFailure("arguments", f"{label} must be an existing directory")
    if not paths["wheelhouse"].is_dir() or not any(paths["wheelhouse"].iterdir()):
        raise SmokeFailure(
            "arguments", "wheelhouse must contain provisioned offline packages"
        )
    paths["work_dir"].mkdir(parents=True, exist_ok=True)
    paths["receipt"].parent.mkdir(parents=True, exist_ok=True)
    return paths


def _archive_parts(name: str, *, directory: bool = False) -> tuple[str, ...]:
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise SmokeFailure("archive_audit", "absolute archive member path is forbidden")
    raw_parts = normalized.split("/")
    if directory and raw_parts and raw_parts[-1] == "":
        raw_parts.pop()
    if (
        not raw_parts
        or any(part in {"", ".", ".."} for part in raw_parts)
        or raw_parts[0].endswith(":")
    ):
        raise SmokeFailure("archive_audit", "unsafe archive member path is forbidden")
    return tuple(PurePosixPath(normalized).parts)


def _archive_names(artifacts: dict[str, Path]) -> tuple[list[str], list[str]]:
    sdist_names: list[str] = []
    with tarfile.open(artifacts["sdist"], "r:gz") as archive:
        for member in archive.getmembers():
            _archive_parts(member.name, directory=member.isdir())
            if (
                member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
            ):
                raise SmokeFailure(
                    "archive_audit",
                    "sdist must contain only regular files and directories",
                )
            if member.isfile():
                sdist_names.append(member.name.replace("\\", "/"))
    wheel_names: list[str] = []
    with ZipFile(artifacts["wheel"]) as archive:
        for wheel_member in archive.infolist():
            _archive_parts(wheel_member.filename, directory=wheel_member.is_dir())
            if wheel_member.is_dir():
                continue
            wheel_names.append(wheel_member.filename.replace("\\", "/"))
    for archive_path, names in (
        (artifacts["sdist"], sdist_names),
        (artifacts["wheel"], wheel_names),
    ):
        for name in names:
            parts = [part for part in name.split("/") if part not in ("", ".")]
            if any(marker in f"/{'/'.join(parts)}/" for marker in FORBIDDEN_DIRS) or (
                parts and parts[-1] in FORBIDDEN_NAMES
            ):
                raise SmokeFailure(
                    "archive_audit",
                    f"forbidden archive member found in {archive_path.name}",
                )
    return sdist_names, wheel_names


def _extract_sdist(sdist: Path, destination: Path, version: str) -> Path:
    if destination.exists() or destination.is_symlink():
        raise SmokeFailure(
            "archive_extract", "sdist extraction directory must be fresh"
        )
    destination.mkdir(parents=True)
    extraction_root = destination.resolve(strict=True)
    seen: set[tuple[str, ...]] = set()
    root_name: str | None = None
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        package_info = next(
            (
                member
                for member in members
                if member.isfile() and member.name.endswith("/PKG-INFO")
            ),
            None,
        )
        if package_info is None:
            raise SmokeFailure("archive_extract", "sdist package metadata is missing")
        root_parts = _archive_parts(package_info.name)
        root_name = root_parts[0]
        if version not in root_name:
            raise SmokeFailure("archive_extract", "sdist root version is inconsistent")

        for member in members:
            parts = _archive_parts(member.name, directory=member.isdir())
            if parts in seen:
                raise SmokeFailure(
                    "archive_extract", "sdist contains duplicate member paths"
                )
            seen.add(parts)
            if parts[0] != root_name:
                raise SmokeFailure(
                    "archive_extract", "sdist contains multiple root directories"
                )
            if (
                member.issym()
                or member.islnk()
                or not (member.isfile() or member.isdir())
            ):
                raise SmokeFailure(
                    "archive_extract",
                    "sdist must contain only regular files and directories",
                )
            target = destination.joinpath(*parts)
            resolved_target = target.resolve(strict=False)
            if not resolved_target.is_relative_to(extraction_root):
                raise SmokeFailure(
                    "archive_extract", "sdist member escapes extraction directory"
                )
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise SmokeFailure("archive_extract", "sdist member could not be read")
            try:
                with source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
            except OSError as exc:
                raise SmokeFailure(
                    "archive_extract", "sdist member could not be written"
                ) from exc

    source_root = destination / root_name
    if not source_root.is_dir() or not (source_root / "pyproject.toml").is_file():
        raise SmokeFailure("archive_extract", "extracted sdist is not a Python project")
    return source_root


def _check_payload(
    artifacts: dict[str, Path],
    sdist_names: list[str],
    wheel_names: list[str],
    version: str,
) -> None:
    sdist_root = next(
        name.split("/", 1)[0] for name in sdist_names if name.endswith("/PKG-INFO")
    )
    if version not in sdist_root:
        raise SmokeFailure(
            "version_audit", "sdist root does not match expected version"
        )
    sdist_prefix = f"{sdist_root}/"
    sdist_required = [
        "README.md",
        "pyproject.toml",
        "MANIFEST.in",
        "config.example.yaml",
        "export_manifest.toml",
        "scripts/build_release_dists.sh",
        "scripts/smoke_installed.py",
        "skills/hf-mycode/references/MYCODE_REFERENCE.md",
    ]
    missing = [
        name for name in sdist_required if f"{sdist_prefix}{name}" not in sdist_names
    ]
    missing.extend(
        f"{sdist_prefix}src/hf_mcp/{name}"
        for name in REQUIRED_MODULES
        if f"{sdist_prefix}src/hf_mcp/{name}" not in sdist_names
    )
    missing.extend(
        f"{sdist_prefix}skills/{skill}/SKILL.md"
        for skill in REQUIRED_SKILLS
        if f"{sdist_prefix}skills/{skill}/SKILL.md" not in sdist_names
    )
    if not any(
        name.startswith(sdist_prefix + "src/hf_mcp/data/")
        and name.endswith("forums_index.json")
        for name in sdist_names
    ):
        missing.append("sdist/forums_index.json")
    if not any(
        name.startswith(sdist_prefix + "docs/") and name.endswith(".md")
        for name in sdist_names
    ):
        missing.append("sdist/docs/*.md")
    wheel_required = [f"hf_mcp/{name}" for name in REQUIRED_MODULES]
    missing.extend(
        f"wheel/{name}" for name in wheel_required if name not in wheel_names
    )
    if not any(
        name.startswith("hf_mcp/data/") and name.endswith("forums_index.json")
        for name in wheel_names
    ):
        missing.append("wheel/forums_index.json")
    if not any(
        ".data/data/docs/" in name and name.endswith(".md") for name in wheel_names
    ):
        missing.append("wheel/docs/*.md")
    for skill in REQUIRED_SKILLS:
        if not any(
            f".data/data/skills/{skill}/SKILL.md" in name for name in wheel_names
        ):
            missing.append(f"wheel/skills/{skill}/SKILL.md")
    if not any(
        name.endswith(".data/data/skills/hf-mycode/references/MYCODE_REFERENCE.md")
        for name in wheel_names
    ):
        missing.append("wheel/skills/hf-mycode/references/MYCODE_REFERENCE.md")
    if missing:
        raise SmokeFailure("resource_audit", "required package payload is missing")
    for kind, artifact, names, marker in (
        ("wheel", artifacts["wheel"], wheel_names, f"{version}"),
        ("sdist", artifacts["sdist"], sdist_names, f"{version}"),
    ):
        if (
            not artifact.name.endswith((".whl" if kind == "wheel" else ".tar.gz"))
            or marker not in artifact.name
        ):
            raise SmokeFailure(
                "version_audit", f"{kind} filename does not match expected version"
            )
        metadata_names = [
            name
            for name in names
            if name.endswith("/METADATA") or name.endswith("/PKG-INFO")
        ]
        if not metadata_names:
            raise SmokeFailure("version_audit", f"{kind} metadata is missing")
        if kind == "wheel":
            with ZipFile(artifact) as archive:
                text = archive.read(metadata_names[0]).decode("utf-8", errors="replace")
        else:
            with tarfile.open(artifact, "r:gz") as archive:
                handle = archive.extractfile(metadata_names[0])
                if handle is None:
                    raise SmokeFailure("version_audit", "sdist metadata is unreadable")
                text = handle.read().decode("utf-8", errors="replace")
        if f"Version: {version}" not in text:
            raise SmokeFailure(
                "version_audit", f"{kind} metadata version does not match"
            )


def _redact_text(value: str) -> str:
    value = re.sub(
        r"(?i)\b(authorization|client_secret|password|secret|token)\b\s*[:=]\s*[^\s,;]+",
        r"\1=<redacted>",
        value,
    )
    value = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer <redacted>", value)
    value = re.sub(r"(?<![\w:])/(?:[^\s/'\";,]+/)*[^\s/'\";,]+", "<path>", value)
    return value


def _safe_diagnostic(stderr: str) -> str:
    detail = "\n".join(line.strip() for line in stderr.splitlines() if line.strip())
    detail = re.sub(r"\x1b\[[0-9;]*m", "", detail)
    detail = _redact_text(detail)
    return " | ".join(detail.splitlines()[-3:])[:400]


def _run(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    records: list[dict[str, Any]],
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    check_record = {
        "name": name,
        "argv": _redact_argv(argv),
        "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
        "exit_code": result.returncode,
        "result": "pass" if result.returncode == 0 else "fail",
        "diagnostic": _safe_diagnostic(result.stderr) if result.returncode else None,
    }
    records.append(check_record)
    if result.returncode:
        detail = check_record["diagnostic"]
        message = f"check failed: {name}"
        if detail:
            message += f": {detail}"
        raise SmokeFailure(name, message, check_record=check_record)
    return result


def _filesystem_snapshot(roots: tuple[Path, ...]) -> dict[str, tuple[str, str]]:
    snapshot = {}
    for index, root in enumerate(roots):
        if root.is_symlink() or not root.is_dir():
            raise SmokeFailure(
                "state_snapshot", "synthetic state directory is unavailable"
            )
        for path in sorted(root.rglob("*")):
            relative = f"{index}/{path.relative_to(root).as_posix()}"
            if path.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(path))
            elif path.is_dir():
                snapshot[relative] = ("directory", "")
            elif path.is_file():
                snapshot[relative] = ("file", _sha256(path))
            else:
                snapshot[relative] = ("other", "")
    return snapshot


def _run_state_guarded_probe(
    name: str,
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    records: list[dict[str, Any]],
    state_roots: tuple[Path, ...],
) -> subprocess.CompletedProcess[str]:
    before = _filesystem_snapshot(state_roots)
    result = _run(name, argv, cwd=cwd, env=env, records=records, timeout=120)
    after = _filesystem_snapshot(state_roots)
    changed = before != after
    check_record = {
        "name": f"{name}_state_preservation",
        "argv": _redact_argv(argv),
        "argv_sha256": hashlib.sha256("\0".join(argv).encode()).hexdigest(),
        "exit_code": 1 if changed else 0,
        "result": "fail" if changed else "pass",
        "diagnostic": (
            "installed probe changed synthetic config/token/draft filesystem state"
            if changed
            else None
        ),
    }
    records.append(check_record)
    if changed:
        raise SmokeFailure(
            "state_leak",
            "installed probe changed synthetic config/token/draft filesystem state",
            check_record=check_record,
        )
    return result


def _redact_argv(argv: list[str]) -> list[str]:
    return [
        Path(item).name if item.startswith("/") else _redact_text(item) for item in argv
    ]


def _guarded_module(python: Path, module: str, arguments: list[str]) -> list[str]:
    wrapper = (
        _NETWORK_GUARD
        + "\nimport runpy, sys\nsys.argv = ["
        + repr(module)
        + ", *sys.argv[1:]]\nrunpy.run_module("
        + repr(module)
        + ", run_name='__main__', alter_sys=True)\n"
    )
    return [str(python), "-I", "-c", wrapper, *arguments]


def _guarded_code(python: Path, source: str, arguments: list[str]) -> list[str]:
    return [str(python), "-I", "-c", _NETWORK_GUARD + "\n" + source, *arguments]


def _probe_command(python: Path, probe_path: Path) -> list[str]:
    return [str(python), "-I", str(probe_path)]


def _offline_env(home: Path, expected_version: str, state: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    config = state / "config.yaml"
    token = state / "token.json"
    drafts = state / "drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    (home / ".config" / "hf_mcp" / "drafts").mkdir(parents=True, exist_ok=True)
    config.write_text(
        "profile: custom\nenabled_capabilities: [forums.index, forums.read, threads.read, posts.read]\nenabled_parameter_families: [selectors.forum, selectors.thread, selectors.post, filters.pagination, fields.posts.body]\n",
        encoding="utf-8",
    )
    return {
        "PATH": os.defpath,
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "HF_MCP_CONFIG": str(config),
        "HF_MCP_TOKEN_PATH": str(token),
        "HF_MCP_DRAFT_DIR": str(drafts),
        "HF_BUILD_EXPECTED_VERSION": expected_version,
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_CONFIG_FILE": os.devnull,
        "PYTHONUNBUFFERED": "1",
    }


def _build_system_requirements(source_root: Path) -> list[str]:
    try:
        project = tomllib.loads(
            (source_root / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SmokeFailure(
            "sdist_build_requirements", "staged pyproject.toml is unreadable"
        ) from exc
    build_system = project.get("build-system")
    requirements = (
        build_system.get("requires") if isinstance(build_system, dict) else None
    )
    if (
        not isinstance(requirements, list)
        or not requirements
        or not all(
            isinstance(requirement, str) and requirement.strip()
            for requirement in requirements
        )
    ):
        raise SmokeFailure(
            "sdist_build_requirements", "staged build-system.requires is invalid"
        )
    return requirements


def _build_requirement_install_args(
    wheelhouse: Path, requirements: list[str]
) -> list[str]:
    return [
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--upgrade",
        *requirements,
    ]


def _build_requirement_failures(
    requirements: list[str], installed_versions: dict[str, str | None]
) -> list[str]:
    failures = []
    for raw_requirement in requirements:
        requirement = Requirement(raw_requirement)
        version = installed_versions.get(requirement.name)
        if version is None or Version(version) not in requirement.specifier:
            failures.append(f"{raw_requirement} (installed {version or 'missing'})")
    return failures


def _smoke(args: argparse.Namespace) -> dict[str, Any]:
    if not VERSION_PATTERN.fullmatch(args.expected_version):
        raise SmokeFailure("arguments", "expected version is invalid")
    if not REVISION_PATTERN.fullmatch(args.source_revision):
        raise SmokeFailure(
            "arguments", "source revision must be a full hexadecimal commit id"
        )
    paths = _validate_paths(args)
    artifacts_found = list(paths["artifact_dir"].iterdir())
    wheels = sorted(path for path in artifacts_found if path.name.endswith(".whl"))
    sdists = sorted(path for path in artifacts_found if path.name.endswith(".tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1 or len(artifacts_found) != 2:
        raise SmokeFailure(
            "artifact_inventory",
            "artifact directory must contain exactly one wheel and one sdist",
        )
    artifacts = {"wheel": wheels[0], "sdist": sdists[0]}
    sdist_names, wheel_names = _archive_names(artifacts)
    _check_payload(artifacts, sdist_names, wheel_names, args.expected_version)
    wheelhouse_files = [
        path for path in paths["wheelhouse"].iterdir() if path.is_file()
    ]
    if not wheelhouse_files:
        raise SmokeFailure("wheelhouse", "offline wheelhouse contains no package files")

    work = paths["work_dir"]
    records: list[dict[str, Any]] = []
    install_records: list[dict[str, Any]] = []
    sdist_source = _extract_sdist(
        artifacts["sdist"], work / "sdist-source", args.expected_version
    )
    probe_path = work / "installed_probe.py"
    probe_path.write_text(_INSTALLED_PROBE, encoding="utf-8")
    artifact_receipts: dict[str, dict[str, Any]] = {}
    for kind, artifact in artifacts.items():
        artifact_receipts[kind] = {
            "name": artifact.name,
            "sha256": _sha256(artifact),
            "size_bytes": artifact.stat().st_size,
        }

    sdist_wheelhouse = work / "sdist-wheelhouse"
    sdist_wheelhouse.mkdir()
    build_requirements = _build_system_requirements(sdist_source)
    build_env = _offline_env(
        work / "build-home", args.expected_version, work / "build-state"
    )
    build_env["PIP_FIND_LINKS"] = str(paths["wheelhouse"])
    build_python = (
        work
        / "build-venv"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    venv.EnvBuilder(with_pip=True, clear=False).create(build_python.parent.parent)
    build_setup = (
        (
            "sdist_build_tool",
            "pip",
            [
                "install",
                "--no-index",
                "--find-links",
                str(paths["wheelhouse"]),
                "build",
            ],
        ),
        (
            "sdist_build_dependencies",
            "pip",
            _build_requirement_install_args(paths["wheelhouse"], build_requirements),
        ),
    )
    for name, module, module_args in build_setup:
        _run(
            name,
            _guarded_module(build_python, module, module_args),
            cwd=work,
            env=build_env,
            records=records,
        )

    requirement_probe = _run(
        "sdist_build_requirements",
        _guarded_code(
            build_python,
            _BUILD_REQUIREMENT_PROBE,
            [json.dumps(build_requirements)],
        ),
        cwd=work,
        env=build_env,
        records=records,
    )
    try:
        build_backend_versions = json.loads(
            requirement_probe.stdout.strip().splitlines()[-1]
        )
    except (json.JSONDecodeError, IndexError) as exc:
        raise SmokeFailure(
            "sdist_build_requirements", "backend version probe returned no result"
        ) from exc
    build_requirement_failures = _build_requirement_failures(
        build_requirements, build_backend_versions
    )
    if build_requirement_failures:
        raise SmokeFailure(
            "sdist_build_requirements",
            "declared build requirements are unsatisfied: "
            + ", ".join(build_requirement_failures),
        )

    _run(
        "sdist_rebuild",
        _guarded_module(
            build_python,
            "build",
            [
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(sdist_wheelhouse),
                str(sdist_source),
            ],
        ),
        cwd=work,
        env=build_env,
        records=records,
    )
    rebuilt = sorted(sdist_wheelhouse.glob("*.whl"))
    if len(rebuilt) != 1:
        raise SmokeFailure("sdist_rebuild", "sdist must produce exactly one wheel")
    rebuilt_names = []
    with ZipFile(rebuilt[0]) as archive:
        rebuilt_names = archive.namelist()
    _check_payload(
        {"wheel": rebuilt[0], "sdist": artifacts["sdist"]},
        sdist_names,
        rebuilt_names,
        args.expected_version,
    )
    rebuilt_metadata = next(
        (name for name in rebuilt_names if name.endswith(".dist-info/METADATA")), None
    )
    if rebuilt_metadata is None:
        raise SmokeFailure("sdist_rebuild", "rebuilt wheel metadata is missing")
    with ZipFile(rebuilt[0]) as archive:
        rebuilt_text = archive.read(rebuilt_metadata).decode("utf-8", errors="replace")
    if f"Version: {args.expected_version}" not in rebuilt_text or not any(
        name.endswith("forums_index.json") for name in rebuilt_names
    ):
        raise SmokeFailure("sdist_rebuild", "rebuilt wheel version or resource differs")

    for kind, wheel in (("wheel", artifacts["wheel"]), ("sdist-derived", rebuilt[0])):
        env_name = kind.replace("-", "_")
        venv_root = work / f"{env_name}-venv"
        python = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        venv.EnvBuilder(with_pip=True, clear=False).create(venv_root)
        state = work / f"{env_name}-state"
        env = _offline_env(work / f"{env_name}-home", args.expected_version, state)
        env["PIP_FIND_LINKS"] = str(paths["wheelhouse"])
        _run(
            f"{env_name}_install",
            _guarded_module(
                python,
                "pip",
                [
                    "install",
                    "--no-index",
                    "--find-links",
                    str(paths["wheelhouse"]),
                    str(wheel),
                ],
            ),
            cwd=work,
            env=env,
            records=records,
        )
        _run(
            f"{env_name}_pip_check",
            _guarded_module(python, "pip", ["check"]),
            cwd=work,
            env=env,
            records=records,
        )
        probe_result = _run_state_guarded_probe(
            f"{env_name}_installed_probe",
            _probe_command(python, probe_path),
            cwd=work,
            env=env,
            records=records,
            state_roots=(state, work / f"{env_name}-home"),
        )
        try:
            probe = json.loads(probe_result.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            raise SmokeFailure(
                f"{env_name}_installed_probe",
                "installed probe returned no structured result",
            ) from exc
        install_records.append(
            {
                "kind": kind,
                "python": sys.version.split()[0],
                "probe": probe,
                "wheel_sha256": _sha256(wheel),
                "install_provenance": "local wheel; --no-index; fresh venv",
            }
        )

    return {
        "schema_version": "hf-mcp-installed-smoke.v1",
        "status": "passed",
        "source_revision": args.source_revision.lower(),
        "expected_version": args.expected_version,
        "actual_version": args.expected_version,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "sdk_version": metadata.version("mcp"),
        "tool_versions": {
            name: metadata.version(name)
            for name in ("build", "pip", "setuptools", "wheel")
        },
        "sdist_build_system_requires": build_requirements,
        "sdist_build_backend_versions": build_backend_versions,
        "artifacts": artifact_receipts,
        "rebuilt_wheel": {
            "name": rebuilt[0].name,
            "sha256": _sha256(rebuilt[0]),
            "size_bytes": rebuilt[0].stat().st_size,
        },
        "checks": records,
        "installations": install_records,
        "protocol_variants": ["legacy", "modern"],
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--wheelhouse", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--receipt", required=True)
    return parser.parse_args()


def _failure_receipt_document(
    args: argparse.Namespace, error: Exception
) -> dict[str, Any]:
    failed_step = error.step if isinstance(error, SmokeFailure) else "smoke"
    diagnostic = (
        str(error)[:300]
        if isinstance(error, SmokeFailure)
        else f"smoke failed with {type(error).__name__}"
    )
    source_revision = getattr(args, "source_revision", "")
    expected_version = getattr(args, "expected_version", "")
    return {
        "schema_version": "hf-mcp-installed-smoke.v1",
        "status": "failed",
        "source_revision": source_revision
        if REVISION_PATTERN.fullmatch(source_revision)
        else None,
        "expected_version": expected_version
        if VERSION_PATTERN.fullmatch(expected_version)
        else None,
        "failed_step": failed_step,
        "diagnostic": diagnostic,
        "failed_check": error.check_record if isinstance(error, SmokeFailure) else None,
    }


def main() -> int:
    args = _arguments()
    try:
        # Parent-side guard protects orchestration and archive processing too.
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_sendto = socket.socket.sendto
        original_create_connection = socket.create_connection

        def blocked(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("outbound network is disabled in the installed smoke")

        socket.socket.connect = blocked  # type: ignore[assignment]
        socket.socket.connect_ex = blocked  # type: ignore[assignment]
        socket.socket.sendto = blocked  # type: ignore[assignment]
        socket.create_connection = blocked  # type: ignore[assignment]
        try:
            receipt = _smoke(args)
        finally:
            socket.socket.connect = original_connect  # type: ignore[assignment]
            socket.socket.connect_ex = original_connect_ex  # type: ignore[assignment]
            socket.socket.sendto = original_sendto  # type: ignore[assignment]
            socket.create_connection = original_create_connection  # type: ignore[assignment]
        receipt_path = Path(args.receipt)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": "passed",
                    "receipt": receipt_path.name,
                    "checks": len(receipt["checks"]),
                }
            )
        )
        return 0
    except (
        SmokeFailure,
        OSError,
        subprocess.SubprocessError,
        tarfile.TarError,
        ValueError,
    ) as exc:
        failure = _failure_receipt_document(args, exc)
        failed_step = failure["failed_step"]
        diagnostic = failure["diagnostic"]
        path = Path(args.receipt)
        product_root = Path(__file__).resolve().parents[1]
        resolved_path = path.resolve(strict=False)
        output_dirs = [
            Path(getattr(args, name)).resolve(strict=False)
            for name in ("artifact_dir", "work_dir", "wheelhouse")
        ]
        safe_receipt = (
            path.is_absolute()
            and not path.exists()
            and not path.is_symlink()
            and resolved_path != product_root
            and resolved_path not in product_root.parents
            and product_root not in resolved_path.parents
            and resolved_path != Path("/")
            and resolved_path != Path.home().resolve()
            and all(
                resolved_path not in directory.parents
                and directory not in resolved_path.parents
                for directory in output_dirs
            )
        )
        if safe_receipt:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(
                    json.dumps(failure, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
        print(
            json.dumps(
                {"status": "failed", "step": failed_step, "diagnostic": diagnostic}
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
