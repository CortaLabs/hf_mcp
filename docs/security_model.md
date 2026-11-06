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

## Write policy

- Start read-only (the default `reader` profile), then enable write tools on purpose.
- The write tools are `threads.create`, `posts.reply`, `bytes.transfer`,
  `bytes.deposit`, `bytes.withdraw`, and `bytes.bump`. Each one needs
  `confirm_live=true` on the call; without it the request is refused before any
  network call.
- `contracts.write`, Signature Market writes, and admin-only writes are not
  available. Direct private message operations are not available either.
- Drafts are local files. `scheduled_at` on a draft is a note for you; `hf-mcp`
  never schedules or posts on its own.
- Hack Forums canonicalizes quotes and HTML entities in posted content (for
  example `&#34;` becomes `&quot;`). Treat that as the API sanitizing input, not
  something to work around.
- Calls that need an API scope your Hack Forums app does not have are refused by
  Hack Forums.
- Keep audit logs and the token file outside any repository you commit.

## Related docs

- [configuration.md](configuration.md): policy, paths, and precedence
- [auth_bootstrap.md](auth_bootstrap.md): OAuth bootstrap and callback behavior
- [examples.md](examples.md): request and response examples
- [tool_overview.md](tool_overview.md): the tool list
