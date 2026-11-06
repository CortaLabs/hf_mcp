#!/usr/bin/env python3
"""Install the built wheel into a fresh venv and talk to it over stdio."""

from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import tempfile
import tomllib
import venv
from pathlib import Path

PROFILES = ("reader", "full_api")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESPONSE_TIMEOUT_SECONDS = 30.0


def exchange(
    process: subprocess.Popen[str],
    method: str,
    params: dict,
    id_: int | None,
    timeout: float = RESPONSE_TIMEOUT_SECONDS,
) -> dict:
    """Send one JSON-RPC message; read the response when it has an id.

    The wait is bounded: a server that never answers fails the smoke run.
    """
    message = {"jsonrpc": "2.0", "method": method, "params": params}
    if id_ is not None:
        message["id"] = id_
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()
    if id_ is None:
        return {}
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        process.kill()
        raise SystemExit(f"server gave no answer to {method} within {timeout:g}s")
    line = process.stdout.readline()
    if not line:
        raise SystemExit(f"server exited before answering {method}")
    response = json.loads(line)
    if response.get("id") != id_ or "error" in response:
        raise SystemExit(f"{method} failed: {response}")
    return response["result"]


def list_tools(
    binary: Path, profile: str, env: dict[str, str], token: Path
) -> set[str]:
    command = [str(binary), "serve", "--profile", profile, "--token-path", str(token)]
    with subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
    ) as process:
        try:
            client = {"name": "hf-smoke", "version": "1"}
            exchange(
                process,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": client,
                },
                1,
            )
            exchange(process, "notifications/initialized", {}, None)
            return {
                tool["name"] for tool in exchange(process, "tools/list", {}, 2)["tools"]
            }
        finally:
            assert process.stdin is not None
            process.stdin.close()
            process.terminate()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, required=True)
    args = parser.parse_args()
    (wheel,) = args.dist_dir.glob("*.whl")
    version = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]

    with tempfile.TemporaryDirectory(prefix="hf-mcp-smoke-") as scratch:
        root = Path(scratch)
        venv.create(root / "venv", with_pip=True)
        bin_dir = root / "venv" / "bin"
        subprocess.run(
            [
                bin_dir / "pip",
                "install",
                "--quiet",
                "--disable-pip-version-check",
                wheel,
            ],
            check=True,
        )
        binary = bin_dir / "hf-mcp"

        home = root / "home"
        home.mkdir()
        token = root / "token.json"
        token.write_text(
            json.dumps(
                {"access_token": "synthetic", "token_type": "Bearer", "scope": ["read"]}
            )
        )
        token.chmod(0o600)
        env = {
            "PATH": os.defpath,
            "HOME": str(home),
            "HF_MCP_CLIENT_ID": "synthetic-id",
            "HF_MCP_CLIENT_SECRET": "synthetic-secret",
        }

        reported = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, check=True, env=env
        )
        if reported.stdout.split()[-1] != version:
            raise SystemExit(
                f"hf-mcp --version {reported.stdout.strip()!r} != project version {version}"
            )
        counts = {}
        for profile in PROFILES:
            tools = list_tools(binary, profile, env, token)
            if not tools:
                raise SystemExit(f"{profile}: tools/list returned no tools")
            counts[profile] = len(tools)
    print(f"smoke ok: hf-mcp {version}, tools per profile {counts}")


if __name__ == "__main__":
    main()
