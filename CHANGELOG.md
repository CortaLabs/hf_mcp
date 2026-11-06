# Changelog

All notable changes to hf-mcp are listed here, newest first.

## 0.7.2

Markdown now becomes the right MyCode: headings, numbered and nested lists, horizontal rules, inline code and escaped characters. Tables stay readable in a code block, and anything that cannot be carried over is reported. Raw bodies and code pass through unchanged. `formatting.preflight` and `drafts.read` return the full MyCode instead of a 500-character preview.

- Raw MyCode mixed into Markdown, including `[*]` list markers, is left as written, and `[css=N]` and `[hr]` are recognized tags.
- `formatting.preflight` and `drafts.read` report each construct that could not be carried over in `conversion_findings`, and a conversion that lost something no longer scores full integrity.
- Every result's `_hf_flow` now includes `server.name` and `server.version`, so clients that never show the MCP `initialize` handshake can still tell which hf-mcp version answered. `_hf_flow.version` is unchanged; it is the flow-format version.

## 0.7.1

Version 0.7.0 was tagged but never published to PyPI, so these changes ship as 0.7.1, together with one test-fixture fix.

Errors are now honest and safe. Hack Forums failures, including HTTP 200 responses that report a failure, come back as MCP errors with a stable code instead of looking like success. A write that times out is reported as "outcome unknown" and never retried. Upstream error bodies and tokens are no longer echoed. Lists and byte amounts come back exactly as Hack Forums sent them. Links and images with unsafe schemes such as `javascript:` or `data:` are rejected before posting. The token file is used only when it is a private regular file you own.

- Login refuses `HF_MCP_AUTHORIZE_URL` and `HF_MCP_TOKEN_URL` overrides that are not `https` URLs with a host, before it opens a browser or sends anything.
- A failed login token exchange now names the cause: rate limited, Hack Forums unavailable, rejected credentials, or another rejection.

Breaking:

- Error results are now `isError` with a `structuredContent.error` object, not free-text exception messages.
- Bytes amounts are returned as exact strings and are no longer truncated to integers.
- List rows keep Hack Forums order and are no longer re-sorted.
- Token files that are symlinks, not owned by you, or not mode 0600 are refused.
- In `raw` output mode, `structuredContent` values now use the same normalized string form as the other modes.

## 0.6.2

- Rewrote the README around installing, authorizing, and running the server, with the tools grouped as read, draft, and write and a short safety model.
- Removed development-process notes, test thread and forum IDs, and monorepo export wording from the docs, example config, and skills. The docs now state the actual policy: write tools exist only in profiles that enable them, and every live write needs `confirm_live=true`.
- Removed the export-boundary note and the launch-post draft from the docs.
- The MCP `initialize` response now reports the server name `hf-mcp` and the package version.
- Installed builds now report their version from package metadata. A source checkout still reports the version in its own `pyproject.toml`, and an unrelated `pyproject.toml` elsewhere on disk is ignored.
- Added project URLs, authors, a development-status classifier, and Python 3.12 and 3.13 classifiers to the package metadata.
- `.council/` is now ignored by git.

## 0.6.1

- Fix offline source-distribution rebuilds so they use the declared build requirements, and install the MyCode reference with the skills.

## 0.6.0

- Advertise purpose-specific MCP tool descriptions from the canonical registry while preserving tool names, schemas, and access policy.

## 0.4.6

- Preserve complete Draft 2020-12 input-schema publication and validation before SDK argument parsing or handler invocation, including local-only reference resolution.
- Add the schema-validation libraries to the runtime dependencies.

## 0.4.5

- Build wheel and source-distribution artifacts from an isolated copy so local build state is left alone.
- Add an offline smoke test that installs the built wheel and sdist and checks they start.

## 0.4.4

- Pin the development, test, and build tools in the `dev` extra, and run tests offline against temporary config, token, and draft paths.

## 0.4.2

- Publish and validate complete Draft 2020-12 tool input schemas before SDK parsing or handler invocation, preserving original JSON types and optional-argument behavior.
- Declare `jsonschema>=4.20.0` and `referencing>=0.30.0` as direct runtime dependencies for original-schema validation and local reference resolution.

## 0.4.1

- Require at least 100 Bytes for deposit and withdrawal schemas while preserving the 1-Byte transfer minimum.
- Keep `hf.doctor` as a catalog entry with an empty argument schema; it is not a callable tool.

## 0.4.0

- Derive tool hints and metadata from one tool registry, and record which tools run locally. A local `hf.doctor` catalog entry exists but is not a callable tool.

## 0.3.5

- Run the PyPI publish workflow only when started manually.
- Make the package checks work from a standalone checkout of this repository.

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
- Keep pagination limits in the published schemas and reject invalid page numbers and sizes before a tool runs.
- Send core forum, thread and post reads through the existing generic `POST /api/v2/read` route, preserving asks and public tool names.
- Preserve standard read-only annotations and structured results on modern and legacy stdio connections. HF custom metadata previously nested in annotations is published at tool-level `_meta` through the SDK `meta` argument.
- SDK wire serialization may omit null extension values, including the local catalog's `x-hf-helper-path: null` (no upstream helper). Populated HF metadata values are preserved.
- Publish existing open-object output schemas through the SDK-supported `Annotated[CallToolResult, OutputModel]` return annotation.
