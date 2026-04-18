# Configuration

`hf-mcp` uses a presets-first configuration model with fail-closed overlays.

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

## Runtime configuration responsibilities

- YAML is the canonical runtime config input for non-secret policy:
  `profile`, capability overlays, parameter-family overlays, and optional
  `token_path`.
- `.env` is for secrets and machine-local overrides only (for example
  `HF_MCP_CLIENT_ID`, `HF_MCP_CLIENT_SECRET`, `HF_MCP_TOKEN_PATH`).
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
