# Export Boundary

`hf-mcp` is published from a product subtree. Export is allowlist-based and
package-local.

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
- Concrete vs placeholder status is documented in `coverage_matrix.md` and
  summarized in `tool_overview.md`.
- Browse semantics are anchored: `threads.read` is forum-anchored (`fid`
  required, optional `tid`), and `posts.read` is thread-anchored (`tid`
  required, optional `pid`).
- Extended helper semantics are browse-first optional-filter:
  `contracts.read` => `cid` (optional), optional `uid`;
  `disputes.read` => `cdid` (optional), optional `uid`;
  legacy alias `did` remains compatibility-only;
  `bratings.read` => optional `uid`;
  `sigmarket.market.read` => optional `uid`;
  `sigmarket.order.read` => `oid` (optional), optional `uid`.
- MCP tool outputs are MCP content plus protocol-level `structuredContent`.
- Published tool metadata/annotations make this explicit via
  `x-hf-output-default=readable`, `x-hf-output-readable=additive`, and
  `x-hf-output-field-bundles=separate_from_rendering`.
- Readable formatting is additive only and must not replace structured output;
  raw upstream payloads remain additive MCP resources when requested.
- Live-write validation stays manual: no automated live writes.
- Concrete writes require `confirm_live=true`.
- Manual checks in this wave remain limited to:
  - `posts.reply` on `TID 6083735`
  - at most one `threads.create` in `FID 375`
- No Bytes live writes are in scope for this wave.
- Placeholder writes remain out of scope in this wave:
  `contracts.write`, `sigmarket.write`, `admin.high_risk.write`.
- Sigmarket live validation status is unchanged: current account/token remains
  scope-limited, so sigmarket probes are expected to return
  `INVALID_KEY_SCOPE_3`; this is scope enforcement, not a repaired write path.

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

## Cross-links

- Safety posture and guarded-write controls: [security_model.md](security_model.md)
- Configuration policy and precedence: [configuration.md](configuration.md)
- Auth bootstrap and callback workflow: [auth_bootstrap.md](auth_bootstrap.md)
- Request/response examples: [examples.md](examples.md)
