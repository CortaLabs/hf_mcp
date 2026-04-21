# hf-mcp

`hf-mcp` is a standalone MCP server package for the Hack Forums API v2.

## Install

```bash
pip install hf-mcp
```

## Entrypoints

- `hf-mcp` (aliases `hf-mcp serve`)
- `python -m hf_mcp`
- `hf-mcp setup init`
- `hf-mcp auth bootstrap`
- `hf-mcp doctor`
- `hf-mcp serve`

## Default local paths

- config: `~/.config/hf_mcp/config.yaml`
- token store: `~/.config/hf_mcp/token.json`

Path overrides:

- `HF_MCP_CONFIG` for config path
- `HF_MCP_ENV_FILE` for explicit `.env` path
- `HF_MCP_TOKEN_PATH` for token path (unless YAML `token_path` is set)

Full precedence and policy split are documented in [`docs/configuration.md`](docs/configuration.md).

## Quick start

```bash
pip install hf-mcp
hf-mcp setup init
hf-mcp auth bootstrap
hf-mcp doctor
hf-mcp serve
```

Module launch equivalent:

```bash
python -m hf_mcp serve
```

## Safety and release posture

- Read paths and guarded writes are documented publicly, with fail-closed behavior for concrete writes via `confirm_live=true`.
- `sigmarket.write` remains a placeholder/later-lane row and is not a concrete callable helper today.
- Detailed release-boundary and limitation truth is owned by [`docs/export_boundary.md`](docs/export_boundary.md).

## Docs map

- [`docs/configuration.md`](docs/configuration.md)
- [`docs/auth_bootstrap.md`](docs/auth_bootstrap.md)
- [`docs/tool_overview.md`](docs/tool_overview.md)
- [`docs/coverage_matrix.md`](docs/coverage_matrix.md)
- [`docs/examples.md`](docs/examples.md)
- [`docs/security_model.md`](docs/security_model.md)
- [`docs/export_boundary.md`](docs/export_boundary.md)
- [`docs/oauth_callback.html`](docs/oauth_callback.html)
