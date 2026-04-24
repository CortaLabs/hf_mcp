# Client Integration

This guide focuses on desktop MCP client launch patterns for `hf-mcp` across Linux/macOS, Windows, and Windows-to-WSL setups.

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
wsl.exe -d <DistroName> --cd /home/<linux-user>/<project-path> /home/<linux-user>/<python-path>/python -m hf_mcp serve
```

Example in the operator's Claude Desktop style (adjust distro/path/env for your own machine):

```powershell
wsl.exe -d Ubuntu-24.04 --cd /home/austin/projects/apps/hackforums_council/products/hf_mcp /home/austin/miniconda3/envs/uap/bin/python -m hf_mcp serve
```

Notes:

- Distro name, Linux home path, and interpreter path differ per user.
- Desktop clients differ in how they launch shells/commands; use the exact invocation shape your client expects.
- Keep secrets in environment/config files, not inline in desktop client JSON.

## Claude Desktop style MCP config shape

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

## Write-safety reminders for client integrations

- Live writes remain fail-closed unless `confirm_live=true` is provided.
- `scheduled_at` in draft artifacts is metadata only; there is no built-in scheduler that auto-runs writes later.
- HF quote/entity canonicalization on live writes is expected HF sanitization behavior, not a transport bypass target.
