---
name: hf-mcp-bootstrap
description: Install and local bootstrap workflow for hf-mcp including config precedence, auth bootstrap, doctor, and serve readiness
user-invocable: true
context: full
visibility: exported
owner: hackforums-council
---

# HF MCP Bootstrap

Use this skill for local hf-mcp setup and readiness, from first install through `setup init`, `auth bootstrap`, `doctor`, and `serve`.

## Trigger Conditions

- The user needs first-run setup for `hf-mcp`.
- The task is about config/env/token path resolution.
- The task is about `auth bootstrap`, `auth status`, `doctor`, or local serve readiness.
- The user needs hosted callback or loopback callback reminders.

## Inputs

- Runtime surface: `hf-mcp` CLI or `python -m hf_mcp`.
- Local config path (if non-default) and token path preference.
- Whether required auth env vars are already set.
- Whether hosted callback mode (`HF_MCP_EXTERNAL_REDIRECT_URI`) is needed.

## Procedure

1. Install and confirm entrypoints.
   Run `pip install hf-mcp`, then use `hf-mcp` or `python -m hf_mcp`.
   Primary commands: `setup init`, `auth bootstrap`, `auth status`, `doctor`, `serve`.

2. Apply path/env precedence correctly.
   Config path precedence:
   - CLI `--config`
   - `HF_MCP_CONFIG`
   - default `~/.config/hf_mcp/config.yaml`
   .env file precedence:
   - `HF_MCP_ENV_FILE` (must exist)
   - adjacent `.env` next to selected config path
   - none loaded if neither exists
   Token path precedence:
   - YAML `token_path`
   - `HF_MCP_TOKEN_PATH`
   - default `~/.config/hf_mcp/token.json`

3. Keep YAML-first policy for non-secret runtime policy.
   Put non-secret policy in YAML (`profile`, enabled/disabled capabilities, enabled/disabled parameter families, optional `token_path`).
   Use environment variables for secrets and machine-local auth/bootstrap overrides (`HF_MCP_CLIENT_ID`, `HF_MCP_CLIENT_SECRET`, redirect and bootstrap envs).

4. Run setup and auth flow.
   Start with `hf-mcp setup init`.
   Continue with `hf-mcp auth bootstrap`.
   Bootstrap requires `HF_MCP_CLIENT_ID` and `HF_MCP_CLIENT_SECRET`, prints authorization URL, waits for callback, saves token, and prints resolved config/token paths.

5. Select callback mode explicitly.
   Hosted mode: set `HF_MCP_EXTERNAL_REDIRECT_URI` to a non-loopback HTTPS URL; local listener target stays `http://127.0.0.1:8765/callback`.
   Legacy loopback mode: if hosted env is unset, use `HF_MCP_REDIRECT_URI` or default loopback callback.
   Callback host must be `127.0.0.1` or `localhost` with explicit port.
   In Windows-to-WSL launches, do not assume universal browser auto-open behavior; rely on the printed authorization URL when needed.

6. Validate readiness before serving.
   Run `hf-mcp auth status` for token/config visibility.
   Run `hf-mcp doctor` for local-only readiness checks; it validates config resolution, env prerequisites, profile override validity, and token state.
   Run `hf-mcp serve` only after doctor reports ready.

7. Hand off API internals to `hf-api-v2`.
   If the user asks for full OAuth/API mechanics or raw `asks` payload design, route to `hf-api-v2` instead of expanding this bootstrap skill into an API tutorial.

8. Keep draft scheduling claims truthful.
   If draft metadata includes `scheduled_at`, treat it as metadata only.
   There is no built-in scheduler/queue that executes live writes automatically.

## Verification

- Confirm resolved config and token paths are explicitly shown after bootstrap/status.
- Confirm `HF_MCP_CLIENT_ID` and `HF_MCP_CLIENT_SECRET` are present before bootstrap.
- Confirm token path is absolute and outside tracked repo paths.
- Confirm doctor guidance is treated as local-only readiness evidence.
- Confirm serve is only recommended after doctor readiness is true.

## Output / Handoff

- A concrete local command sequence for the user's current state.
- Explicit path/env values the user must set or correct.
- Clear next-step handoff to `hf-mcp-reads`, `hf-mcp-writes`, or `hf-api-v2` after bootstrap is complete.

## Boundaries

- Do not redefine or loosen path/env precedence rules.
- Do not move non-secret runtime policy from YAML into ad hoc env usage.
- Do not claim `doctor` performs network calls or remote validation.
- Do not present write automation as part of bootstrap.
