# Changelog

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
