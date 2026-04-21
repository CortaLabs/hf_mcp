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
| `threads.create` | write | `threads` | concrete today | in scope | `confirm_live=true` required; manual live validation wave allows at most one create in `FID 375` |
| `posts.reply` | write | `posts` | concrete today | in scope | `confirm_live=true` required; manual live validation wave allows replies on `TID 6083735` |
| `bytes.transfer` | write | `bytes` | concrete today | in scope | `confirm_live=true` required; no Bytes live writes in this validation wave |
| `bytes.deposit` | write | `bytes/deposit` | concrete today | in scope | `confirm_live=true` required; no Bytes live writes in this validation wave |
| `bytes.withdraw` | write | `bytes/withdraw` | concrete today | in scope | `confirm_live=true` required; no Bytes live writes in this validation wave |
| `bytes.bump` | write | `bytes/bump` | concrete today | in scope | `confirm_live=true` required; no Bytes live writes in this validation wave |
| `contracts.write` | write | `contracts` | placeholder row only | in scope | deployment exposure control may keep disabled until helper proof is named |
| `sigmarket.write` | write | `sigmarket` | placeholder row only | in scope | deployment exposure control may keep disabled until helper proof is named |
| `admin.high_risk.write` | write | `admin/high-risk/write` | placeholder row only | in scope | deployment exposure control may keep disabled until helper proof is named |

## Interpretation

- A disabled row is still part of product scope.
- A later-lane row is still part of product scope.
- `Implementation status` distinguishes concrete tools available today from
  placeholder-only rows tracked for documented coverage continuity.
- Manual live validation in this wave is intentionally narrower than concrete
  write availability: replies on `TID 6083735` plus at most one
  `threads.create` in `FID 375`.
- Placeholder writes remain out of scope in this wave:
  `contracts.write`, `sigmarket.write`, `admin.high_risk.write`.
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
