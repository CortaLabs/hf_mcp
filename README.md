# hf-mcp

`hf-mcp` is a standalone MCP server package for the Hack Forums API v2.

## Product target

The product target is full documented Hack Forums API coverage. The registry and
coverage matrix include:

- generic transport rows (`transport.read`, `transport.write`)
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
- `hf-mcp` ships the `mcp` runtime dependency required for the stdio launch path
- `hf-mcp serve` runs one stdio server instance and exits when the stdio client disconnects
- `hf-mcp serve` fails closed on invalid bootstrap state (config/secrets/token/runtime dependency)

## Documentation

- `docs/configuration.md`
- `docs/coverage_matrix.md`
- `docs/security_model.md`
- `docs/export_boundary.md`
