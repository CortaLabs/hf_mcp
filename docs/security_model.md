# Security Model

`hf-mcp` is a networked MCP server for live HF API calls. Exposure is treated
as open-world input/output, so controls default to fail-closed behavior.

## Fail-closed controls

- Capability policy is fail-closed: unknown capability names or parameter-family
  names fail config load.
- Parameter-family pruning keeps schema exposure aligned with runtime validation.
- Guarded concrete writes require explicit `confirm_live=true`; missing or false
  confirmation fails closed before transport calls.
- High-risk families stay operator-gated (`contracts.*`, `sigmarket.*`,
  `admin.high_risk.*`) and should be enabled deliberately.

## Secret handling

- Keep OAuth client credentials and access tokens in private runtime storage.
- Keep non-secret runtime policy in YAML config; keep secrets in `.env` or
  machine-local environment variables.
- Do not commit credentials into docs, config examples, or tests.
- Rotate credentials immediately if exposure is suspected.

## Rollout and validation posture

- Start deployments read-first, then enable write families intentionally.
- Live-write validation remains manual and operator-controlled.
- Concrete writes require explicit `confirm_live=true`.
- Manual live validation in this wave is limited to `posts.reply` on
  `TID 6083735` and at most one `threads.create` in `FID 375`.
- No Bytes live writes are in scope for this wave.
- Placeholder writes remain out of scope in this wave:
  `contracts.write`, `sigmarket.write`, `admin.high_risk.write`.
- Keep audit logs outside the tracked package tree.

## Ownership and cross-links

- `security_model.md` owns safety posture, guarded-write expectations, and
  secret-handling guidance.
- `export_boundary.md` is canonical for package-export truth, JSON-first output
  framing, and current sigmarket scope limitation status.
- For configuration policy details, see [configuration.md](configuration.md).
- For auth bootstrap flow and callback behavior, see
  [auth_bootstrap.md](auth_bootstrap.md).
- For concrete request/response examples, see [examples.md](examples.md).
