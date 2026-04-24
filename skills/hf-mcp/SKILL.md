---
name: hf-mcp
description: Index and routing skill for using the hf-mcp package safely and choosing the correct sibling workflow
user-invocable: true
context: full
visibility: exported
owner: hackforums-council
---

# HF MCP

Use this skill as the router for hf-mcp tasks so you choose the right specialized skill quickly and keep guidance aligned with current package truth.

## Trigger Conditions

- The task mentions `hf-mcp` generally and the next step is unclear.
- The user needs to decide between setup/auth, read usage, or write usage.
- You need a safe entrypoint before running live-capable operations.

## Inputs

- User goal in one sentence.
- Current state: planning only, local setup, read calls, or write calls.
- Whether the user already has config and token state ready.

## Procedure

1. Route to `hf-api-v2` for raw Hack Forums API fundamentals.
   Use that skill for OAuth model details, scope reasoning, `/read` and `/write` payload shape, and API error classes.

2. Route to `hf-mcp-bootstrap` for local lifecycle work.
   Use it for install/setup/auth/status/doctor/serve, config path precedence, and environment-variable reminders.

3. Route to `hf-mcp-reads` for read tooling.
   Use it for tool family selection, required selectors, browse-first optional-filter semantics, and JSON-first read examples.

4. Route to `hf-mycode` for formatting and syntax work.
   Use it when the user needs MyCode/BBCode authoring, conversion, linting, or syntax troubleshooting.

5. Route to `hf-mcp-writes` for write tooling.
   Use it for concrete write helpers, `confirm_live=true` requirements, and placeholder-row boundaries.
   Keep draft semantics explicit: `scheduled_at` is metadata only and there is no built-in scheduler.

6. Keep boundaries explicit.
   If a task would change runtime behavior, package manifests, or product docs, escalate to implementation planning instead of improvising in usage guidance.

## Verification

- Confirm the task is routed to exactly one primary sibling skill.
- Confirm `hf-api-v2` is used when OAuth/API internals are requested.
- Confirm write-capable tasks are routed through write guardrail guidance, not treated as routine reads.

## Output / Handoff

- A clear next skill and why it fits.
- Any prerequisites the user must satisfy before the next step.
- Any risk flags that require manual operator confirmation.

## Boundaries

- Do not duplicate full procedures from sibling skills in this router.
- Do not re-teach the full HF API contract here; hand that off to `hf-api-v2`.
- Do not claim placeholder write rows are concrete callable helpers.
- Do not normalize uncontrolled live-write automation.
