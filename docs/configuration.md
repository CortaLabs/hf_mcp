# Configuration

`hf-mcp` uses a presets-first configuration model with fail-closed overlays.

## Config paths and overrides

Authoritative default paths:

- default config path: `~/.config/hf_mcp/config.yaml`
- default token path: `~/.config/hf_mcp/token.json`

Path resolution order:

1. Config path:
   - CLI `--config` (when provided)
   - `HF_MCP_CONFIG`
   - default `~/.config/hf_mcp/config.yaml`
2. `.env` file path:
   - `HF_MCP_ENV_FILE` (must point to an existing file)
   - adjacent `.env` next to the selected config path
   - no `.env` loaded if neither exists
3. Token path:
   - YAML `token_path` in selected config file
   - `HF_MCP_TOKEN_PATH`
   - default `~/.config/hf_mcp/token.json`

Operational note:

- `hf-mcp setup init` writes `profile` to the selected config path and can persist
  `token_path` if `--token-path` is provided.
- `hf-mcp auth bootstrap`, `hf-mcp auth status`, `hf-mcp doctor`, and `hf-mcp serve`
  all resolve paths through the same config loader behavior above.

## Scope and exposure control

The product scope is the full documented Hack Forums API surface captured in the
coverage matrix. Configuration is an exposure control mechanism for the active
user or deployment:

- `enabled_capabilities` and `disabled_capabilities` decide which tool families
  can register.
- `enabled_parameter_families` and `disabled_parameter_families` decide which
  schema inputs remain visible and accepted.

This means a deployment can disable `sigmarket`, `contract`, or
`admin/high-risk` rows without redefining the product target.

Output-contract boundary (published in metadata/annotations):

- `x-hf-output-default=structured` means canonical structured payloads are the default contract.
- `x-hf-output-readable=additive` means any readable/operator rendering is additive-only and cannot replace structured data.
- `x-hf-output-field-bundles=separate_from_rendering` means field-bundle controls are independent of rendering mode.
- Extended read selector contract is browse-first optional-filter:
  `contracts.read` => `cid` (optional), optional `uid`;
  `disputes.read` => `did` (optional), optional `uid`;
  `bratings.read` => optional `uid`;
  `sigmarket.market.read` => optional `uid`;
  `sigmarket.order.read` => `oid` (optional), optional `uid`.

## Profiles

- `reader`: read-oriented exposure profile.
- `forum_operator`: read + core forum/content/bytes write exposure.
- `full_api`: broadest shipped exposure profile.
- `custom`: starts empty; caller opts in explicitly.

`reader` is the recommended first-run profile. Use `full_api` as an explicit
opt-in when validating the full documented coverage surface.

## First-run setup flow

Run the terminal-native onboarding commands in this order:

```bash
pip install hf-mcp
hf-mcp setup init
```

Then set local secrets (for example in `.env` or shell):

```bash
export HF_MCP_CLIENT_ID=your_client_id
export HF_MCP_CLIENT_SECRET=your_client_secret
```

Complete auth/bootstrap and local readiness validation:

```bash
hf-mcp auth bootstrap
hf-mcp doctor
hf-mcp serve
```

Hosted callback contract:

- Hosted mode (recommended): host `docs/oauth_callback.html` (for example on GitHub Pages), set
  `HF_MCP_EXTERNAL_REDIRECT_URI` to that hosted HTTPS callback URL, and register the same URL in
  your Hack Forums developer app settings (example:
  `https://cortalabs.github.io/hf_mcp/oauth_callback.html`).
- Hosted mode always forwards from the hosted page to the fixed local callback target:
  `http://127.0.0.1:8765/callback`.
- Legacy fallback: if `HF_MCP_EXTERNAL_REDIRECT_URI` is unset, `HF_MCP_REDIRECT_URI` remains the
  loopback-only redirect URI input (for example `http://127.0.0.1:8765/callback`).

## Runtime configuration responsibilities

- YAML is the canonical runtime config input for non-secret policy:
  `profile`, capability overlays, parameter-family overlays, and optional
  `token_path`.
- `.env` is for secrets and machine-local overrides only (for example
  `HF_MCP_CLIENT_ID`, `HF_MCP_CLIENT_SECRET`, `HF_MCP_TOKEN_PATH`,
  `HF_MCP_EXTERNAL_REDIRECT_URI`, `HF_MCP_REDIRECT_URI`).
- Callback URI inputs are machine-local auth settings from env (`.env`/shell), not YAML policy
  keys.
- `.env` must not be used to choose non-secret runtime policy such as
  `profile`, capability families, or parameter families.
- `token_path` must resolve to an absolute path outside the tracked repository.

## Overlays

Overlays are additive/subtractive and always validated against known family
names:

- `enabled_capabilities`
- `disabled_capabilities`
- `enabled_parameter_families`
- `disabled_parameter_families`

Unknown names fail fast during config load.

## Example

```yaml
profile: reader

disabled_capabilities:
  - sigmarket.market.read
  - sigmarket.order.read

disabled_parameter_families:
  - fields.me.advanced
```

The example above is still the same product. It is a narrower exposure profile
for one deployment.
