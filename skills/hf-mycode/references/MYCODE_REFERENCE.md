# HF MyCode Reference

Use this file for dense syntax lookups, conversions, and HF-specific boundaries. Keep workflow decisions in the root skill.

## HF Helpdoc 45 Truth Surface

Hack Forums helpdoc 45 (mirrored in the HF wiki MyCode page) documents these tag families as HF-supported:

- Text formatting: `[b]`, `[i]`, `[u]`, `[s]`, `[color=...]`, `[align=left|center|right|justify]`
- Linking and contact: `[url]...[/url]`, `[url=...]...[/url]`, `[email]...[/email]`, custom-text email form, `[pmme=Subject]...[/pmme]`, `[help]`
- Structural: `[quote]...[/quote]`, `[quote="Author"]...[/quote]`, `[code]...[/code]`, `[list]`, `[list=1]`, `[list=a]` with `[*]`
- Embeds/content: `[img]...[/img]`, `[img=WxH]...[/img]`, `[spoiler]...[/spoiler]`, `[spoiler=Description]...[/spoiler]`, `[soundcloud]...[/soundcloud]`, `[skype]...[/skype]`

Practical rule: if a tag is missing from the list above, treat it as unverified for HF unless the user provides current forum evidence.

## Conservative Cross-MyBB Baseline

For unknown MyBB deployments, default to:

- `[b]`, `[i]`, `[u]`, `[s]`
- `[url]`, `[url=...]`
- `[quote]`, `[code]`
- `[list]` plus `[*]`

Treat other tags as conditional until forum support is confirmed.

## Non-Guaranteed Tag Handling

When inputs include tags not covered by HF helpdoc 45 (for example `[table]`, `[youtube]`, `[media]`, `[h1]`, custom `[icode]`):

1. Convert to a documented HF equivalent when possible.
2. If no equivalent exists, preserve content as plain text or `[code]`.
3. State that the tag is unverified/conditional instead of claiming support.

## Conversion Cheatsheet

- Markdown link: `[title](https://x)` -> `[url=https://x]title[/url]`
- Markdown heading: `## Heading` -> `[b]Heading[/b]`
- Markdown code fence -> `[code]...[/code]`
- HTML `<strong>` / `<b>` -> `[b]...[/b]`
- HTML `<em>` / `<i>` -> `[i]...[/i]`
- HTML `<a href="...">text</a>` -> `[url=...]text[/url]`
- HTML lists -> `[list]` + `[*]` items

## HF API / MCP Write Quote Boundary

When content is posted through the HF API write path, treat double-quote entity conversion as expected HF security/sanitization behavior.

Observed live behavior from `hf-mcp posts.reply` probes on thread `6324346`:

- Raw double quotes in `[code]` JSON examples read back as `&quot;`.
- Inline raw double quotes read back as `&quot;`.
- Decimal numeric quote entities (`&#34;`) were canonicalized to `&quot;`, so pre-encoding quotes is not a proven escape hatch.
- Single quotes stayed readable in YAML-ish examples, but that is a formatting workaround, not JSON fidelity.

Practical guidance:

- Do not promise that API/MCP-posted JSON snippets will be copy-ready from the public HF page.
- Prefer quote-light formats, YAML-ish examples, single-quoted formats where valid, screenshots, attachments, paste links, or explicit "illustrative only" labels for quote-heavy examples.
- MCP clients may decode entities for readable/structured output, but raw payload views should preserve the upstream HF API response.

## Minimal Validation Checklist

- All tags close correctly.
- Nested tags are balanced.
- HF-specific guidance only uses helpdoc 45-supported forms.
- Conditional/unverified tags are explicitly labeled.
- API/MCP-posted code examples account for the quote-sanitization boundary.
