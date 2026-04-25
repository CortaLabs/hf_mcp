---
name: hf-mcp-reads
description: Read-surface usage skill for hf-mcp covering core and extended tools, canonical selectors, and browse-first JSON-first behavior
user-invocable: true
context: full
visibility: exported
owner: hackforums-council
---

# HF MCP Reads

Use this skill for read-only hf-mcp usage so tool selection, selector usage, and output expectations stay aligned with the shipped read surface.

## Trigger Conditions

- The user wants to inspect account, forum, thread, post, market, contract, dispute, or rating data through `hf-mcp`.
- The task is choosing between core read tools and extended browse-first reads.
- The user needs canonical selector guidance for structured JSON arguments.

## Inputs

- The read question or data target.
- Scope anchor when available: forum id, thread id, post id, contract id, dispute id, or order id.
- Pagination/filter intent (`page`, `per_page`, optional user filter) for browse-first reads.

## Procedure

1. Start with root discovery if IDs are unknown, then move to anchored reads.
   - Root discovery: `forums.index` / `forums_index` (local catalog-backed package data that can drift from live HF).
   - Exploration chain: `forums.index` -> `forums.read` -> `threads.read` -> `posts.read`.
   - Follow `_hf_flow.next_actions` from each result when present so one tool output feeds the next tool call without selector guessing.
   - `forums.read` still requires `fid`; it is not root discovery.
   - Core anchored reads: `me.read`, `users.read`, `forums.read`, `threads.read`, `posts.read`.
   - Canonical selectors for anchored reads: `fid`, `tid`, `pid`.

2. Use extended reads as single browse-first tools, not split browse/detail interfaces.
   - `bytes.read`, `contracts.read`, `disputes.read`, `bratings.read`, `sigmarket.market.read`, `sigmarket.order.read`, `admin.high_risk.read`
   - These rows accept optional filters and pagination in one tool call per family.

3. Apply canonical selector names in prompts and examples.
   - Canonical selectors: `fid`, `tid`, `pid`, `cid`, `cdid`, `oid`.
   - Compatibility aliases may exist in runtime for legacy callers, but public guidance should stay canonical-first.

4. Choose body formatting deliberately.
   - Read tools expose `body_format` for body fields such as `message`.
   - `markdown` is the default for normal agent reads and converts common HF MyCode/BBCode into simple Markdown.
   - `clean` strips noisy formatting while preserving readable text and URLs.
   - `raw` preserves upstream MyCode; `output_mode=raw` resolves to raw body text unless a caller explicitly overrides `body_format`.

5. Choose output structure deliberately.
   - `readable` returns `structuredContent` plus rich human-facing content for normal agent consumption.
   - `structured` keeps `structuredContent` but intentionally makes the text summary terse.
   - `raw` attaches the upstream JSON payload as a resource; `include_raw_payload=true` adds that raw resource to `readable` or `structured`.
   - For `threads.read`, readable output should show the formatted thread body from nested `firstpost.message` plus useful thread and first-post fields when Hack Forums returns them.
   - `_hf_flow.next_actions` is the machine-readable handoff layer emitted by `forums.index`, core reads, supported extended reads, local draft/preflight tools, and successful results from implemented guarded writes (live writes still require explicit confirmation).

6. Keep output handling JSON-first.
   - Treat request/response payloads as structured JSON.
   - Use lightweight field selection toggles when exposed (for example `include_post_body`), instead of rewriting transport assumptions.

7. Route out-of-scope API fundamentals to `hf-api-v2`.
   - Use `hf-api-v2` for raw OAuth mechanics, HF endpoint model details, and generic `/read` payload reasoning.

8. Keep PM boundaries explicit.
   - PM counters (`unreadpms`, `totalpms`) can be read through `me.read` when Advanced Info fields are enabled.
   - Direct PM content operations are unsupported.

## Verification

- Confirm the selected read tool is in the shipped read matrix.
- Confirm selector naming stays canonical (`fid`, `tid`, `pid`, `cid`, `cdid`, `oid`) when those selectors are used.
- Confirm root discovery guidance names `forums.index` / `forums_index` as local catalog-backed package data, including drift warning.
- Confirm `forums.read` is described as `fid`-required and not root discovery.
- Confirm flow-aware usage follows `_hf_flow.next_actions` when present and does not invent unsupported next tools.
- Confirm body formatting matches the caller's need: `markdown` for agent readability, `clean` for stripped text, or `raw` for exact MyCode.
- Confirm `output_mode` matches the caller's structural need: `readable` for rich text+structuredContent, `structured` for terse text+structuredContent, or `raw` / `include_raw_payload=true` when upstream JSON evidence is needed.
- Confirm extended reads are described as browse-first optional-filter tools, not as separate browse/detail tool pairs.
- Confirm no write helper or live-write workflow is implied in the read procedure.

## Output / Handoff

- A concrete read tool choice and argument shape.
- Canonical selector and pagination/filter notes for that call.
- Body-format guidance when post/thread message content is involved.
- Handoff to `hf-mcp-writes` only if the user explicitly needs a guarded live write.

## Boundaries

- Do not invent read tools beyond the shipped matrix.
- Do not replace canonical selectors with legacy alias names in primary guidance.
- Do not present extended reads as split browse/detail interfaces.
- Do not include write execution guidance in this skill.
