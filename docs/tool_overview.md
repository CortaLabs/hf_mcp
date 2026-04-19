# Tool Overview

This page summarizes the shipped MCP tool surface defined in
`src/hf_mcp/registry.py` (`_MATRIX_ROWS`) for operator use.

Status labels:

- `concrete today`: shipped and intended for immediate use
- `placeholder row only`: documented row retained for coverage continuity; do not
  treat as a concrete helper commitment today

## Account and identity reads

| Tool | Status | What it is for |
|---|---|---|
| `me.read` | concrete today | Read profile/account details for the authenticated account |
| `users.read` | concrete today | Read public user details by target uid |
| `bratings.read` | concrete today | Read b-ratings data for a target uid |

## Forum and content reads

| Tool | Status | What it is for |
|---|---|---|
| `forums.read` | concrete today | List forum metadata/threads by forum id |
| `threads.read` | concrete today | Forum-anchored browse (`fid` required, optional `tid`) |
| `posts.read` | concrete today | Thread-anchored browse (`tid` required, optional `pid`) |
| `bytes.read` | concrete today | Read Bytes balance/details for a target user (`target_uid`) |

## Market, contracts, and disputes reads

| Tool | Status | What it is for |
|---|---|---|
| `contracts.read` | concrete today | Read contract thread/details by contract id |
| `disputes.read` | concrete today | Read dispute thread/details by dispute id |
| `sigmarket.market.read` | concrete today | Read sigmarket listing/market view by listing id |
| `sigmarket.order.read` | concrete today | Read sigmarket order view by listing id |
| `admin.high_risk.read` | concrete today | Read high-risk admin surface data (privileged scope) |

## Write tools available today

All write rows below require `confirm_live=true`.

| Tool | Status | What it is for |
|---|---|---|
| `threads.create` | concrete today | Create a new thread in a target forum (`fid`) |
| `posts.reply` | concrete today | Reply to an existing thread (`tid`) |
| `bytes.transfer` | concrete today | Transfer Bytes to a target user (`target_uid`, `amount`) |
| `bytes.deposit` | concrete today | Deposit Bytes (`amount`) |
| `bytes.withdraw` | concrete today | Withdraw Bytes (`amount`) |
| `bytes.bump` | concrete today | Bump Bytes by thread id (`tid`) |

## Placeholder write rows (coverage continuity)

These rows are part of the documented product coverage target, but are
placeholder-only today.

| Tool | Status | Notes |
|---|---|---|
| `contracts.write` | placeholder row only | Listed in registry/matrix for later-lane contract write coverage |
| `sigmarket.write` | placeholder row only | Listed in registry/matrix for later-lane sigmarket write coverage |
| `admin.high_risk.write` | placeholder row only | Listed in registry/matrix for later-lane admin write coverage |

## Operator notes

- Use this page for grouped operator orientation.
- Use `docs/coverage_matrix.md` for row-by-row contract tracking.
- Use `docs/configuration.md` for path and override behavior (`HF_MCP_CONFIG`,
  `HF_MCP_ENV_FILE`, `HF_MCP_TOKEN_PATH`).
