# Auth Bootstrap

This page documents the shipped behavior of `hf-mcp auth bootstrap`, `hf-mcp auth status`, and `hf-mcp doctor`.

## Command surfaces

- `hf-mcp auth bootstrap [--config PATH] [--token-path ABS_PATH] [--open-browser | --no-browser]`
- `hf-mcp auth status [--config PATH] [--token-path ABS_PATH]`
- `hf-mcp doctor [--config PATH] [--token-path ABS_PATH] [--profile PROFILE]`

## Bootstrap flow

`hf-mcp auth bootstrap`:

1. Resolves config and token store from config/env/CLI overrides.
2. Requires `HF_MCP_CLIENT_ID` and `HF_MCP_CLIENT_SECRET`.
3. Builds authorization URL with `client_id`, `response_type=code`, `redirect_uri`, and OAuth `state`.
4. Optionally opens browser, then waits for loopback callback.
5. Exchanges code for token via POST (`grant_type=authorization_code`).
6. Saves token bundle to resolved token path.
7. Prints:
- `Config path: ...`
- `Token path: ...`
- `Token saved: yes`
- `Granted scopes: ...`

Failure path returns exit code `2` with `Auth bootstrap failed: ...`.

Before bootstrap, create your own Hack Forums API developer app from the HF user
control panel. `hf-mcp` does not ship shared credentials; each operator uses
their own app client ID and secret.

For the OAuth redirect, you have two supported options:

- use the hosted GitHub Pages callback:
  `https://cortalabs.github.io/hf_mcp/oauth_callback.html`
- host the included `docs/oauth_callback.html` yourself and use that HTTPS URL

Example local `.env`:

```bash
HF_MCP_CLIENT_ID=your_app_client_id
HF_MCP_CLIENT_SECRET=your_app_client_secret
HF_MCP_EXTERNAL_REDIRECT_URI=https://cortalabs.github.io/hf_mcp/oauth_callback.html
```

## Hosted callback and loopback behavior

Bootstrap redirect selection:

- Hosted mode: if `HF_MCP_EXTERNAL_REDIRECT_URI` is set, it must be a non-loopback HTTPS URL.
- In hosted mode, local callback listener target is fixed to `http://127.0.0.1:8765/callback`.
- Legacy loopback mode: if `HF_MCP_EXTERNAL_REDIRECT_URI` is unset, bootstrap uses `HF_MCP_REDIRECT_URI` or default `http://127.0.0.1:8765/callback`.

Loopback callback constraints:

- callback host must be `127.0.0.1` or `localhost`
- callback URI must include explicit port
- callback state must match generated OAuth state
- timeout raises `Timed out waiting for OAuth loopback callback.`

Onboarding helper constants used by CLI guidance/doctor:

- hosted callback artifact path: `docs/oauth_callback.html`
- hosted external redirect env var: `HF_MCP_EXTERNAL_REDIRECT_URI`
- hosted example callback URL: `https://cortalabs.github.io/hf_mcp/oauth_callback.html`
- legacy redirect env var: `HF_MCP_REDIRECT_URI`
- fixed local callback target: `http://127.0.0.1:8765/callback`

## Browser behavior flags

`auth bootstrap` supports mutually exclusive flags:

- `--open-browser`: force browser open
- `--no-browser`: force no browser open

Default when neither is passed:

- opens browser on non-WSL environments
- does not auto-open on WSL environments

Authorization URL is always printed to stdout (`Authorization URL: ...`) before callback wait.

## Windows desktop client + WSL reality check

When a desktop client runs on Windows but launches `hf-mcp` inside WSL:

- Browser behavior depends on where the process is running and client shell behavior.
- Do not assume universal auto-open support in this mode; copy/paste the printed authorization URL when needed.
- Hosted callback mode still targets the local loopback listener (`http://127.0.0.1:8765/callback`) in the runtime environment where bootstrap is running.

See `docs/client_integration.md` for concrete Windows-native and Windows-to-WSL launch patterns.

## Auth/bootstrap env variables

Required secrets:

- `HF_MCP_CLIENT_ID`
- `HF_MCP_CLIENT_SECRET`

Callback/bootstrap routing:

- `HF_MCP_EXTERNAL_REDIRECT_URI`
- `HF_MCP_REDIRECT_URI`

Shipped bootstrap knobs:

- `HF_MCP_AUTHORIZE_URL` (authorize endpoint override)
- `HF_MCP_TOKEN_URL` (token endpoint override)
- `HF_MCP_AUTH_TIMEOUT_SECONDS` (callback wait timeout in seconds, integer)

## Token path, status, and doctor truth

Token path behavior:

- effective token path resolves from YAML `token_path`, `HF_MCP_TOKEN_PATH`, or default
- CLI `--token-path` must be absolute and is applied via env override before load

`hf-mcp auth status` output:

- `Config path: ...`
- `Token path: ...`
- `Token present: yes|no`
- `Granted scopes: ...`

`hf-mcp doctor` behavior:

- local-only readiness check (no network calls)
- validates config resolution, profile override validity, required env vars, token file state
- prints readiness summary and next-step commands
- returns `0` when ready, `2` when prerequisites are missing/invalid
