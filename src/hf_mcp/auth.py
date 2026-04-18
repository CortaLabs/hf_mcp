from __future__ import annotations

import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Mapping

from .config import (
    DEFAULT_LOOPBACK_REDIRECT_URI,
    HOSTED_MODE_LOOPBACK_CALLBACK_URI,
    HFMCPSettings,
)
from .token_store import TokenBundle

DEFAULT_AUTHORIZE_ENDPOINT = "https://hackforums.net/api/v2/authorize"


def authorize_via_loopback(settings: HFMCPSettings, open_browser: bool = True) -> TokenBundle:
    client_id = _required_setting(settings, "HF_MCP_CLIENT_ID")
    client_secret = _required_setting(settings, "HF_MCP_CLIENT_SECRET")

    external_redirect_uri = settings.runtime_env.get("HF_MCP_EXTERNAL_REDIRECT_URI", "").strip()
    if external_redirect_uri:
        redirect_uri = _validate_external_redirect_uri(external_redirect_uri)
        callback_redirect_uri = HOSTED_MODE_LOOPBACK_CALLBACK_URI
    else:
        redirect_uri = settings.runtime_env.get("HF_MCP_REDIRECT_URI", DEFAULT_LOOPBACK_REDIRECT_URI)
        callback_redirect_uri = redirect_uri

    authorize_url = settings.runtime_env.get("HF_MCP_AUTHORIZE_URL", DEFAULT_AUTHORIZE_ENDPOINT)
    token_url = settings.runtime_env.get("HF_MCP_TOKEN_URL", DEFAULT_AUTHORIZE_ENDPOINT)

    timeout_raw = settings.runtime_env.get("HF_MCP_AUTH_TIMEOUT_SECONDS", "180")
    try:
        timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("HF_MCP_AUTH_TIMEOUT_SECONDS must be an integer number of seconds.") from exc

    state = secrets.token_urlsafe(24)
    browser_url = _build_authorize_url(
        authorize_url=authorize_url,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
    )

    if open_browser:
        webbrowser.open(browser_url)

    callback_params = _await_loopback_callback(
        redirect_uri=callback_redirect_uri,
        timeout_seconds=timeout_seconds,
    )
    callback_state = callback_params.get("state")
    if callback_state != state:
        raise ValueError("OAuth callback state mismatch. Aborting token exchange.")

    code = callback_params.get("code")
    if code is None or not code.strip():
        raise ValueError("OAuth callback is missing authorization code.")

    token_payload = _exchange_code_for_token(
        token_url=token_url,
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=redirect_uri,
    )
    return TokenBundle.from_payload(token_payload)


def _build_authorize_url(
    authorize_url: str,
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    separator = "&" if "?" in authorize_url else "?"
    return f"{authorize_url}{separator}{params}"


def _await_loopback_callback(redirect_uri: str, timeout_seconds: int) -> Mapping[str, str]:
    parsed_uri = urllib.parse.urlparse(redirect_uri)
    host = parsed_uri.hostname
    port = parsed_uri.port
    callback_path = parsed_uri.path or "/callback"

    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Redirect URI must use localhost or 127.0.0.1 loopback host.")
    if port is None:
        raise ValueError("Redirect URI must include an explicit loopback port.")

    callback_state: dict[str, str] = {}

    class _CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (standard library method name)
            parsed_request = urllib.parse.urlparse(self.path)
            if parsed_request.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return

            parsed_query = urllib.parse.parse_qs(parsed_request.query, keep_blank_values=True)
            for key in ("code", "state", "error"):
                values = parsed_query.get(key)
                if values:
                    callback_state[key] = values[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"You can close this tab and return to the terminal.")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            del format, args
            return

    server = HTTPServer((host, port), _CallbackHandler)
    server.timeout = 0.25

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline and "code" not in callback_state and "error" not in callback_state:
        server.handle_request()

    server.server_close()

    if "error" in callback_state:
        raise ValueError(f"OAuth provider returned error: {callback_state['error']}")
    if "code" not in callback_state:
        raise TimeoutError("Timed out waiting for OAuth loopback callback.")
    return callback_state


def _exchange_code_for_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> dict[str, object]:
    encoded_payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        token_url,
        data=encoded_payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Token exchange failed: HTTP {error.code}. {error_body}") from error

    parsed = json.loads(response_body)
    if not isinstance(parsed, dict):
        raise ValueError("Token exchange returned non-object JSON payload.")
    return parsed


def _required_setting(settings: HFMCPSettings, name: str) -> str:
    value = settings.runtime_env.get(name) or os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()


def _validate_external_redirect_uri(redirect_uri: str) -> str:
    parsed_uri = urllib.parse.urlparse(redirect_uri)
    host = parsed_uri.hostname
    if parsed_uri.scheme != "https" or host is None:
        raise ValueError(
            "Invalid HF_MCP_EXTERNAL_REDIRECT_URI: hosted redirect URI must be a valid HTTPS URL."
        )
    if host in {"127.0.0.1", "localhost"}:
        raise ValueError(
            "Invalid HF_MCP_EXTERNAL_REDIRECT_URI: hosted redirect URI cannot use a loopback host."
        )
    return redirect_uri


__all__ = ["authorize_via_loopback"]
