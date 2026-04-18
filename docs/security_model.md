# Security Model

`hf-mcp` is a networked MCP server for live HF API calls, so every enabled tool
should be treated as open-world input/output.

## Core controls

- Capability policy is fail-closed. Unknown capability or parameter-family names
  fail config load.
- Parameter-family pruning keeps schema exposure aligned with runtime validation.
- Documented write helpers require explicit `confirm_live = true`.
- Capability and parameter families can restrict user exposure for high-risk
  rows such as `contract`, `sigmarket`, and `admin/high-risk` helpers.

## Secret handling

- Keep OAuth client credentials and access tokens in private runtime storage.
- Do not commit credentials into config files, docs, or tests.
- Rotate credentials if they are ever exposed.

## Operational guidance

- Start from read-oriented exposure when validating a new deployment.
- Enable write families deliberately and verify each path with test coverage.
- Keep audit logs outside the tracked package tree.
