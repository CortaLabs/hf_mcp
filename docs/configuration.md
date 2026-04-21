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
- optional `token_path`

Use env (`.env` or shell) for secrets and machine-local auth/bootstrap settings:
Environment variables must not be used to choose non-secret runtime policy.

- `HF_MCP_CLIENT_ID`
- `HF_MCP_CLIENT_SECRET`
- `HF_MCP_CONFIG`
- `HF_MCP_ENV_FILE`
- `HF_MCP_TOKEN_PATH`
- `HF_MCP_EXTERNAL_REDIRECT_URI`
- `HF_MCP_REDIRECT_URI`
- `HF_MCP_AUTHORIZE_URL`
- `HF_MCP_TOKEN_URL`
- `HF_MCP_AUTH_TIMEOUT_SECONDS`

Merge behavior:

- `.env` values load first
- process environment wins on key conflicts

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

## Setup, bootstrap, and doctor path truth

Commands below share the same path-resolution model above for config and token state:

- `hf-mcp setup init`
- `hf-mcp auth bootstrap`
- `hf-mcp auth status`
- `hf-mcp doctor`
- `hf-mcp serve`

Operational notes:

- `hf-mcp setup init` writes YAML config (`profile`, optional `token_path`) and prints next-step commands.
- `hf-mcp auth bootstrap` prints resolved config path + token path after success.
- `hf-mcp auth status` prints resolved config path + token path and token presence.
- `hf-mcp doctor` is local-only readiness validation and prints config/env/token status plus next steps.

## Example

```yaml
profile: reader

disabled_capabilities:
  - sigmarket.market.read
  - sigmarket.order.read

disabled_parameter_families:
  - fields.me.advanced
```
