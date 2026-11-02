# Changelog

## 0.4.2

- Publish and validate complete Draft 2020-12 tool input schemas before SDK parsing or handler invocation, preserving original JSON types and optional-argument behavior.
- Declare `jsonschema>=4.20.0` and `referencing>=0.30.0` as direct runtime dependencies for original-schema validation and local reference resolution.

## 0.4.1

- Require at least 100 Bytes for deposit and withdrawal schemas while preserving the 1-Byte transfer minimum.
- Keep `hf.doctor` as a local catalog fact with a closed empty argument schema and neutral object output metadata; it is not a callable diagnostic tool.

## 0.4.0

- Unify ToolSpec locality and parameter facts, derive hints and metadata, and add local `hf.doctor` catalog facts without exposing a callable diagnostic tool yet.

## 0.3.5

- Restrict the PyPI publisher workflow to explicit manual dispatches.
- Make export-boundary checks resolve from a standalone product checkout while preserving the manifest's product-prefixed allowlist.

## 0.3.4

- Route `me.read`, `users.read`, and `bratings.read` through generic `POST /api/v2/read` instead of helper URLs returning HTTP 404, including raw output mode.
- Route `posts.reply` through generic `POST /api/v2/write` once, preserving the existing asks payload and live-write confirmation guard.
- Add regression coverage for account and b-rating output modes and guarded reply request routing; preserve existing forum, thread, and post reads and MCP 2 discovery.
- Verify repaired account and b-rating reads with existing authentication. Reply routing and payload were verified offline only; no live write or announcement retry was performed for this repair.

## 0.3.3

- Document `full_api` as the default ChatGPT profile for all supported tools, with a custom read-only profile as an optional restriction.
- Add client configuration, secret-reference, health, lifecycle, rollback, and WSL availability guidance.
- Clarify that local server validation and a successful ChatGPT tool call are separate verification steps.

## 0.3.2

- Restore stdio startup using the official MCP SDK 2.3 `MCPServer` API; require `mcp>=2.3.0,<3`.
- Preserve numeric pagination bounds in published schemas and reject invalid pages and page sizes before handlers run.
- Send core forum, thread and post reads through the existing generic `POST /api/v2/read` route, preserving asks and public tool names.
- Preserve standard read-only annotations and structured results on modern and legacy stdio connections. HF custom metadata previously nested in annotations is published at tool-level `_meta` through the SDK `meta` argument.
- SDK wire serialization may omit null extension values, including the local catalog's `x-hf-helper-path: null` (no upstream helper). Populated HF metadata values are preserved.
- Publish existing open-object output schemas through the SDK-supported `Annotated[CallToolResult, OutputModel]` return annotation.
