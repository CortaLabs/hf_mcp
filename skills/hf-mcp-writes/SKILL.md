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
   - `threads.create`: forum selector plus content (`fid`, `subject`, `message`, `confirm_live`).
   - `posts.reply`: thread selector plus content (`tid`, `message`, `confirm_live`).
   - Bytes writes: target and amount details where required, plus `confirm_live`.

4. Treat placeholder rows as documented scope continuity only.
   - They are part of coverage tracking, but not concrete helper commitments today.
   - Do not provide runnable examples that imply these rows are currently executable.

5. Keep autonomous posting out of scope.
   - This skill does not normalize ungated automation or unattended live posting.
   - Escalate any automation request into explicit planning with operator-controlled gates.

6. Route raw HF API internals to `hf-api-v2` when requested.
   - Use `hf-api-v2` for low-level API semantics and scope details, not this write-usage surface.

## Verification

- Confirm the requested helper is in the concrete-today list before preparing a live call.
- Confirm `confirm_live=true` is explicitly present for concrete writes.
- Confirm placeholder rows are labeled non-callable in all guidance.
- Confirm no ungated autonomous posting behavior is implied.

## Output / Handoff

- A concrete helper decision or an explicit placeholder-row block decision.
- A JSON-first argument outline with required guardrail fields.
- Any risk note that requires operator confirmation before proceeding.

## Boundaries

- Do not claim placeholder rows are callable today.
- Do not relax or omit `confirm_live=true` for concrete write helpers.
- Do not normalize autonomous posting or unattended live-write loops.
- Do not invent additional write helpers beyond the shipped documented set.
