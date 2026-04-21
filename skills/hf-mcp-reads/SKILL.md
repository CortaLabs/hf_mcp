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

1. Start with core reads for direct forum/content anchors.
   - `me.read`, `users.read`, `forums.read`, `threads.read`, `posts.read`
   - Canonical selectors for anchored reads: `fid`, `tid`, `pid`.

2. Use extended reads as single browse-first tools, not split browse/detail interfaces.
   - `bytes.read`, `contracts.read`, `disputes.read`, `bratings.read`, `sigmarket.market.read`, `sigmarket.order.read`, `admin.high_risk.read`
   - These rows accept optional filters and pagination in one tool call per family.

3. Apply canonical selector names in prompts and examples.
   - Canonical selectors: `fid`, `tid`, `pid`, `cid`, `cdid`, `oid`.
   - Compatibility aliases may exist in runtime for legacy callers, but public guidance should stay canonical-first.

4. Keep output handling JSON-first.
   - Treat request/response payloads as structured JSON.
   - Use lightweight field selection toggles when exposed (for example `include_post_body`), instead of rewriting transport assumptions.

5. Route out-of-scope API fundamentals to `hf-api-v2`.
   - Use `hf-api-v2` for raw OAuth mechanics, HF endpoint model details, and generic `/read` payload reasoning.

## Verification

- Confirm the selected read tool is in the shipped read matrix.
- Confirm selector naming stays canonical (`fid`, `tid`, `pid`, `cid`, `cdid`, `oid`) when those selectors are used.
- Confirm extended reads are described as browse-first optional-filter tools, not as separate browse/detail tool pairs.
- Confirm no write helper or live-write workflow is implied in the read procedure.

## Output / Handoff

- A concrete read tool choice and argument shape.
- Canonical selector and pagination/filter notes for that call.
- Handoff to `hf-mcp-writes` only if the user explicitly needs a guarded live write.

## Boundaries

- Do not invent read tools beyond the shipped matrix.
- Do not replace canonical selectors with legacy alias names in primary guidance.
- Do not present extended reads as split browse/detail interfaces.
- Do not include write execution guidance in this skill.
