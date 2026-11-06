# Use HF MCP from ChatGPT through a private tunnel

This guide describes a private stdio connection through OpenAI Secure MCP
Tunnel. `tunnel-client` makes outbound HTTPS requests to OpenAI and starts the
local MCP command; the MCP server does not need an inbound public endpoint.
Following these steps does not by itself confirm the setup works; check each
deployment with the local checks and the ChatGPT walkthrough below.

Confirm the installed HF MCP version with `hf-mcp --version` and use a release
that declares support for its installed MCP runtime. Check that release's
package metadata and release notes before setup. The profile and supervisor
examples below are configuration guidance; they do not certify the installed
server or a live ChatGPT connection.

For OpenAI's current network, permissions, CLI and ChatGPT flow, see the
[Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
That guide is the authority for the current Platform and ChatGPT UI labels.

## Prerequisites and permissions

- An HF MCP installation and a Linux host (including WSL) that can reach both
  the private MCP process and OpenAI over outbound HTTPS.
- A completed HF OAuth bootstrap. Keep the HF client credentials and token in
  their existing local secret/config paths.
- A Platform organization with a tunnel associated with the ChatGPT workspace
  that will create and use the private app. These are separate identities; a
  tunnel associated only with a Platform organization might not appear in the
  ChatGPT workspace.
- Tunnel permissions: Read + Manage to create or edit a tunnel; Read + Use to
  run `tunnel-client` or select a tunnel while creating the app. ChatGPT
  workspace permissions and security restrictions also apply.
- The official `tunnel-client` from Platform tunnel settings or the
  [latest openai/tunnel-client release](https://github.com/openai/tunnel-client/releases/latest).
  Before running a downloaded binary, compare its checksum or signature with
  verification metadata published by OpenAI for that release. If the artifact
  has no published checksum or signature, do not label it verified; use a
  Platform-provided binary or obtain verification guidance from OpenAI. Check
  the installed version's help before using the commands below.

The tunnel client needs outbound HTTPS to `api.openai.com:443` (or
`mtls.api.openai.com:443` when using control-plane mTLS) and access to the
configured local stdio command. It does not require inbound internet access to
the MCP server.

## Use all supported tools by default

For the ChatGPT connection, use a dedicated per-consumer YAML with
`profile: full_api`. This profile exposes all 27 supported tools
through this profile; check `hf-mcp --version` and the release notes when using
another release. The package's general fallback profile is `reader`, so select
`full_api` explicitly for this connection. Keep ChatGPT's config separate from
every other agent's settings.

```yaml
profile: full_api
read_output_defaults:
  mode: readable
  include_raw_payload: false
  body_format: markdown
```

Launch the server with that config:

```bash
hf-mcp serve --config /absolute/path/chatgpt.yaml
```

`full_api` includes existing guarded write tools as well as reads. Concrete
writes retain their `confirm_live=true` guard. This guide's validation journey
uses reads only; no write operations were exercised. Do not add forum policy
options to the config: per-forum/per-agent policy controls are not part of the
shipped configuration contract. Review the
[configuration guide](configuration.md) for existing YAML fields and the
[client guide](client_integration.md) for other launch forms.

### Optional: restrict this connection to forum reads

If a deployment wants a smaller read-only tool set, give the ChatGPT tunnel its
own YAML with this `custom` profile. `forums.index` is exposed as
`forums_index` and uses the `forums.read` capability; together these settings
register four tools: `forums_index`, `forums_read`, `threads_read`, and
`posts_read`.

```yaml
profile: custom
enabled_capabilities:
  - forums.read
  - threads.read
  - posts.read
enabled_parameter_families:
  - selectors.forum
  - selectors.thread
  - selectors.post
  - filters.pagination
  - fields.posts.body
  - output.options
read_output_defaults:
  mode: readable
  include_raw_payload: false
  body_format: markdown
```

The `output.options` family keeps `output_mode`, `include_raw_payload` and
`body_format` on these reads (and `view` and `include_inactive` on `forums_index`); a `custom` profile without it drops them from the tool
schemas. This optional profile excludes write capabilities and the `confirm.live`
parameter family. Do not pass `--profile custom` on the command line when using
this YAML: the CLI override replaces its capability overlays. If another agent
also uses `hf-mcp`, preserve its settings in its own config. Sharing an existing
HF token store with a new process changes which process can access those
credentials.

The HF server resolves secrets through its existing local configuration:
`HF_MCP_ENV_FILE` must point to an existing env file, and the HF token store
defaults to `~/.config/hf_mcp/token.json` unless `token_path` or
`HF_MCP_TOKEN_PATH` selects another absolute path. Protect those files locally;
do not place their contents in YAML committed to source control, ChatGPT, logs,
or command arguments.

## Create and run the private tunnel

1. In the intended Platform organization, open Platform tunnel settings and
   create or select the tunnel. Associate it with the ChatGPT workspace that
   will install the app. A Platform organization ID and a ChatGPT workspace ID
   refer to different scopes; use your own values only in the private Platform
   UI and local configuration.
2. Obtain a runtime API key authorized for Tunnels Read + Use. Keep it in the
   protected environment or file reference supported by the installed client;
   never put the literal key in YAML, argv, logs, screenshots, or chat. Creating
   or editing the tunnel requires Read + Manage and is a separate privilege.
3. Check the installed client before selecting options:

   ```bash
   tunnel-client help quickstart
   tunnel-client init --help
   tunnel-client doctor --help
   ```

   The local `tunnel-client` quickstart and sample help confirm this stdio setup:

   ```bash
   tunnel-client init \
     --sample sample_mcp_stdio_local \
     --profile hf-chatgpt \
     --profile-dir /absolute/path/chatgpt-tunnel-profiles \
     --tunnel-id "$CONTROL_PLANE_TUNNEL_ID" \
     --mcp-command "/absolute/path/hf-mcp serve --config /absolute/path/chatgpt.yaml" \
     --control-plane-api-key-ref "file:/absolute/path/control-plane-api-key"
   ```

   `CONTROL_PLANE_TUNNEL_ID` is your tunnel ID. The final flag stores
   only a reference; the referenced file contains the key and must be protected
   locally. The default key reference is `env:CONTROL_PLANE_API_KEY`; do not
   put a literal key in a command, config file, or transcript. `init` creates
   local profile configuration; it does not confirm that the tunnel can connect.
4. Review the generated profile and verify its stdio command runs the absolute
   HF MCP executable with `serve --config /absolute/path/chatgpt.yaml`. Keep
   the restricted profile and secret references local with owner-only
   permissions.
5. Run the client and validate its named profile:

   ```bash
   tunnel-client doctor --profile hf-chatgpt --profile-dir /absolute/path/chatgpt-tunnel-profiles --explain
   tunnel-client run --profile hf-chatgpt --profile-dir /absolute/path/chatgpt-tunnel-profiles
   ```

   Keep the process running while creating the app and during discovery/calls.
   A successful `doctor` validates local profile/configuration conditions; it
   does not show MCP discovery, HF authentication, or a successful read working.

To check the local server, start HF MCP with the dedicated `full_api` config, list
its tools, then call `forums_index` followed by a harmless `forums_read` using a
forum ID returned by the catalog. This checks the local server and HF read path;
it does not test OpenAI tunnel connectivity or ChatGPT app discovery.

Use one supervised `tunnel-client` process for this profile. A user systemd
service can keep it running and restart it after an unexpected exit; use the
absolute path and profile supported by the installed client. Keep the unit,
profile, and secret references dedicated to this integration. Do not run a
second overlapping client during restart or upgrade.

For a per-user systemd service, use the following shape with the actual paths:

```ini
[Unit]
Description=HF MCP through OpenAI Secure MCP Tunnel
After=network-online.target

[Service]
Type=simple
ExecStart=/absolute/path/tunnel-client run --profile hf-chatgpt --profile-dir /absolute/path/chatgpt-tunnel-profiles
Environment=HF_MCP_ENV_FILE=/absolute/path/to/private/hf-mcp-chatgpt.env
Restart=on-failure
RestartSec=5
UMask=0077
KillMode=control-group
NoNewPrivileges=true

[Install]
WantedBy=default.target
```

Before enabling the unit, create the referenced env file at the selected absolute
path with the HF client settings required by your installation (including
`HF_MCP_CLIENT_ID` and `HF_MCP_CLIENT_SECRET`). Restrict the file to its owner,
for example mode `0600` inside a `0700` directory. Do not put secret values in
the unit or tunnel profile. `HF_MCP_ENV_FILE` passes the existing file path to
the HF child process so it loads those settings at startup; the path must exist
when the service starts.

Install the unit under the user's systemd config directory, then enable and
start it with `systemctl --user enable --now hf-mcp-chatgpt.service`.

If Codex manages this long-lived runtime, the local quickstart recommends
`tunnel-client runtimes connect` followed by
`tunnel-client runtimes status <alias>`; it explicitly advises against
`nohup`/`disown` supervision. The standalone ChatGPT setup here uses the
dedicated systemd unit described below.

For local health checks, the client exposes `/healthz`, `/readyz`, `/metrics`,
and a local admin UI at `/ui` (loopback-only by default). The checked sample
uses `127.0.0.1:8080`; use the address in your profile if it differs. The help
also supports `--health.unix-socket` or `HEALTH_UNIX_SOCKET` for serving
health/admin over a Unix socket instead of TCP. Keep the endpoint private.
Check service state and local logs through the supervisor; review/redact logs
before sharing them. Readiness means the tunnel client is ready, not that the
HF server authenticated or that ChatGPT can call it.

Example checks for a user systemd unit named `hf-mcp-chatgpt.service`:

```bash
systemctl --user status hf-mcp-chatgpt.service
journalctl --user -u hf-mcp-chatgpt.service -n 50 --no-pager
systemctl --user restart hf-mcp-chatgpt.service
systemctl --user stop hf-mcp-chatgpt.service
```

If the service exits, inspect its local logs and profile, run `doctor` again,
then start the same unit and recheck readiness. During recovery, in-flight calls
may fail and need a fresh ChatGPT request. Never retry or replay a write
automatically. On rollback, stop and disable only this dedicated service,
confirm its client/child process has exited, remove only its unit/profile, and
uninstall only its private ChatGPT app. Revoke a dedicated tunnel key or delete
the tunnel only after checking that no other consumer uses it; preserve shared
HF authentication and other agents' configurations. Disable the dedicated
service with `systemctl --user disable --now hf-mcp-chatgpt.service` as part of
rollback.

## Add the server in ChatGPT

Use ChatGPT web in the workspace associated with the tunnel:

1. Open [ChatGPT Plugins](https://chatgpt.com/plugins), select the plus button,
   and choose **Add custom MCP server**.
2. Name the app, choose **Tunnel** for **Connection**, and select the available
   tunnel or enter its tunnel ID if the UI offers that choice.
3. Configure the authentication layer requested by the current UI, review the
   risk warning, select **I understand and want to continue**, then create the
   plugin. Do not enter HF OAuth credentials into ChatGPT. Tunnel authorization
   and HF server authentication are separate layers.
4. Install or enable the resulting private app in that workspace and refresh
   its available tools. With the default `full_api` profile, expect all 27
   currently supported tools. If you deliberately selected the optional custom
   read profile, expect only `forums_index`, `forums_read`, `threads_read`, and
   `posts_read`.
5. In a conversation, select the custom app using the current tool/app picker
   and make a harmless read journey:

   - Call `forums_index` to get the maintained local forum catalog. It is a
     discovery aid, not a live scrape and does not show that HF authentication works.
   - Choose a returned forum ID, then call `forums_read` with that `fid`,
     `page: 1`, and `per_page: 1` to check the authenticated HF read path.

Only tool discovery plus a successful harmless read in ChatGPT confirms the
end-to-end setup. Local profile validation, health readiness, and available
tool toggles alone do not. The walkthrough above uses read calls only; test
write calls separately and deliberately.

If the tunnel is missing in ChatGPT, check its ChatGPT workspace association
and the app operator's Tunnels Read + Use permission. If discovery or calls
fail, first confirm the client is running and ready, then inspect local tunnel
and HF child logs. Keep the service running while ChatGPT polls it.

## Windows and WSL availability

When the MCP process runs in WSL, a Windows desktop client can launch it with
`wsl.exe`; see the path-neutral example in
[`client_integration.md`](client_integration.md). A running Linux user service
or WSL linger setting does not by itself mean Windows will start the
distribution after sign-in or reboot. If automatic WSL startup is configured,
test it after a real logout/login and reboot, then check service readiness,
tool discovery, and a harmless read. Until those checks pass, reboot
persistence is unverified. The Windows host must remain awake and connected;
shutdown, sleep, or lost network access interrupts the tunnel.

## Sources

- [OpenAI Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
- [Latest official tunnel-client release](https://github.com/openai/tunnel-client/releases/latest)
- [HF MCP configuration](configuration.md)
- [HF MCP desktop client integration](client_integration.md)
