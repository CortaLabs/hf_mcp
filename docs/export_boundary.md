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
