# Client Integration

This guide focuses on desktop MCP client launch patterns for `hf-mcp` across Linux/macOS, Windows, and Windows-to-WSL setups. For ChatGPT's private tunnel flow, see [`chatgpt_tunnel.md`](chatgpt_tunnel.md).

## Core launch forms

### Direct command

```bash
hf-mcp serve
```

### Module command

```bash
python -m hf_mcp serve
```

Both forms are supported. Use the one that best matches your client's command runner.

## Environment-specific command patterns

### Virtualenv or conda interpreter launch

When the desktop client can call a specific Python interpreter, use that interpreter directly:

```bash
/path/to/python -m hf_mcp serve
```

Examples include virtualenv `.venv/bin/python`, conda env interpreters, or pyenv-managed interpreters.

### Native Windows Python

If `hf-mcp` is installed in a Windows Python environment:

```powershell
py -3.11 -m hf_mcp serve
```

Equivalent explicit interpreter form:

```powershell
C:\Path\To\Python\python.exe -m hf_mcp serve
```

## Windows desktop client -> WSL bridge

Some desktop clients run on Windows while you want `hf-mcp` to execute inside WSL.

Path-neutral pattern:

```powershell
wsl.exe -d <DistroName> --cd /opt/hf-mcp /opt/hf-mcp-venv/bin/python -m hf_mcp serve
```

Path-neutral Windows-to-WSL invocation (adjust distro and paths for your machine):

```powershell
wsl.exe -d <DistroName> --cd /opt/hf-mcp /opt/hf-mcp-venv/bin/python -m hf_mcp serve
```

Notes:

- Distro name, HF MCP installation path, and interpreter path vary by setup; replace the `/opt/...` examples with local paths.
- Desktop clients differ in how they launch shells/commands; use the exact invocation shape your client expects.
- Keep secrets in environment/config files, not inline in desktop client JSON.

## Separate MCP client configurations

Illustrative JSON snippet (adjust command args for your environment):

```json
{
  "mcpServers": {
    "hf-mcp": {
      "command": "python",
      "args": ["-m", "hf_mcp", "serve"]
    }
  }
}
```

Windows-to-WSL variant often sets `command` to `wsl.exe` and passes distro/working-directory/interpreter in `args`.

Keep each consumer's MCP configuration separate. If a client supports an
explicit `--config` argument, give that client its own `hf-mcp` YAML path and
preserve the policies already configured for other agents. Do not replace an
agent's config to add ChatGPT. The ChatGPT guide uses `full_api` by default in
its dedicated config to expose all currently supported tools; the package's
general fallback profile is `reader`. A smaller four-tool `custom` read profile
is optional. Do not use the CLI `--profile` override with the custom capability
selection: the override replaces its YAML overlays. The tunnel guide includes
both configurations.

## Write-safety reminders for client integrations

- Live writes remain fail-closed unless `confirm_live=true` is provided.
- `scheduled_at` in draft artifacts is metadata only; there is no built-in scheduler that auto-runs writes later.
- HF quote/entity canonicalization on live writes is expected HF sanitization behavior, not a transport bypass target.
