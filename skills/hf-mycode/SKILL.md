---
name: hf-mycode
description: Author, convert, and troubleshoot MyBB/Hack Forums MyCode with conservative syntax assumptions
user-invocable: true
context: full
visibility: exported
owner: hackforums-council
---

# HF MyCode

Use this skill when you need reliable MyCode (BBCode) output for MyBB-style forums, with explicit Hack Forums overlays grounded in helpdoc 45.

## Trigger Conditions

- The task asks for MyCode or BBCode authoring, conversion, or cleanup.
- You need to validate whether a tag is safe on Hack Forums before suggesting it.
- The user needs formatting that should survive forum parser differences.

## Inputs

- Target forum: Hack Forums or another MyBB-based forum.
- Source content format: plain text, Markdown, HTML, or existing BBCode.
- Portability target: HF-specific output only or cross-MyBB fallback.

## Procedure

1. Classify target scope before writing tags.
   If the target is Hack Forums, treat helpdoc 45 as the authoritative syntax boundary. If the target is generic MyBB, keep output to conservative core tags unless forum-specific support is confirmed.

2. Build a portable baseline first.
   Start with core tags such as `[b]`, `[i]`, `[u]`, `[s]`, `[url]`, `[quote]`, `[code]`, and list syntax. Keep nesting explicit, close all tags, and avoid custom/plugin tags by default.

3. Apply HF-specific overlay only when requested or when target is HF.
   For HF guidance, use helpdoc 45-compatible forms such as `[help]`, `[pmme=Subject]...[/pmme]`, `[soundcloud]...[/soundcloud]`, `[skype]...[/skype]`, and spoiler/image/list variants documented for HF.

4. Account for HF API write-path quote sanitization.
   Treat double-quote entity conversion in content posted through the HF API/MCP write path as an expected HF safety behavior, not a parser surprise. Live probes showed raw double quotes in API-written JSON/code examples, and decimal numeric quote entities (`&#34;`), both read back as `&quot;` in `[code]` and inline text. Do not promise that JSON or other quote-heavy snippets posted through `hf-mcp` will preserve copy-ready literal double quotes on the public forum page. Prefer quote-light examples, YAML-ish examples, single-quoted formats where valid, screenshots, attachments, paste links, or explicitly labeled non-copyable examples when the exact code matters.

5. Mark uncertain or non-core tags as conditional.
   If a tag is common in other BBCode dialects but not in HF helpdoc 45, either convert to a supported equivalent or label it as unverified before recommending it.

6. Return ready-to-paste output with a short safety note.
   Include the final MyCode block plus one sentence describing any assumptions, especially when converting from Markdown/HTML.

## Verification

- Confirm every opening tag has a matching close tag when required.
- Confirm HF-specific examples use helpdoc 45-supported syntax forms.
- Confirm unsupported/custom tags are not presented as guaranteed behavior.
- Confirm converted output remains readable if styling tags are stripped.
- For API/MCP-posted HF content, confirm code examples do not depend on literal double quotes surviving the write path unless that behavior has just been live-verified.

## Output / Handoff

- Final MyCode snippet tailored to the target forum.
- Brief assumptions note (forum target, parser assumptions, any conditional tags).
- Optional pointer to `references/MYCODE_REFERENCE.md` for full syntax tables and conversions.

## Boundaries

- Do not claim plugin/custom tags are default HF behavior.
- Do not infer live forum permissions from syntax alone.
- Do not describe HF API quote sanitization as unexpected breakage; frame it as a natural security/safety boundary for live forum writes.
- Do not turn this skill into a full API or automation workflow.

## References

- [MYCODE_REFERENCE.md](references/MYCODE_REFERENCE.md)
