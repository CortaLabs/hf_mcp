# Coverage Matrix

This matrix tracks the public product target for `hf-mcp`: full documented HF
API coverage. Deployment policy can hide rows, but rows remain in-scope product
coverage.

## Registry-backed rows

| Coverage family | Operation | Helper path | Product scope status | Exposure note |
|---|---|---|---|---|
| `transport.read` | read | generic | in scope | can be disabled by capability policy |
| `transport.write` | write | generic | in scope | write path still requires local write guards |
| `me.read` | read | `me` | in scope | can be disabled by capability policy |
| `users.read` | read | `users` | in scope | can be disabled by capability policy |
| `forums.read` | read | `forums` | in scope | can be disabled by capability policy |
| `threads.read` | read | `threads` | in scope | can be disabled by capability policy |
| `posts.read` | read | `posts` | in scope | can be disabled by capability policy |
| `bytes.read` | read | `bytes` | in scope | can be disabled by capability policy |
| `contracts.read` | read | `contracts` | in scope (later-lane row retained) | deployment exposure control may keep disabled |
| `disputes.read` | read | `disputes` | in scope | can be disabled by capability policy |
| `bratings.read` | read | `bratings` | in scope | can be disabled by capability policy |
| `sigmarket.market.read` | read | `sigmarket/market` | in scope (later-lane row retained) | deployment exposure control may keep disabled |
| `sigmarket.order.read` | read | `sigmarket/order` | in scope (later-lane row retained) | deployment exposure control may keep disabled |
| `admin.high_risk.read` | read | `admin/high-risk/read` | in scope (documented admin/high-risk row retained) | deployment exposure control may keep disabled |
| `threads.create` | write | `threads` | in scope | `confirm_live` guard required |
| `posts.reply` | write | `posts` | in scope | `confirm_live` guard required |
| `bytes.transfer` | write | `bytes` | in scope | `confirm_live` guard required |
| `bytes.deposit` | write | `bytes/deposit` | in scope | `confirm_live` guard required |
| `bytes.withdraw` | write | `bytes/withdraw` | in scope | `confirm_live` guard required |
| `bytes.bump` | write | `bytes/bump` | in scope | `confirm_live` guard required |
| `contracts.write` | write | `contracts` | in scope (later-lane contract row retained) | deployment exposure control may keep disabled until helper proof is named |
| `sigmarket.write` | write | `sigmarket` | in scope (later-lane sigmarket row retained) | deployment exposure control may keep disabled until helper proof is named |
| `admin.high_risk.write` | write | `admin/high-risk/write` | in scope (documented admin/high-risk row retained) | deployment exposure control may keep disabled until helper proof is named |

## Interpretation

- A disabled row is still part of product scope.
- A later-lane row is still part of product scope.
- If documented HF API coverage expands, this matrix must add named rows rather
  than replacing specifics with vague future language.
