# Configuration

`hf-mcp` uses YAML for runtime policy and environment variables for secrets and machine-local auth/bootstrap overrides.

## Config paths and overrides

Authoritative defaults:

- default config path: `~/.config/hf_mcp/config.yaml`
- default token path: `~/.config/hf_mcp/token.json`

Resolution order:

1. Config path:
- CLI `--config` (when provided)
- `HF_MCP_CONFIG`
- default `~/.config/hf_mcp/config.yaml`

2. `.env` file:
- `HF_MCP_ENV_FILE` (must point to an existing file)
- adjacent `.env` next to the selected config path
- no `.env` file loaded when neither exists

3. Token path:
- YAML `token_path`
- `HF_MCP_TOKEN_PATH`
- default `~/.config/hf_mcp/token.json`

4. Draft artifact directory:
- explicit tool argument `draft_dir`
- YAML `draft_dir`
- `HF_MCP_DRAFT_DIR`
- default `~/.config/hf_mcp/drafts`

5. Templates directory:
- YAML `templates_dir`
- `HF_MCP_TEMPLATES_DIR`
- default `~/.config/hf_mcp/templates`

Token-path constraints:

- token paths must be absolute
- token-store location must resolve to an absolute path outside the tracked repository
- relative `token_path` values fail config resolution
- CLI `--token-path` is translated to `HF_MCP_TOKEN_PATH` before settings load

## YAML vs `.env` responsibilities

YAML is the canonical runtime config input for non-secret policy.
Use YAML (`config.yaml`) for non-secret runtime policy:

- `profile`
- `enabled_capabilities`
- `disabled_capabilities`
- `enabled_parameter_families`
- `disabled_parameter_families`
- `templates_dir`
- `read_output_defaults.mode`
- `read_output_defaults.include_raw_payload`
- `read_output_defaults.body_format`
- optional `token_path`

Use env (`.env` or shell) for secrets and machine-local auth/bootstrap settings:
Environment variables must not be used to choose non-secret runtime policy.

- `HF_MCP_CLIENT_ID`
- `HF_MCP_CLIENT_SECRET`
- `HF_MCP_CONFIG`
- `HF_MCP_ENV_FILE`
- `HF_MCP_TOKEN_PATH`
- `HF_MCP_DRAFT_DIR`
- `HF_MCP_TEMPLATES_DIR`
- `HF_MCP_EXTERNAL_REDIRECT_URI`
- `HF_MCP_REDIRECT_URI`
- `HF_MCP_AUTHORIZE_URL`
- `HF_MCP_TOKEN_URL`
- `HF_MCP_AUTH_TIMEOUT_SECONDS`

Before running `hf-mcp auth bootstrap`, create your own Hack Forums API developer
app in the HF user control panel. The app's client ID and client secret belong in
local env/config only.

Redirect options:

- use the hosted callback: `https://cortalabs.github.io/hf_mcp/oauth_callback.html`
- or host `docs/oauth_callback.html` yourself and set `HF_MCP_EXTERNAL_REDIRECT_URI`
  to your own HTTPS URL

Example `.env`:

```bash
HF_MCP_CLIENT_ID=your_app_client_id
HF_MCP_CLIENT_SECRET=your_app_client_secret
HF_MCP_EXTERNAL_REDIRECT_URI=https://cortalabs.github.io/hf_mcp/oauth_callback.html
```

Merge behavior:

- `.env` values load first
- process environment wins on key conflicts

## Read output defaults

Read tools use this YAML block for default output behavior:

```yaml
read_output_defaults:
  mode: readable
  include_raw_payload: false
  body_format: markdown
```

Mode options:

- `readable` (default): rich human-readable text plus canonical `structuredContent`; thread reads include formatted first-post body content when Hack Forums returns it
- `structured`: terse text plus canonical `structuredContent` for script compatibility
- `raw`: terse text plus canonical `structuredContent`, with the exact upstream payload attached as an additive JSON resource

Per-call read-tool overrides:

- `output_mode` overrides `read_output_defaults.mode` for that call
- `include_raw_payload` overrides `read_output_defaults.include_raw_payload` for that call

Raw payload remains additive. `structuredContent` stays normalized/canonical for scripts even when raw payload is included.

PM support boundary:

- PM counters (`unreadpms`, `totalpms`) can be returned by `me.read` when Advanced Info fields are enabled.
- Direct PM content operations are unsupported in this package surface.

Body-format options:

- `markdown` (default): convert MyCode/BBCode body fields such as `message` into simple Markdown for agents
- `clean`: strip formatting tags and keep readable text/URLs
- `raw`: preserve upstream MyCode body text

When `output_mode: raw` is selected, `body_format` resolves to `raw` unless explicitly overridden for that call.

## Post templates

`templates.list` and `templates.render` read your own named templates from
`templates_dir`. `~` is expanded, and the result must be an absolute path; a relative or non-string value
fails settings load. A missing directory simply means zero templates, and none ship
with the package. Both tools belong to the `templates.read` capability, which the
`reader`, `forum_operator` and `full_api` profiles enable.

A template is a file named `<name>.md` (Markdown) or `<name>.mycode` (MyCode) directly
in that directory. The name uses lowercase letters, digits, `_` and `-`, starts with a
letter or digit, and is at most 64 characters. Files in subdirectories and files with
other extensions are ignored. Each template must follow these rules:

- It is a regular file, not a symlink, valid UTF-8, and at most 64 KiB.
- It opens with a `---` front-matter block that may contain only `description` and
  `placeholders` (both optional), then a closing `---`, then the body.
- Each placeholder is declared under `placeholders` by a key (a lowercase letter, then
  up to 31 lowercase letters, digits or `_`), with an optional `description` and an
  optional `required` flag (default `true`).
- The body writes placeholders as `{{key}}`. Every placeholder used in the body must be
  declared, and every declared key must be used.

```markdown
---
description: Weekly update post
placeholders:
  week:
    description: Week number
  summary:
    description: One-line summary
    required: false
---
# Update for week {{week}}

{{summary}}
```

A file that breaks any rule is invalid: it is counted in `invalid_count`, never listed,
and no path or file text is returned. A duplicate name counts as invalid too, and at
most 256 candidate files are read per call; any further candidates count as invalid and are never read. `templates.render` takes the template
`name` and a `values` object of strings, inserts them literally in one pass, and returns
the filled `source_text` and the Hack Forums `mycode` with any `conversion_findings`.
It refuses unknown or missing required values, and a result over 500,000 characters.
Nothing is saved and nothing is sent.

## Profiles and overlays

Profiles:

- `reader`
- `forum_operator`
- `full_api`
- `custom`

Overlay fields are additive/subtractive and validated against known names:

- `enabled_capabilities`
- `disabled_capabilities`
- `enabled_parameter_families`
- `disabled_parameter_families`

Unknown capability or parameter-family names fail settings load.

Profile sizes: `reader` registers 18 tools, `forum_operator` 23 and `full_api` 27;
`custom` starts with none. A tool registers only when its capability is enabled and
every parameter family it requires is enabled.

The `output.options` parameter family carries `output_mode`, `include_raw_payload` and
`body_format` on the read tools, plus `view` and `include_inactive` on `forums.index`. The presets include it. A `custom` profile must list
`output.options` in `enabled_parameter_families` to keep those arguments; without it
they are removed from the published schema.

Free-text messages and sources (tool arguments, converter input and rendered templates)
share one limit of 500,000 characters, and a draft source file is limited to 500,000 bytes. Titles, categories and
subjects are limited to 512 characters and file selectors to 4,096; longer values are
refused.

## Setup, bootstrap, and doctor paths

Commands below share the same path-resolution model above for config and token state:

- `hf-mcp setup init`
- `hf-mcp auth bootstrap`
- `hf-mcp auth status`
- `hf-mcp doctor`
- `hf-mcp serve`

Write-tool draft notes:

- `scheduled_at` in draft artifacts is metadata only and is never auto-executed by an internal scheduler.
- Draft publish only happens when a concrete live write call is made with `confirm_live=true`.

## Draft directory default rationale

`hf-mcp` defaults draft artifacts to `~/.config/hf_mcp/drafts` for portable local behavior:

- It keeps generated draft content outside tracked repositories by default.
- It aligns with the existing config/token defaults under `~/.config/hf_mcp/`.
- It works across Linux/macOS and WSL-backed workflows without hard-coding project paths.

Use YAML `draft_dir` or `HF_MCP_DRAFT_DIR` when your local workflow needs a different location.

Operational notes:

- `hf-mcp setup init` writes YAML config (`profile`, optional `token_path`) and prints next-step commands.
- `hf-mcp auth bootstrap` prints resolved config path + token path after success.
- `hf-mcp auth status` prints resolved config path + token path and token presence.
- `hf-mcp doctor` is local-only readiness validation and prints config/env/token status plus next steps.

## Example

```yaml
profile: reader

read_output_defaults:
  mode: readable
  include_raw_payload: false

disabled_capabilities:
  - sigmarket.market.read
  - sigmarket.order.read

disabled_parameter_families:
  - fields.me.advanced
```
