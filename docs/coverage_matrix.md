# Coverage Matrix

This matrix tracks final public endpoint-family status for `hf-mcp`.

## Evidence tiers

- `OpenAPI-confirmed`
- `PHP-source-confirmed`
- `HF_API_REFERENCE-confirmed`
- `none` (no source confirms it)

Live status values: `tested live` and `untested`.

## Endpoint-family status

| Endpoint family | Operation | MCP exposure status | Evidence tiers | Live status | Notes |
|---|---|---|---|---|---|
| `me.read` | read | available now | OpenAPI-confirmed | untested | PM counters (`unreadpms`, `totalpms`) may appear when Advanced Info fields are enabled |
| `users.read` | read | available now | OpenAPI-confirmed | untested | canonical selector `uid` |
| `forums.index` | read | available now | OpenAPI-confirmed | untested | local catalog-backed root discovery (`forums.index` / `forums_index`); `_hf_flow` emitted; catalog can drift from live HF |
| `forums.read` | read | available now | OpenAPI-confirmed | untested | canonical selector `fid` |
| `threads.read` | read | available now | OpenAPI-confirmed | untested | canonical selector `fid`; compatibility selectors `tid`/`uid` accepted |
| `posts.read` | read | available now | OpenAPI-confirmed | untested | canonical selector `tid`; compatibility selectors `pid`/`uid` accepted |
| `bytes.read` | read | available now | OpenAPI-confirmed | untested | canonical selector `target_uid`; compatibility alias `uid` accepted |
| `contracts.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | untested | canonical selector `cid`; compatibility alias `contract_id` accepted |
| `disputes.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | untested | canonical selector `cdid`; compatibility aliases `dispute_id`/`did` accepted |
| `bratings.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | untested | browse-first optional-filter read |
| `sigmarket.market.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | untested | browse-first optional-filter read |
| `sigmarket.order.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | untested | canonical selector `smid`; compatibility alias `oid` accepted |
| `admin.high_risk.read` | read | available now | OpenAPI-confirmed | untested | privileged scope boundary remains operator-gated |
| `formatting.preflight` | local | available now | none | untested | local check that saves a local draft on every call; nothing is sent |
| `formatting.convert` | local | available now | none | untested | local Markdown/MyCode to Hack Forums MyCode conversion; nothing is saved or sent |
| `templates.list` | local | available now | none | untested | lists valid templates in `templates_dir`; invalid files are only counted |
| `templates.render` | local | available now | none | untested | fills a named template and returns its source and MyCode; nothing is saved or sent |
| `drafts.list` / `drafts.read` | local | available now | none | untested | local draft store reads |
| `drafts.update` / `drafts.delete` | local | available now | none | untested | local draft store changes; nothing is sent |
| `threads.create` | write | available now | OpenAPI-confirmed | tested live | `confirm_live=true` required |
| `posts.reply` | write | available now | OpenAPI-confirmed | tested live | `confirm_live=true` required |
| `bytes.transfer` | write | available now | OpenAPI-confirmed | untested | `confirm_live=true` required |
| `bytes.deposit` | write | available now | OpenAPI-confirmed | untested | `confirm_live=true` required |
| `bytes.withdraw` | write | available now | OpenAPI-confirmed | untested | `confirm_live=true` required |
| `bytes.bump` | write | available now | OpenAPI-confirmed | untested | `confirm_live=true` required |
| `contracts.write` | write | not exposed | PHP-source-confirmed, HF_API_REFERENCE-confirmed | untested | not in the OpenAPI spec and no verified contract, so it is not offered |
| Signature Market write family | write | not exposed | HF_API_REFERENCE-confirmed | untested | no current concrete helper evidence for exposure |
| Admin-only high-risk write family | write | not exposed | none | untested | no verified concrete contract for exposure |
| PM content-management family | write | not exposed | none | untested | only `me.read` counters are supported today |

## Interpretation

- `available now` rows are concrete and registered in the current MCP surface.
- `not exposed` rows are explicit unsupported boundaries, not callable tools.
- Capability policy may disable available rows, but this table tracks final exposure eligibility.
- Write tools are registered only when the active profile enables them, and every live write needs `confirm_live=true`.
- `forums.index` is a local catalog for finding forums when you have no IDs; treat it as a maintained index, not live Hack Forums state.
