# hf-mcp

`hf-mcp` is a standalone MCP server package for the Hack Forums API v2.

Current release line: `0.2`.

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

## Read output defaults

Read tools default to human-readable summaries while keeping canonical JSON for scripts.

- default mode: `readable`
- per-call override: `output_mode` (`readable`, `structured`, `raw`)
- additive raw payload toggle: `include_raw_payload`

Compatibility contract for read tools:

- `structuredContent` always carries normalized/canonical JSON for automation.
- `output_mode="structured"` keeps script-friendly `structuredContent` with terse text.
- raw payload remains available as an additive JSON resource when `output_mode="raw"` or `include_raw_payload=true`.

See [`docs/configuration.md`](docs/configuration.md) for `read_output_defaults` config and
[`docs/examples.md`](docs/examples.md) for concrete request/response examples.

## Automation usage

For automated clients, call read tools with `output_mode="structured"` when you only
need normalized fields, or `output_mode="raw"` / `include_raw_payload=true` when
you also need the exact upstream HF API payload as an additive MCP resource.

Example:

```json
{
  "tool": "posts.read",
  "arguments": {
    "tid": 6324346,
    "per_page": 1,
    "include_post_body": false,
    "output_mode": "raw",
    "include_raw_payload": true
  }
}
```

Expected protocol shape:

```json
{
  "content": [
    {"type": "text", "text": "posts.read returned 1 row(s)."},
    {"type": "resource", "resource": {"uri": "hf-mcp://raw/posts.read", "mimeType": "application/json"}}
  ],
  "structuredContent": {
    "posts": [
      {"pid": "62946370", "tid": "6324346", "subject": "The HF API MCP server"}
    ]
  }
}
```

## Quick start

```bash
pip install hf-mcp
hf-mcp setup init
hf-mcp auth bootstrap
hf-mcp doctor
hf-mcp serve
```

Before `auth bootstrap`, create your own Hack Forums API developer app in the HF
user control panel. You can use the hosted callback
`https://cortalabs.github.io/hf_mcp/oauth_callback.html` for
`HF_MCP_EXTERNAL_REDIRECT_URI`, or host `docs/oauth_callback.html` yourself and
use that HTTPS URL instead.

Module launch equivalent:

```bash
python -m hf_mcp serve
```

## Safety and release posture

- Read paths and guarded writes are documented publicly, with fail-closed behavior for concrete writes via `confirm_live=true`.
- Concrete write helpers currently exposed are `threads.create`, `posts.reply`, and Bytes write helpers (`bytes.transfer`, `bytes.deposit`, `bytes.withdraw`, `bytes.bump`) with repaired argument contracts.
- Manual live validation in this wave is intentionally narrower: replies only on `TID 6083735` plus at most one `threads.create` in `FID 375`; no Bytes live writes.
- Placeholder writes remain out of scope in this wave (`contracts.write`, `sigmarket.write`, `admin.high_risk.write`).
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
