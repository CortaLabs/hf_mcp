---
name: hf-api-v2
description: Work with the Hack Forums API v2 for OAuth app design, scope selection, request-shape drafting, MCP tool planning, and integration debugging
user-invocable: true
context: full
visibility: exported
owner: hackforums-council
---

# HF API v2

Use this skill when work touches the Hack Forums API v2, including OAuth app setup, scope planning, `asks` payload design, MCP tool definitions, or debugging forum integrations.

## Trigger Conditions

- The task mentions Hack Forums, HF API v2, OAuth app setup, Bearer-token auth, or the `https://hackforums.net/api/v2` base URL.
- The task needs example `/read` or `/write` payloads, scope selection guidance, or endpoint selection.
- The task involves designing MCP tools or automations that read from or write to Hack Forums resources.

## Inputs

- The intended product surface, such as an MCP tool, dashboard, bot, or account automation.
- The resource domain involved: `me`, `users`, `forums`, `threads`, `posts`, `bytes`, `contracts`, `disputes`, `bratings`, or signature-market endpoints.
- Whether the task is read-only, write-capable, or just planning/debugging.
- Any current error evidence, such as `401`, validation failures, or rate-limit pressure.

## Procedure

1. Confirm the integration shape.
   Decide whether the task is explaining the API, drafting requests, debugging an existing call, or shaping a new MCP tool.

2. Choose the minimum scope set.
   Map the use case to the documented beta scopes: Basic Info, Advanced Info, Posts, Users, Bytes, and Contracts. Favor the smallest viable scope set and note that increased permissions require user re-authorization.

3. Keep OAuth architecture server-side.
   Describe the authorization-code flow accurately:
   - send the user to the HF authorize page with `client_id`, `response_type=code`, and optional `state`
   - receive `code` at the configured redirect URI
   - exchange it at `POST https://hackforums.net/api/v2/authorize`
   - store the returned access token securely and use `Authorization: Bearer <token>`

4. Model reads and writes around the real endpoint contract.
   - Base URL: `https://hackforums.net/api/v2`
   - Generic reads: `POST /read`
   - Generic writes: `POST /write`
   - Helper endpoints: `POST /read/me`, `/read/users`, `/read/forums`, `/read/threads`, `/read/posts`, `/read/bytes`, `/read/contracts`, `/read/disputes`, `/read/bratings`, `/read/sigmarket/market`, `/read/sigmarket/order`, `/write/posts`, `/write/threads`, `/write/bytes`, `/write/bytes/deposit`, `/write/bytes/withdraw`, `/write/bytes/bump`

5. Build `asks` payloads correctly.
   Inputs are underscore-prefixed, such as `_pid`, `_tid`, `_message`, `_amount`, and `_to_uid`. Requested response fields are marked with `true`. When drafting examples, show only the fields needed for the task.

6. Debug the obvious failure classes first.
   - `401 Unauthorized`: missing, invalid, expired, or revoked token
   - validation failure: wrong endpoint, missing underscore-prefixed inputs, or missing write scope
   - rate pressure: inspect `x-rate-limit-remaining`

7. Account for API write-path content sanitization.
   Treat quote-entity conversion in API-written post bodies as a natural HF security/safety behavior. Live MCP probes showed quote-heavy content written through `posts.reply` can read back with double quotes canonicalized to `&quot;`, including inside `[code]` blocks and inline text; pre-encoding quotes as decimal numeric entities (`&#34;`) did not remain distinct and also read back as `&quot;`. Do not assume API-written JSON snippets are copy-ready on the public forum page. If exact code fidelity matters, use a safer delivery shape such as quote-light examples, attachments, paste links, screenshots, or a read-side decoded representation for MCP consumers while preserving the raw upstream payload.

8. For write-capable designs, add operational guardrails.
   Recommend explicit confirmation, dry-run previews where possible, rate-limit awareness, and server-side secret storage. If the integration is for this repo, keep write automation downstream of the MCP surface rather than embedding forum-posting logic directly into unrelated components.

## Verification

- Confirm the scope list matches the requested behavior and does not over-request permissions.
- Confirm the chosen endpoint matches the resource and operation.
- Confirm every input field that is sent in `asks` uses the expected underscore-prefixed name.
- Confirm write-side guidance includes token handling, revocation awareness, and rate-limit awareness.
- Confirm forum-visible examples do not rely on raw double quotes surviving API write-path sanitization unless that exact behavior has just been live-verified.

## Output / Handoff

- A concise integration plan, debugging diagnosis, or MCP-tool design rooted in the documented HF API v2 contract.
- Example request shapes when the task benefits from them.
- Explicit risks or missing information if the docs do not fully answer the question.

## Boundaries

- Do not claim to obtain, rotate, or manage real tokens or secrets.
- Do not suggest putting `client_secret` or access tokens in front-end code, public repos, or shared logs.
- Treat the docs at `https://apidocs.hackforums.net/` as current guidance for this repo, but note that they are unofficial and should be rechecked if behavior appears to drift.
- For this project, do not normalize uncontrolled forum-posting automation. Live writes should stay gated and operator-controlled.
- Do not frame HF API quote sanitization as inherently broken; treat it as an expected safety boundary and design MCP copy/read behavior around it.

## References

- Unofficial docs: `https://apidocs.hackforums.net/`
- Swagger: `https://swagger.hackforums.net/`
- Community resources called out by the docs:
  - `https://github.com/xerotic/HF-API-v2`
  - `https://github.com/LNodesL/HF-API-Python`
