# Examples

All examples are `JSON-first` and use structured request/response shapes that
match the current public tool registry.

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
  "me": [
    {
      "uid": "1",
      "username": "example_user",
      "usergroup": "4",
      "avatar": "https://example.test/avatar.png"
    }
  ]
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

Response:

```json
{
  "threads": [
    {
      "tid": "123",
      "subject": "Topic title"
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
  "posts": [
    {
      "pid": "88",
      "subject": "Post subject",
      "message": "Post body"
    }
  ]
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

Response:

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

Request:

```json
{
  "tool": "threads.create",
  "arguments": {
    "fid": 101,
    "subject": "Launch thread",
    "message": "Initial post body",
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

Placeholder write rows (`contracts.write`, `sigmarket.write`,
`admin.high_risk.write`) are intentionally excluded from concrete examples
because they are documented coverage rows, not concrete callable behavior today.
