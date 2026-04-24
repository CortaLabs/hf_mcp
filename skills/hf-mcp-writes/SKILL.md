---
name: hf-mcp-writes
description: Guarded write usage skill for hf-mcp separating concrete live-write helpers from documented placeholder rows
user-invocable: true
context: full
visibility: exported
owner: hackforums-council
---

# HF MCP Writes

Use this skill for hf-mcp write tasks so live-write guardrails stay explicit, concrete helper coverage stays truthful, and placeholder rows are not treated as callable operations.

## Trigger Conditions

- The user asks to create content or submit a mutating Bytes action through `hf-mcp`.
- The task needs concrete write helper selection and `confirm_live=true` handling.
- The user asks whether a documented write row is currently callable.

## Inputs

- Target write outcome (thread create, reply, transfer, deposit, withdraw, or bump).
- Required selector/content fields for the selected concrete helper.
- Explicit operator intent to perform a live remote mutation now.

## Procedure

1. Separate concrete write helpers from placeholder coverage rows before any command drafting.
   - Concrete today helpers: `threads.create`, `posts.reply`, `bytes.transfer`, `bytes.deposit`, `bytes.withdraw`, `bytes.bump`.
   - Placeholder rows (not callable today): `contracts.write`, `sigmarket.write`, `admin.high_risk.write`.

2. Require explicit live-write confirmation on concrete helpers.
   - Concrete helpers require `confirm_live=true`.
   - If `confirm_live` is missing or false, treat it as a blocked write path rather than a soft warning.

3. Draft JSON-first write arguments with minimal required fields.
   - `threads.create`: forum selector plus content (`fid`, `subject`, `message`, `confirm_live`; optional `message_format`).
   - `posts.reply`: thread selector plus content (`tid`, `message`, `confirm_live`; optional `message_format`).
   - Bytes writes: target and amount details where required, plus `confirm_live`.

4. Use Markdown-to-MyCode conversion when it helps agents draft naturally.
   - `message_format` defaults to `mycode`, preserving existing behavior for ready-to-post MyCode.
   - Set `message_format="markdown"` when the caller writes Markdown and wants hf-mcp to convert common formatting to HF MyCode before sending.
   - The converter handles common Markdown emphasis, links, images, lists, block quotes, inline code, and fenced code blocks. Treat complex nested layouts as best-effort and inspect important public posts before live submission.

5. Treat HF API quote sanitization as an expected live-write safety boundary.
   - Do not promise that quote-heavy code examples posted through `posts.reply` or `threads.create` will preserve copy-ready literal double quotes on the forum page.
   - Live probes on thread `6324346` showed raw double quotes in `[code]` and inline text read back as `&quot;`; decimal numeric quote entities (`&#34;`) were also canonicalized to `&quot;`.
   - Frame this as natural HF security/sanitization for API-written forum content, not as a surprising MCP transport bug.
   - For public update posts, prefer quote-light formats, YAML-ish examples, single-quoted examples where valid, screenshots, attachments, paste links, or an explicit note that the snippet is illustrative rather than copy-ready.

6. Treat placeholder rows as documented scope continuity only.
   - They are part of coverage tracking, but not concrete helper commitments today.
   - Do not provide runnable examples that imply these rows are currently executable.

7. Treat draft scheduling fields as metadata only.
   - `scheduled_at` can exist in draft artifacts for operator workflow context.
   - There is no built-in scheduler/queue that auto-executes writes from this metadata.
   - Live execution still requires an explicit concrete helper call with `confirm_live=true`.

8. Keep autonomous posting out of scope.
   - This skill does not normalize ungated automation or unattended live posting.
   - Escalate any automation request into explicit planning with operator-controlled gates.

9. Route raw HF API internals to `hf-api-v2` when requested.
   - Use `hf-api-v2` for low-level API semantics and scope details, not this write-usage surface.

## Verification

- Confirm the requested helper is in the concrete-today list before preparing a live call.
- Confirm `confirm_live=true` is explicitly present for concrete writes.
- Confirm `message_format` is set intentionally: omit/use `mycode` for MyCode input, or use `markdown` for Markdown-to-MyCode conversion.
- Confirm placeholder rows are labeled non-callable in all guidance.
- Confirm any `scheduled_at` guidance is metadata-only with no implied scheduler.
- Confirm no ungated autonomous posting behavior is implied.
- Confirm any quote-heavy public post drafted through `hf-mcp` has an explicit strategy for HF API quote sanitization.

## Output / Handoff

- A concrete helper decision or an explicit placeholder-row block decision.
- A JSON-first argument outline with required guardrail fields.
- Optional `message_format` guidance for MyCode vs Markdown input.
- Any risk note that requires operator confirmation before proceeding.

## Boundaries

- Do not claim placeholder rows are callable today.
- Do not relax or omit `confirm_live=true` for concrete write helpers.
- Do not normalize autonomous posting or unattended live-write loops.
- Do not invent additional write helpers beyond the shipped documented set.
- Do not imply `scheduled_at` triggers automatic execution.
- Do not treat backend entity pre-encoding as a proven workaround for double quotes; `&#34;` was canonicalized to `&quot;` in live API readback.
