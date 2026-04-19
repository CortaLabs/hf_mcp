# Export Boundary

`hf-mcp` is published from a product subtree. Export is allowlist-based.

## Authoritative manifest

`export_manifest.toml` is the machine-readable allowlist for exported files.
Allowed entries are scoped to `products/hf_mcp/` only.

## Included public surfaces

- package metadata and launch docs (`pyproject.toml`, `README.md`)
- example configuration (`config.example.yaml`)
- public documentation (`docs/**`)
- package source (`src/hf_mcp/**`)
- package tests (`tests/**`)

## Operator contract truth

- Concrete shipped helpers include core reads plus implemented extended reads:
  `contracts.read`, `disputes.read`, `bratings.read`,
  `sigmarket.market.read`, `sigmarket.order.read`, `admin.high_risk.read`,
  and `bytes.read`.
- Placeholder rows are only rows without concrete handlers today and currently
  map to later-lane write placeholders (`contracts.write`, `sigmarket.write`,
  `admin.high_risk.write`) tracked for documented API coverage.
- Tool inventory source of truth is `src/hf_mcp/registry.py` (`_MATRIX_ROWS`).
- Concrete vs placeholder status is documented in `docs/coverage_matrix.md` and
  summarized for operators in `docs/tool_overview.md`.
- Browse semantics are anchored: `threads.read` is forum-anchored (`fid`
  required, optional `tid`), and `posts.read` is thread-anchored (`tid`
  required, optional `pid`).
- MCP tool outputs are JSON-first dict payloads today. Any future readable
  formatting must be additive only and cannot replace JSON output.
- Live-write validation stays manual: no automated live writes. Manual checks
  are limited to `TID 6083735` or `FID 375`, ideally one testing thread total.

## Boundary guarantees

- Root-level repository assets are outside the export boundary.
- Internal orchestration/planning assets are outside the export boundary.
- Release packaging should fail if any allowlist entry leaves the
  `products/hf_mcp/` subtree.
- Runtime policy is YAML-first: non-secret policy belongs in `config.yaml`.
- `.env` is reserved for secrets and machine-local overrides; it must not define
  profile/capability/parameter policy.
- Token-store location must be an absolute path outside the tracked repository
  tree.
