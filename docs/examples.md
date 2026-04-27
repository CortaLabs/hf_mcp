# Examples

All examples are `JSON-first` and use structured request/response shapes that
match the current public tool registry.

## Zero-ID exploration chain (`forums.index`)

Use `forums.index` (alias `forums_index`) as local catalog-backed root discovery
when you do not yet have IDs.

- Concrete chain: `forums.index` -> `forums.read` -> `threads.read` -> `posts.read`
- `forums.read` still requires `fid`; it is not root discovery.
- `_hf_flow` is the machine-readable flow key and currently appears on
  `forums.index`, core reads, supported extended reads (`bytes.read`,
  `contracts.read`, `disputes.read`, `bratings.read`,
  `sigmarket.market.read`, and `sigmarket.order.read`), local
  draft/preflight tools, and successful results from existing guarded write
  helpers after confirmed or stubbed execution.
- The forums index is maintained package data and can drift from live HF.

Request:

```json
{
  "tool": "forums.index",
  "arguments": {
    "view": "flat"
  }
}
```

Response text shown to the client:

```text
forums.index loaded 41 node(s) in flat view (forums=36, categories=5, include_inactive=False).
```

Structured sidecar (excerpt):

```json
{
  "nodes": [
    {
      "fid": 444,
      "name": "Tech",
      "active": true,
      "is_category": true
    },
    {
      "fid": 460,
      "name": "Artificial Intelligence",
      "active": true,
      "is_category": false,
      "parent_fid": 444,
      "category_fid": 444
    },
    {
      "fid": 375,
      "name": "HF API",
      "active": true,
      "is_category": false,
      "parent_fid": 151,
      "category_fid": 444
    }
  ],
  "_hf_flow": {
    "entry_tool": "forums.index",
    "breadcrumbs": ["forum_catalog", "forums.index"],
    "next_actions": [
      {"tool": "forums.read", "arguments": {"fid": 375}, "label": "Load forum 375"}
    ]
  }
}
```

For `view="tree"`, the same `_hf_flow.next_actions` are emitted from nested
forum nodes, so category grouping does not break the next-tool handoff.

## Read output modes (`threads.read`)

Read tools accept per-call output overrides:

- `output_mode`: `readable` (default), `structured`, or `raw`
- `include_raw_payload`: optional additive raw JSON payload toggle
- `body_format`: `markdown` (default), `clean`, or `raw` for MyCode/BBCode body fields

### Default readable output

Request:

```json
{
  "tool": "threads.read",
  "arguments": {
    "fid": 375,
    "page": 1,
    "per_page": 10
  }
}
```

Response text shown to the client:

```text
threads.read returned 1 thread(s).

## Topic title

### Thread fields
- tid: 123
- fid: 375
- subject: Topic title
- uid: 5
- username: alice

### First post fields
- firstpost.pid: 456
- firstpost.author.uid: 5
- firstpost.author.username: alice

### Thread body

**Launch notes**

This is the thread body returned from `firstpost.message`.
```

The same call still returns canonical `structuredContent` for automation clients:

```json
{
  "threads": [
    {
      "tid": "123",
      "fid": "375",
      "subject": "Topic title",
      "uid": "5",
      "username": "alice",
      "firstpost": {
        "pid": "456",
        "message": "**Launch notes**\n\nThis is the thread body returned from `firstpost.message`.",
        "author": {
          "uid": "5",
          "username": "alice"
        }
      }
    }
  ]
}
```

### Explicit structured compatibility output

Request:

```json
{
  "tool": "threads.read",
  "arguments": {
    "fid": 375,
    "output_mode": "structured"
  }
}
```

Response (illustrative):

```json
{
  "content": [
    {
      "type": "text",
      "text": "threads.read returned 1 row(s)."
    }
  ],
  "structuredContent": {
    "threads": [
      {
        "tid": "123",
        "fid": "375",
        "subject": "Topic title",
        "uid": "5",
        "username": "alice"
      }
    ]
  }
}
```

### Explicit raw output

Request:

```json
{
  "tool": "threads.read",
  "arguments": {
    "fid": 375,
    "output_mode": "raw"
  }
}
```

Response (illustrative):

```json
{
  "content": [
    {
      "type": "text",
      "text": "threads.read returned 1 row(s)."
    },
    {
      "type": "resource",
      "resource": {
        "uri": "hf-mcp://raw/threads.read",
        "mimeType": "application/json",
        "text": "{\"threads\":[{\"tid\":\"123\",\"fid\":\"375\",\"subject\":\"Topic title\",\"uid\":\"5\",\"username\":\"alice\"}]}"
      }
    }
  ],
  "structuredContent": {
    "threads": [
      {
        "tid": "123",
        "fid": "375",
        "subject": "Topic title",
        "uid": "5",
        "username": "alice"
      }
    ]
  }
}
```

## Body formatting (`posts.read`)

By default, post body fields are normalized for agents by converting common
MyCode/BBCode into simple Markdown. Use `body_format="clean"` to strip noisy
formatting or `body_format="raw"` to preserve upstream MyCode.

Request:

```json
{
  "tool": "posts.read",
  "arguments": {
    "tid": 123,
    "pid": 88,
    "body_format": "markdown"
  }
}
```

StructuredContent excerpt:

```json
{
  "posts": [
    {
      "pid": "88",
      "message": "**Bold** [link](https://example.test)"
    }
  ]
}
```

## `me.read`

Request:

```json
{
  "tool": "me.read",
  "arguments": {
    "include_basic_fields": true,
    "include_advanced_fields": false
  }
}
```

Response:

```json
{
  "content": [
    {
      "type": "text",
      "text": "me.read profile: uid=1, username=example_user, usergroup=4, usertitle=Member, postnum=250, threadnum=12, reputation=42, bytes=1000"
    }
  ],
  "structuredContent": {
    "me": [
      {
        "uid": "1",
        "username": "example_user",
        "usergroup": "4",
        "displaygroup": "4",
        "additionalgroups": "",
        "postnum": "250",
        "awards": "0",
        "bytes": "1000",
        "threadnum": "12",
        "avatar": "https://example.test/avatar.png",
        "avatardimensions": "100|100",
        "avatartype": "remote",
        "lastvisit": "1777046400",
        "usertitle": "Member",
        "website": "https://example.test",
        "timeonline": "3600",
        "reputation": "42",
        "referrals": "0"
      }
    ]
  }
}
```

## `threads.read` (forum-anchored, `fid` required)

Request:

```json
{
  "tool": "threads.read",
  "arguments": {
    "fid": 375,
    "page": 1,
    "per_page": 30
  }
}
```

Response text shown to the client:

```text
threads.read returned 1 row(s):
- tid=123, fid=375, subject=Topic title, uid=5, username=alice
```

Structured sidecar:

```json
{
  "threads": [
    {
      "tid": "123",
      "fid": "375",
      "subject": "Topic title",
      "uid": "5",
      "username": "alice"
    }
  ]
}
```

## `posts.read` (thread-anchored, `tid` required)

Request:

```json
{
  "tool": "posts.read",
  "arguments": {
    "tid": 123,
    "pid": 88,
    "include_post_body": true
  }
}
```

Response:

```json
{
  "content": [
    {
      "type": "text",
      "text": "posts.read returned 1 row(s):\n- pid=88, tid=123, fid=375, uid=5, subject=Post subject, message=Post body"
    }
  ],
  "structuredContent": {
    "posts": [
      {
        "pid": "88",
        "tid": "123",
        "fid": "375",
        "uid": "5",
        "subject": "Post subject",
        "message": "Post body"
      }
    ]
  }
}
```

## Extended browse-first read: `disputes.read`

Canonical selector is `cdid` (optional). Legacy alias support exists for
`did` and `dispute_id` for compatibility, but `cdid` is the canonical public
selector in docs.

Request:

```json
{
  "tool": "disputes.read",
  "arguments": {
    "cdid": 11,
    "uid": 99,
    "page": 1,
    "per_page": 20
  }
}
```

StructuredContent excerpt (illustrative):

```json
{
  "disputes": [
    {
      "cdid": "11",
      "contractid": "7",
      "claimantuid": "99",
      "defendantuid": "77",
      "dateline": "1710001000",
      "status": "1",
      "dispute_tid": "4321",
      "claimantnotes": "note a",
      "defendantnotes": "note b"
    }
  ]
}
```

## Guarded write: `threads.create`

Concrete writes require `confirm_live=true`.
Content writes accept `message_format`. Omit it or use `mycode` when `message`
already contains HF MyCode; use `markdown` to convert common Markdown into HF
MyCode before sending.

Request:

```json
{
  "tool": "threads.create",
  "arguments": {
    "fid": 101,
    "subject": "Launch thread",
    "message": "**Launch notes**\n\n- first item\n- second item",
    "message_format": "markdown",
    "confirm_live": true
  }
}
```

Response:

The write helper forwards the upstream Hack Forums response body from
`/write/threads` without local normalization. The JSON below is illustrative,
not a guaranteed contract shape.

```json
{
  "threads": {
    "tid": "98765"
  }
}
```

`contracts.write` is intentionally excluded from runnable examples because it is
not exposed without operator-approved sandbox proof. Signature Market writes and
admin-only high-risk writes are also unsupported and unexposed in the current
registered surface.

## Guarded write: `bytes.transfer`

Request (illustrative shape):

```json
{
  "tool": "bytes.transfer",
  "arguments": {
    "target_uid": 42,
    "amount": 10,
    "note": "Example transfer payload",
    "confirm_live": true
  }
}
```

Response (illustrative):

```json
{
  "bytes": {
    "status": "ok"
  }
}
```

Use fake transport/local test lanes for routine verification. Live mutations
stay operator-controlled.

## Draft metadata and scheduling truth

Draft artifacts may include metadata fields such as `scheduled_at`, but this is
metadata only for operator workflow and review. `hf-mcp` does not ship an
internal scheduler that auto-runs queued writes. A live write still requires an
explicit concrete call such as `threads.create` or `posts.reply` with
`confirm_live=true`.

## Quote/entity canonicalization note for live writes

HF can canonicalize quote-heavy content (for example, converting literal quotes
or numeric quote entities to `&quot;`) when content is published through the API.
Treat this as expected HF security/sanitization behavior. Do not rely on
pre-encoding quotes as a guaranteed bypass.
