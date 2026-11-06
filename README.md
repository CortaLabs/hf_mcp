# hf-mcp

`hf-mcp` is an MCP server for the Hack Forums API v2. It lets MCP clients such as
Claude Desktop, Codex, or ChatGPT read forums, threads, posts, users, and Bytes data,
draft and check MyCode locally, and post replies or threads when you explicitly
allow it. It is for Hack Forums members who build with MCP clients and want a small,
inspectable server that runs under their own API app and never writes without confirmation.

## Install

```bash
pip install hf-mcp
```

Requires Python 3.11 or newer.

## Quickstart

1. Create a Hack Forums API v2 developer app in your user control panel. Use
   `https://cortalabs.github.io/hf_mcp/oauth_callback.html` as the redirect URL, or host
   [`docs/oauth_callback.html`](docs/oauth_callback.html) yourself.
2. Put your app credentials in a `.env` file or your shell:

   ```bash
   HF_MCP_CLIENT_ID=your_app_client_id
   HF_MCP_CLIENT_SECRET=your_app_client_secret
   HF_MCP_EXTERNAL_REDIRECT_URI=https://cortalabs.github.io/hf_mcp/oauth_callback.html
   ```

3. Set up, authorize, check, and serve:

   ```bash
   hf-mcp setup init        # writes ~/.config/hf_mcp/config.yaml (profile: reader)
   hf-mcp auth bootstrap    # OAuth flow, saves ~/.config/hf_mcp/token.json
   hf-mcp doctor            # local readiness check, no network calls
   hf-mcp serve             # starts the MCP server on stdio
   ```

4. Point your MCP client at the server. For most desktop clients the command is
   `hf-mcp` with the argument `serve`; `python -m hf_mcp serve` is equivalent. Windows,
   WSL, and virtualenv launch forms are in
   [`docs/client_integration.md`](docs/client_integration.md).

Other commands: `hf-mcp auth status` shows token and config state.

## Tools

Clients list these tools with underscores instead of dots (for example
`threads_read` for `threads.read`). These docs and the config file use the
dotted names; both refer to the same tool.
Full details and selectors are in [`docs/tool_overview.md`](docs/tool_overview.md).

**Read** (talk to the Hack Forums API)

- `me.read`, `users.read`
- `forums.index` (packaged forum catalog, no IDs needed), `forums.read`, `threads.read`, `posts.read`
- `bytes.read`
- `contracts.read`, `disputes.read`, `bratings.read`
- `sigmarket.market.read`, `sigmarket.order.read`
- `admin.high_risk.read` (needs privileged scope)

**Draft** (local only, nothing is sent to Hack Forums)

- `formatting.preflight` checks how MyCode or Markdown converts to Hack Forums MyCode and can save a draft
- `drafts.list`, `drafts.read`, `drafts.update`, `drafts.delete`

**Write** (live requests, each requires `confirm_live=true`)

- `threads.create`, `posts.reply`
- `bytes.transfer`, `bytes.deposit`, `bytes.withdraw`, `bytes.bump`

Not available: contract writes, Signature Market writes, admin writes, and direct
private message content. Private message counters are returned by `me.read` when
advanced account fields are enabled.

## Safety model

A profile in your config decides which tools the server registers: `reader` (reads
and local drafts, the default), `forum_operator` (adds `threads.create` and
`posts.reply`), `full_api` (all 24 tools), or `custom` (start empty, opt in per
capability). Tools outside the profile are not registered at all. Write tools fail
closed: without `confirm_live=true` no request leaves your machine. Drafts are local
files, and a draft's `scheduled_at` is only a note; `hf-mcp` has no scheduler and never
posts on its own. Failures come back as MCP errors with a stable code, such as
`RATE_LIMITED` or `WRITE_OUTCOME_UNKNOWN`, and never echo tokens or upstream error
text. Links and images with unsafe schemes such as `javascript:` are rejected before
anything is posted. See [`docs/security_model.md`](docs/security_model.md).

## Reading output

Read tools return readable text plus normalized JSON in `structuredContent`. Pass
`output_mode` as `readable` (default), `structured`, or `raw`, or set
`include_raw_payload=true` to attach the exact upstream response as an extra resource.
Results carry an `_hf_flow.next_actions` hint so a client can chain
`forums.index` → `forums.read` → `threads.read` → `posts.read` without guessing IDs.
`_hf_flow.server.version` reports the running hf-mcp version, which is handy in clients
that do not show the MCP handshake.
Examples are in [`docs/examples.md`](docs/examples.md).

## Configuration

Config lives at `~/.config/hf_mcp/config.yaml` and the token at
`~/.config/hf_mcp/token.json`. Override them with `HF_MCP_CONFIG`, `HF_MCP_ENV_FILE`,
and `HF_MCP_TOKEN_PATH`. Policy goes in YAML and secrets stay in `.env` or the
environment. See [`docs/configuration.md`](docs/configuration.md) and
[`config.example.yaml`](config.example.yaml).

## ChatGPT

ChatGPT can connect through an outbound-only private tunnel. Setup, profile choice, and
rollback are in [`docs/chatgpt_tunnel.md`](docs/chatgpt_tunnel.md).

## Documentation

- [Configuration](docs/configuration.md)
- [Auth bootstrap](docs/auth_bootstrap.md)
- [Client integration](docs/client_integration.md)
- [ChatGPT tunnel](docs/chatgpt_tunnel.md)
- [Tool overview](docs/tool_overview.md)
- [Coverage matrix](docs/coverage_matrix.md)
- [Examples](docs/examples.md)
- [Security model](docs/security_model.md)
- [Changelog](CHANGELOG.md)

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m mypy
```

Tests use temporary config, token, and draft paths and block outbound network access.
A source checkout reports the version from its `pyproject.toml`; an installed build
reports its distribution metadata version.

## License

MIT. See [`LICENSE`](LICENSE).
