# hf-mcp

`hf-mcp` is a standalone MCP server package for the Hack Forums API v2.

## Product target

The product target is full documented Hack Forums API coverage. The registry and
coverage matrix include:

- core read helpers (`me`, `users`, `forums`, `threads`, `posts`)
- extended read helpers (`bytes`, `contracts`, `disputes`, `bratings`)
- later-lane documented read/write rows for `sigmarket`, `contract`, and
  documented `admin/high-risk` helpers
- documented write helpers (`threads.create`, `posts.reply`, `bytes.transfer`,
  `bytes.deposit`, `bytes.withdraw`, `bytes.bump`)

## Exposure model

Profiles and overlays are an exposure control layer for a specific user or
deployment. They do not redefine product scope. If a deployment disables a row,
that row still remains in the documented product coverage matrix.

## Launch surface

- console entrypoint: `hf-mcp`
- module entrypoint: `python -m hf_mcp`
- `hf-mcp` aliases `hf-mcp serve` (stdio runtime launch)
- `hf-mcp setup init` creates first-run local config and prints the next commands
- `hf-mcp doctor` validates local config/secrets/token readiness without network I/O
- `hf-mcp` ships the `mcp` runtime dependency required for the stdio launch path
- `hf-mcp serve` runs one stdio server instance and exits when the stdio client disconnects
- `hf-mcp serve` fails closed on invalid bootstrap state (config/secrets/token/runtime dependency)

## First run

```bash
pip install hf-mcp
hf-mcp setup init
```

Set secrets in your local environment (`.env` or shell):

```bash
export HF_MCP_CLIENT_ID=your_client_id
export HF_MCP_CLIENT_SECRET=your_client_secret
```

Configure OAuth redirect handling in your local environment (`.env` or shell):

```bash
# Hosted mode (recommended): register your hosted callback page URL in HF app settings.
# Host the static artifact at docs/oauth_callback.html (for example via GitHub Pages).
export HF_MCP_EXTERNAL_REDIRECT_URI=https://cortalabs.github.io/hf_mcp/oauth_callback.html

# The hosted callback page forwards to this fixed local target:
# http://127.0.0.1:8765/callback

# Legacy fallback (loopback only): if hosted mode is not used, set this instead.
export HF_MCP_REDIRECT_URI=http://127.0.0.1:8765/callback
```

Finish local bootstrap and readiness checks:

```bash
hf-mcp auth bootstrap
hf-mcp doctor
hf-mcp serve
```

## Source distribution boundary

`MANIFEST.in` defines a package-local source distribution boundary rooted in
`products/hf_mcp`. The source distribution includes package docs, tests, and
runtime source from this product subtree only.

## Documentation

- `docs/configuration.md`
- `docs/coverage_matrix.md`
- `docs/security_model.md`
- `docs/export_boundary.md`
