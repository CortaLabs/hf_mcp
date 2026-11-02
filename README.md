# hf-mcp

`hf-mcp` is a standalone MCP server package for the Hack Forums API v2.

Current release line: `0.4.6`.

The PyPI publisher workflow runs only on an explicit manual dispatch. Export
boundary checks also resolve files from a standalone `hf-mcp` product checkout.

Version 0.4.6 combines complete Draft 2020-12 input-schema publication and
validation before SDK argument parsing with pinned development tooling and
offline child-process checks. Local schema references resolve only within the
supplied schema. Invalid values such as numeric strings, booleans used as
integers, and unknown fields are rejected; omitted optional values keep their
existing defaults.

Version 0.4.4 pinned the development, test, and build tools and added isolated
source checks for the export boundary. Version 0.4.2 publishes and enforces the
complete Draft 2020-12 input schema while preserving original JSON types; it
declared `jsonschema>=4.20.0` and `referencing>=0.30.0` as direct runtime
dependencies. The 0.4.1 release tightened the published schemas for Bytes
deposits and withdrawals and kept `hf.doctor` as a local catalog fact without
exposing a callable diagnostic tool. The 0.4.0 release recorded canonical tool
facts and derived locality metadata and behavior hints from the registry.

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

## Desktop MCP clients

Desktop client wiring is first-class and documented in
[`docs/client_integration.md`](docs/client_integration.md), including:

- direct command launch (`hf-mcp serve`)
- module launch (`python -m hf_mcp serve`)
- virtualenv/conda launch forms
- native Windows Python launch
- Windows desktop client to WSL bridge examples (including Claude Desktop style)

## ChatGPT through a private tunnel

For the current ChatGPT Plugins custom MCP flow and an outbound-only OpenAI
Secure MCP Tunnel, see [`docs/chatgpt_tunnel.md`](docs/chatgpt_tunnel.md). The
ChatGPT connection uses `full_api` by default to expose all 24 currently
supported tools. A four-tool read-only profile is documented as an optional
restriction. Keep ChatGPT's config separate from other agents' settings; local
readiness and end-to-end ChatGPT acceptance are different checks.

## Default local paths

- config: `~/.config/hf_mcp/config.yaml`
- token store: `~/.config/hf_mcp/token.json`

Path overrides:

- `HF_MCP_CONFIG` for config path
- `HF_MCP_ENV_FILE` for explicit `.env` path
- `HF_MCP_TOKEN_PATH` for token path (unless YAML `token_path` is set)

Full precedence and policy split are documented in [`docs/configuration.md`](docs/configuration.md).

## Read output defaults

Read tools default to human-readable content while keeping canonical JSON for scripts.

- default mode: `readable`
- per-call override: `output_mode` (`readable`, `structured`, `raw`)
- additive raw payload toggle: `include_raw_payload`

Compatibility contract for read tools:

- `structuredContent` always carries normalized/canonical JSON for automation.
- `output_mode="readable"` is the human surface; for thread reads it includes the formatted thread body plus useful thread and first-post fields.
- `output_mode="structured"` keeps script-friendly `structuredContent` with terse text.
- raw payload remains available as an additive JSON resource when `output_mode="raw"` or `include_raw_payload=true`.

See [`docs/configuration.md`](docs/configuration.md) for `read_output_defaults` config and
[`docs/examples.md`](docs/examples.md) for concrete request/response examples.

## Compounding flow discovery

Use `forums.index` (alias `forums_index`) for root discovery when you do not yet
have IDs. This tool is backed by maintained package catalog data and can drift
from live Hack Forums state between package updates.

Concrete exploration path:

- `forums.index` -> `forums.read` -> `threads.read` -> `posts.read`
- `forums.read` still requires `fid`; it is not root discovery.
- `_hf_flow` is the machine-readable flow envelope key.
- `_hf_flow.next_actions` is the communication layer that lets one tool result
  feed the next tool call without an agent guessing selectors.
- `_hf_flow` currently ships on `forums.index`, core reads, supported
  extended reads (`bytes.read`, `contracts.read`, `disputes.read`,
  `bratings.read`, `sigmarket.market.read`, and `sigmarket.order.read`),
  local draft/preflight tools, and successful results from existing guarded
  write helpers after confirmed or stubbed execution.

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
    "include_post_body": true,
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
      {
        "pid": "62946370",
        "tid": "6324346",
        "subject": "The HF API MCP server",
        "message": "[size=xx-large][align=center][css=68]HF MCP Is Live..."
      }
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

## Development checks

Install the pinned development tools with `python -m pip install -e ".[dev]"`.
The source test lane uses temporary HF config, token, and draft paths. Pytest
blocks outbound IPv4 and IPv6 sockets while allowing Unix-domain IPC for local
asyncio stdio tests. This parent-process guard does not propagate to child
processes. Child probes must use the `isolated_child_context` fixture, which
supplies allowlisted synthetic state and installs a deny-all network guard
before the child imports the package. From the product checkout, run the
targeted source and quality checks with:

```bash
python -m pytest tests/test_export_boundary.py tests/test_entrypoints.py tests/test_onboarding_cli.py -q
python -m pytest tests/test_export_boundary.py -k hermetic -q --randomly-seed=1729 -n 2
python -m ruff check src/hf_mcp/__init__.py tests/conftest.py tests/test_export_boundary.py --select E4,E7,E9,F,I
python -m ruff format --check tests/conftest.py
python -m mypy src/hf_mcp/__init__.py
```

The version reported by a source checkout comes from its local `pyproject.toml`;
installed builds use distribution metadata and report `0.0.0+unknown` only when
that metadata is unavailable. These are development checks and do not publish a
distribution.

## Safety and release posture

- Read paths and guarded writes are documented publicly, with fail-closed behavior for concrete writes via `confirm_live=true`.
- Concrete write helpers currently exposed are `threads.create`, `posts.reply`, and Bytes write helpers (`bytes.transfer`, `bytes.deposit`, `bytes.withdraw`, `bytes.bump`) with repaired argument contracts.
- `scheduled_at` on draft artifacts is metadata for operator workflow only; `hf-mcp` does not ship a scheduler/queue that auto-executes future writes.
- HF API quote/entity canonicalization on live writes is treated as expected security/sanitization behavior, not a bypass target.
- Manual live validation in this wave is intentionally narrower: replies only on `TID 6083735` plus at most one `threads.create` in `FID 375`; no Bytes live writes.
- `contracts.write` is not exposed in this release because operator-approved sandbox proof is unavailable.
- Signature Market write operations and admin-only high-risk write operations are unsupported and unexposed.
- PM counters (`unreadpms`, `totalpms`) are available through `me.read` when Advanced Info fields are enabled; direct PM content operations are unsupported.
- Detailed release-boundary and limitation truth is owned by [`docs/export_boundary.md`](docs/export_boundary.md).

## Docs map

- [`docs/configuration.md`](docs/configuration.md)
- [`docs/auth_bootstrap.md`](docs/auth_bootstrap.md)
- [`docs/client_integration.md`](docs/client_integration.md)
- [`docs/chatgpt_tunnel.md`](docs/chatgpt_tunnel.md)
- [`docs/tool_overview.md`](docs/tool_overview.md)
- [`docs/coverage_matrix.md`](docs/coverage_matrix.md)
- [`docs/examples.md`](docs/examples.md)
- [`docs/hf_mcp_hf_launch_post.mycode`](docs/hf_mcp_hf_launch_post.mycode)
- [`docs/security_model.md`](docs/security_model.md)
- [`docs/export_boundary.md`](docs/export_boundary.md)
- [`docs/oauth_callback.html`](docs/oauth_callback.html)
