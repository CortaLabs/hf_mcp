# hf-mcp

`hf-mcp` is a standalone MCP server package for the Hack Forums API v2.

## Product target

The product target is full documented Hack Forums API coverage, tracked in
`docs/coverage_matrix.md`. Operator-facing truth today is split into two groups:

- concrete shipped helpers: `me.read`, `users.read`, `forums.read`,
  `threads.read`, `posts.read`, `bytes.read`, `contracts.read`,
  `disputes.read`, `bratings.read`, `sigmarket.market.read`,
  `sigmarket.order.read`, `admin.high_risk.read`, `threads.create`,
  `posts.reply`, `bytes.transfer`, `bytes.deposit`, `bytes.withdraw`,
  `bytes.bump`
- registry-shipped placeholder rows (documented coverage tracking, not live-write
  promises): `contracts.write`, `sigmarket.write`, `admin.high_risk.write`

Anchored browse contract after `HFMCP-INT-03`:

- `threads.read` is forum-anchored (`fid` required, optional `tid` narrowing)
- `posts.read` is thread-anchored (`tid` required, optional `pid` narrowing)

MCP tool outputs are JSON-first (dict payloads) today. Any future readable output
must be additive and must not break existing JSON consumers.

Live testing boundary: no automated live writes. Manual live checks only on
`TID 6083735` or `FID 375`, ideally using one testing thread total.

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
