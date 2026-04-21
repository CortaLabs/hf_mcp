# Coverage Matrix

This matrix tracks the public product target for `hf-mcp`: full documented HF
API coverage. Deployment policy can hide rows, but rows remain in-scope product
coverage.

## Registry-backed rows

| Coverage family | Operation | Helper path | Implementation status | Product scope status | Exposure note |
|---|---|---|---|---|---|
| `me.read` | read | `me` | concrete today | in scope | can be disabled by capability policy |
| `users.read` | read | `users` | concrete today | in scope | can be disabled by capability policy |
| `forums.read` | read | `forums` | concrete today | in scope | can be disabled by capability policy |
| `threads.read` | read | `threads` | concrete today | in scope | can be disabled by capability policy |
| `posts.read` | read | `posts` | concrete today | in scope | can be disabled by capability policy |
| `bytes.read` | read | `bytes` | concrete today | in scope | can be disabled by capability policy |
| `contracts.read` | read | `contracts` | concrete today | in scope | deployment exposure control may keep disabled |
| `disputes.read` | read | `disputes` | concrete today | in scope | can be disabled by capability policy |
| `bratings.read` | read | `bratings` | concrete today | in scope | can be disabled by capability policy |
| `sigmarket.market.read` | read | `sigmarket/market` | concrete today | in scope | deployment exposure control may keep disabled |
| `sigmarket.order.read` | read | `sigmarket/order` | concrete today | in scope | deployment exposure control may keep disabled |
| `admin.high_risk.read` | read | `admin/high-risk/read` | concrete today | in scope | deployment exposure control may keep disabled |
| `threads.create` | write | `threads` | concrete today | in scope | `confirm_live` guard required |
| `posts.reply` | write | `posts` | concrete today | in scope | `confirm_live` guard required |
| `bytes.transfer` | write | `bytes` | concrete today | in scope | `confirm_live` guard required |
| `bytes.deposit` | write | `bytes/deposit` | concrete today | in scope | `confirm_live` guard required |
| `bytes.withdraw` | write | `bytes/withdraw` | concrete today | in scope | `confirm_live` guard required |
| `bytes.bump` | write | `bytes/bump` | concrete today | in scope | `confirm_live` guard required |
| `contracts.write` | write | `contracts` | placeholder row only | in scope | deployment exposure control may keep disabled until helper proof is named |
| `sigmarket.write` | write | `sigmarket` | placeholder row only | in scope | deployment exposure control may keep disabled until helper proof is named |
| `admin.high_risk.write` | write | `admin/high-risk/write` | placeholder row only | in scope | deployment exposure control may keep disabled until helper proof is named |

## Interpretation

- A disabled row is still part of product scope.
- A later-lane row is still part of product scope.
- `Implementation status` distinguishes concrete tools available today from
  placeholder-only rows tracked for documented coverage continuity.
- Extended reads (`contracts.read`, `disputes.read`, `bratings.read`,
  `sigmarket.market.read`, `sigmarket.order.read`) use a browse-first
  optional-filter contract with canonical selectors in structured JSON payloads:
  `contracts.read` => `cid` (optional), optional `uid`;
  `disputes.read` => `cdid` (optional), optional `uid` (legacy alias support:
  `did` / `dispute_id`);
  `bratings.read` => optional `uid`;
  `sigmarket.market.read` => optional `uid`;
  `sigmarket.order.read` => `oid` (optional), optional `uid`.
- If documented HF API coverage expands, this matrix must add named rows rather
  than replacing specifics with vague future language.
