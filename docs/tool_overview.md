# Tool Overview

This page summarizes the shipped MCP tool surface defined in
`src/hf_mcp/registry.py` for users and operators.

Clients list tools with underscores instead of dots (for example
`threads_read` for `threads.read`). These docs and the config file use the
dotted names; both refer to the same tool.

## Availability labels

- `available now`: concrete and registered for downstream MCP clients
- `not exposed`: intentionally unavailable in the registered MCP surface

## Evidence tiers

Evidence tags used in this document and the coverage matrix:

- `OpenAPI-confirmed`
- `PHP-source-confirmed`
- `HF_API_REFERENCE-confirmed`
- `none` (no source confirms it)

Live status values: `tested live` and `untested`.

## Read output contract

All read tools in this overview support the same output controls:

- config defaults via `read_output_defaults.mode` and
  `read_output_defaults.include_raw_payload`
- config defaults via `read_output_defaults.body_format`
- per-call overrides via `output_mode`, `include_raw_payload`, and
  `body_format`

Mode behavior:

- `readable` (default): rich human-readable text + canonical `structuredContent`;
  thread reads include formatted first-post body content when Hack Forums returns it
- `structured`: terse text + canonical `structuredContent` for scripts
- `raw`: terse text + canonical `structuredContent` + additive raw JSON resource

Raw JSON can also be attached additively when `include_raw_payload=true` even if
`output_mode` is `readable` or `structured`.

Body-format behavior:

- `markdown` (default): converts MyCode/BBCode body fields such as `message`
  into simple Markdown for agent readability
- `clean`: strips noisy formatting tags while keeping readable text and URLs
- `raw`: preserves upstream MyCode/BBCode body fields

When `output_mode=raw`, `body_format` resolves to `raw` unless explicitly
overridden for that call.

## Root discovery and flow contract

- `forums.index` (alias `forums_index`) is local catalog-backed root discovery.
- The catalog is maintained package data and can drift from live HF between
  package updates.
- Concrete chain: `forums.index` -> `forums.read` -> `threads.read` ->
  `posts.read`.
- `forums.read` remains selector-bound (`fid` required) and is not root
  discovery.
- `_hf_flow` is the machine-readable flow key and is currently emitted by
  `forums.index`, core reads, supported extended reads (`bytes.read`,
  `contracts.read`, `disputes.read`, `bratings.read`,
  `sigmarket.market.read`, and `sigmarket.order.read`), local
  draft/preflight tools, and successful results from existing guarded write
  helpers after confirmed or stubbed execution.

## Canonical selectors and compatibility aliases

Core reads:

- `forums.index`: selector-free root discovery from the packaged forum catalog.
- `threads.read`: canonical browse anchor is `fid`; compatibility selectors `tid`
  and `uid` are accepted for compatibility callers.
- `posts.read`: canonical browse anchor is `tid`; compatibility selectors `pid`
  and `uid` are accepted for compatibility callers.
- `forums.read`: canonical selector is `fid`.

Extended reads:

- `bytes.read`: canonical selector is `target_uid`; compatibility alias `uid` is accepted.
- `contracts.read`: canonical selector is `cid`; compatibility alias `contract_id` is accepted.
- `disputes.read`: canonical selector is `cdid`; compatibility aliases `dispute_id` and `did` are accepted.
- `sigmarket.order.read`: canonical selector is `smid`; compatibility alias `oid` is accepted.

PM boundary:

- PM counters (`unreadpms`, `totalpms`) are available via `me.read` when Advanced
  Info fields are enabled.
- Direct PM content operations are unsupported.

## Available reads

| Tool | Availability | What it is for |
|---|---|---|
| `me.read` | available now | Read profile/account details for the authenticated account |
| `users.read` | available now | Read public user details by target uid |
| `forums.index` | available now | Local catalog-backed root discovery when no IDs are known |
| `forums.read` | available now | List forum metadata/threads by forum id |
| `threads.read` | available now | Forum-anchored browse (`fid` canonical; compatibility selectors accepted) |
| `posts.read` | available now | Thread-anchored browse (`tid` canonical; compatibility selectors accepted) |
| `bytes.read` | available now | Read Bytes balance/details for a target user |
| `contracts.read` | available now | Browse-first optional-filter read |
| `disputes.read` | available now | Browse-first optional-filter read |
| `bratings.read` | available now | Browse-first optional-filter read |
| `sigmarket.market.read` | available now | Browse-first optional-filter read |
| `sigmarket.order.read` | available now | Browse-first optional-filter read |
| `admin.high_risk.read` | available now | Read high-risk admin surface data (privileged scope) |

## Available local tools

These run on your machine only. Nothing is sent to Hack Forums, and none of them
takes `confirm_live`.

| Tool | Availability | What it is for |
|---|---|---|
| `formatting.preflight` | available now | Check how MyCode or Markdown converts to Hack Forums MyCode, report conversion findings, and save the result as a local draft on every call (use `formatting.convert` to convert without saving) |
| `formatting.convert` | available now | Convert Markdown or MyCode (`message`, `message_format`) to Hack Forums MyCode and report `conversion_findings`; nothing is saved |
| `templates.list` | available now | List the named templates in `templates_dir` with their placeholders; invalid files are only counted in `invalid_count` |
| `templates.render` | available now | Fill a named template (`name`, `values`) and return its `source_text` and Hack Forums `mycode`; nothing is saved |
| `drafts.list` | available now | List local drafts with optional status, category, title or schedule filters |
| `drafts.read` | available now | Read one local draft by `draft_id` or `draft_path`, including its full MyCode |
| `drafts.update` | available now | Update a local draft's title, category, status or scheduled-time metadata |
| `drafts.delete` | available now | Delete a local draft (needs explicit delete confirmation) |

Template file rules and the `templates_dir` setting are in
[`configuration.md`](configuration.md#post-templates). Every free-text message or
source is limited to 500,000 characters.

## Profiles

| Profile | Tools |
|---|---|
| `reader` (default) | 18: all 13 reads, `formatting.convert`, `templates.list`, `templates.render`, `drafts.list`, `drafts.read` |
| `forum_operator` | 23: `reader` plus `formatting.preflight`, `drafts.update`, `drafts.delete`, `threads.create`, `posts.reply` |
| `full_api` | all 27: `forum_operator` plus `bytes.transfer`, `bytes.deposit`, `bytes.withdraw`, `bytes.bump` |
| `custom` | none until you opt in; list `output.options` among the enabled parameter families to keep `output_mode`, `include_raw_payload` and `body_format` (plus `view` and `include_inactive` on `forums.index`) |

## Available writes

All write tools below require `confirm_live=true`.
Content writes (`threads.create`, `posts.reply`) also accept `message_format`.

| Tool | Availability | What it is for |
|---|---|---|
| `threads.create` | available now | Create a new thread in a target forum (`fid`) |
| `posts.reply` | available now | Reply to an existing thread (`tid`) |
| `bytes.transfer` | available now | Transfer Bytes to a target user (`target_uid`, `amount`) |
| `bytes.deposit` | available now | Deposit Bytes (`amount`) |
| `bytes.withdraw` | available now | Withdraw Bytes (`amount`) |
| `bytes.bump` | available now | Bump Bytes by thread id (`tid`) |

## Not exposed boundaries

- `contracts.write` is not exposed because there is no verified contract for it.
- Signature Market write operations are unsupported and not exposed.
- Admin-only high-risk write operations are unsupported and not exposed.

## Operator notes

- Use this page for grouped operator orientation.
- Use `docs/coverage_matrix.md` for row-by-row contract/evidence tracking.
- Use `docs/examples.md` for compact JSON-first request/response snippets.
- Use `docs/configuration.md` for path and override behavior (`HF_MCP_CONFIG`,
  `HF_MCP_ENV_FILE`, `HF_MCP_TOKEN_PATH`).
