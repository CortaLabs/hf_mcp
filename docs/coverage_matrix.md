# Coverage Matrix

This matrix tracks final public endpoint-family status for `hf-mcp`.

## Evidence tiers

- `OpenAPI-confirmed`
- `PHP-source-confirmed`
- `HF_API_REFERENCE-confirmed`
- `live-proven`
- `unproven`

## Endpoint-family status

| Endpoint family | Operation | MCP exposure status | Evidence tiers | Live status | Notes |
|---|---|---|---|---|---|
| `me.read` | read | available now | OpenAPI-confirmed | unproven | PM counters (`unreadpms`, `totalpms`) may appear when Advanced Info fields are enabled |
| `users.read` | read | available now | OpenAPI-confirmed | unproven | canonical selector `uid` |
| `forums.read` | read | available now | OpenAPI-confirmed | unproven | canonical selector `fid` |
| `threads.read` | read | available now | OpenAPI-confirmed | unproven | canonical selector `fid`; compatibility selectors `tid`/`uid` accepted |
| `posts.read` | read | available now | OpenAPI-confirmed | unproven | canonical selector `tid`; compatibility selectors `pid`/`uid` accepted |
| `bytes.read` | read | available now | OpenAPI-confirmed | unproven | canonical selector `target_uid`; compatibility alias `uid` accepted |
| `contracts.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | unproven | canonical selector `cid`; compatibility alias `contract_id` accepted |
| `disputes.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | unproven | canonical selector `cdid`; compatibility aliases `dispute_id`/`did` accepted |
| `bratings.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | unproven | browse-first optional-filter read |
| `sigmarket.market.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | unproven | browse-first optional-filter read |
| `sigmarket.order.read` | read | available now | OpenAPI-confirmed, HF_API_REFERENCE-confirmed | unproven | canonical selector `smid`; compatibility alias `oid` accepted |
| `admin.high_risk.read` | read | available now | OpenAPI-confirmed | unproven | privileged scope boundary remains operator-gated |
| `threads.create` | write | available now | OpenAPI-confirmed | live-proven | `confirm_live=true` required |
| `posts.reply` | write | available now | OpenAPI-confirmed | live-proven | `confirm_live=true` required |
| `bytes.transfer` | write | available now | OpenAPI-confirmed | unproven | `confirm_live=true` required |
| `bytes.deposit` | write | available now | OpenAPI-confirmed | unproven | `confirm_live=true` required |
| `bytes.withdraw` | write | available now | OpenAPI-confirmed | unproven | `confirm_live=true` required |
| `bytes.bump` | write | available now | OpenAPI-confirmed | unproven | `confirm_live=true` required |
| `contracts.write` | write | not exposed | PHP-source-confirmed, HF_API_REFERENCE-confirmed | unproven | OpenAPI-absent and blocked until operator-approved sandbox proof exists |
| Signature Market write family | write | not exposed | HF_API_REFERENCE-confirmed | unproven | no current concrete helper evidence for exposure |
| Admin-only high-risk write family | write | not exposed | unproven | unproven | no verified concrete contract for exposure |
| PM content-management family | write | not exposed | unproven | unproven | only `me.read` counters are supported today |

## Interpretation

- `available now` rows are concrete and registered in the current MCP surface.
- `not exposed` rows are explicit unsupported boundaries, not callable tools.
- Capability policy may disable available rows, but this table tracks final exposure eligibility.
- Manual live validation remains intentionally narrower than full write availability in this wave.
