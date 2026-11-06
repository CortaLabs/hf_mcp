from __future__ import annotations

import io
import json
import logging
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import hf_mcp.auth as auth_module
from hf_mcp.auth import authorize_via_loopback
from hf_mcp.cli import main
from hf_mcp.config import HFMCPSettings
from hf_mcp.token_store import TokenBundle, TokenStore, load_token_store
from hf_mcp.transport import HFAPIError

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"


def _settings(
    *,
    config_path: Path | None = None,
    token_path: Path | None = None,
    runtime_env: dict[str, str] | None = None,
) -> HFMCPSettings:
    return HFMCPSettings(
        profile="full_api",
        enabled_capabilities=frozenset({"posts.read"}),
        enabled_parameter_families=frozenset({"selectors.thread"}),
        config_path=config_path or (Path.home() / ".config/hf_mcp/config.yaml"),
        token_path=token_path or (Path.home() / ".config/hf_mcp/token.json"),
        runtime_env=runtime_env or {},
    )


def test_authorize_via_loopback_rejects_state_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr(
        "hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test"
    )
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda redirect_uri, timeout_seconds: {"code": "abc", "state": "wrong-state"},
    )
    exchange_calls: list[object] = []

    def _exchange_spy(**kwargs: str) -> dict[str, object]:
        exchange_calls.append(kwargs)
        return {"access_token": "token", "token_type": "Bearer", "scope": "Basic Info"}

    monkeypatch.setattr("hf_mcp.auth._exchange_code_for_token", _exchange_spy)

    with pytest.raises(ValueError, match="state mismatch"):
        authorize_via_loopback(
            _settings(
                runtime_env={
                    "HF_MCP_CLIENT_ID": "client",
                    "HF_MCP_CLIENT_SECRET": "secret",
                    "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
                }
            ),
            open_browser=False,
        )
    assert exchange_calls == []


def test_authorize_via_loopback_rejects_missing_authorization_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr(
        "hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test"
    )
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda redirect_uri, timeout_seconds: {"state": "expected-state"},
    )
    exchange_calls: list[object] = []
    monkeypatch.setattr(
        "hf_mcp.auth._exchange_code_for_token",
        lambda **kwargs: exchange_calls.append(kwargs) or {},
    )

    with pytest.raises(ValueError, match="missing authorization code"):
        authorize_via_loopback(
            _settings(
                runtime_env={
                    "HF_MCP_CLIENT_ID": "client",
                    "HF_MCP_CLIENT_SECRET": "secret",
                    "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
                }
            ),
            open_browser=False,
        )
    assert exchange_calls == []


@pytest.mark.parametrize("missing_name", ["HF_MCP_CLIENT_ID", "HF_MCP_CLIENT_SECRET"])
def test_authorize_via_loopback_requires_client_secrets(
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    runtime_env = {
        "HF_MCP_CLIENT_ID": "client",
        "HF_MCP_CLIENT_SECRET": "secret",
        "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
    }
    runtime_env.pop(missing_name)

    with pytest.raises(ValueError, match=missing_name):
        authorize_via_loopback(_settings(runtime_env=runtime_env), open_browser=False)


def test_authorize_via_loopback_successful_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr(
        "hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test/authorize"
    )
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda redirect_uri, timeout_seconds: {
            "code": "abc",
            "state": "expected-state",
        },
    )

    exchange_inputs: dict[str, str] = {}
    exchange_count: list[int] = []

    def _fake_exchange(**kwargs: str) -> dict[str, object]:
        exchange_count.append(1)
        exchange_inputs.update(kwargs)
        return {"access_token": "token", "token_type": "Bearer", "scope": "Basic Info"}

    monkeypatch.setattr("hf_mcp.auth._exchange_code_for_token", _fake_exchange)

    bundle = authorize_via_loopback(
        _settings(
            runtime_env={
                "HF_MCP_CLIENT_ID": "client",
                "HF_MCP_CLIENT_SECRET": "secret",
                "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
            }
        ),
        open_browser=False,
    )
    assert len(exchange_count) == 1

    assert bundle.access_token == "token"
    assert bundle.token_type == "Bearer"
    assert exchange_inputs["client_id"] == "client"
    assert exchange_inputs["client_secret"] == "secret"
    assert exchange_inputs["code"] == "abc"
    assert "redirect_uri" not in exchange_inputs


def test_exchange_code_for_token_uses_documented_form_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        def read(self) -> bytes:
            return (
                b'{"access_token":"token","token_type":"Bearer","scope":"Basic Info"}'
            )

    def _fake_urlopen(request: object, timeout: int) -> _FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("hf_mcp.auth.urllib.request.urlopen", _fake_urlopen)

    token_payload = auth_module._exchange_code_for_token(
        token_url="https://hackforums.net/api/v2/authorize",
        client_id="client",
        client_secret="secret",
        code="auth-code",
    )

    assert token_payload["access_token"] == "token"
    request = captured["request"]
    assert isinstance(request, auth_module.urllib.request.Request)
    body_bytes = request.data
    assert isinstance(body_bytes, bytes)
    form_fields = urllib.parse.parse_qs(
        body_bytes.decode("utf-8"), keep_blank_values=True
    )
    assert form_fields == {
        "grant_type": ["authorization_code"],
        "client_id": ["client"],
        "client_secret": ["secret"],
        "code": ["auth-code"],
    }
    assert "redirect_uri" not in form_fields
    assert request.headers["User-agent"] == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )


def test_authorize_via_loopback_announces_authorization_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr(
        "hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test/authorize"
    )
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda redirect_uri, timeout_seconds: {
            "code": "abc",
            "state": "expected-state",
        },
    )
    monkeypatch.setattr(
        "hf_mcp.auth._exchange_code_for_token",
        lambda **_: {
            "access_token": "token",
            "token_type": "Bearer",
            "scope": "Basic Info",
        },
    )

    announced: list[str] = []
    authorize_via_loopback(
        _settings(
            runtime_env={
                "HF_MCP_CLIENT_ID": "client",
                "HF_MCP_CLIENT_SECRET": "secret",
                "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
            }
        ),
        open_browser=False,
        announce_authorize_url=announced.append,
    )

    assert announced == ["https://example.test/authorize"]


def test_authorize_via_loopback_hosted_mode_uses_external_redirect_and_fixed_local_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")

    authorize_inputs: dict[str, str] = {}
    callback_inputs: dict[str, object] = {}
    exchange_inputs: dict[str, str] = {}

    def _fake_build_authorize_url(**kwargs: str) -> str:
        authorize_inputs.update(kwargs)
        return "https://example.test/authorize"

    def _fake_await_loopback_callback(
        redirect_uri: str, timeout_seconds: int
    ) -> dict[str, str]:
        callback_inputs["redirect_uri"] = redirect_uri
        callback_inputs["timeout_seconds"] = timeout_seconds
        return {"code": "abc", "state": "expected-state"}

    def _fake_exchange(**kwargs: str) -> dict[str, object]:
        exchange_inputs.update(kwargs)
        return {"access_token": "token", "token_type": "Bearer", "scope": "Basic Info"}

    monkeypatch.setattr("hf_mcp.auth._build_authorize_url", _fake_build_authorize_url)
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback", _fake_await_loopback_callback
    )
    monkeypatch.setattr("hf_mcp.auth._exchange_code_for_token", _fake_exchange)

    bundle = authorize_via_loopback(
        _settings(
            runtime_env={
                "HF_MCP_CLIENT_ID": "client",
                "HF_MCP_CLIENT_SECRET": "secret",
                "HF_MCP_EXTERNAL_REDIRECT_URI": "https://example.github.io/hf-callback/",
                "HF_MCP_REDIRECT_URI": "http://127.0.0.1:9999/not-used",
            }
        ),
        open_browser=False,
    )

    assert bundle.access_token == "token"
    assert authorize_inputs["redirect_uri"] == "https://example.github.io/hf-callback/"
    assert callback_inputs["redirect_uri"] == "http://127.0.0.1:8765/callback"
    assert "redirect_uri" not in exchange_inputs


def test_authorize_via_loopback_hosted_mode_rejects_state_mismatch_before_token_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr(
        "hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test/authorize"
    )

    callback_inputs: dict[str, object] = {}
    exchange_called = False

    def _fake_await_loopback_callback(
        redirect_uri: str, timeout_seconds: int
    ) -> dict[str, str]:
        callback_inputs["redirect_uri"] = redirect_uri
        callback_inputs["timeout_seconds"] = timeout_seconds
        return {"code": "abc", "state": "wrong-state"}

    def _should_not_exchange(**kwargs: str) -> dict[str, object]:
        nonlocal exchange_called
        del kwargs
        exchange_called = True
        raise AssertionError(
            "token exchange should not run after callback state mismatch"
        )

    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback", _fake_await_loopback_callback
    )
    monkeypatch.setattr("hf_mcp.auth._exchange_code_for_token", _should_not_exchange)

    with pytest.raises(ValueError, match="state mismatch"):
        authorize_via_loopback(
            _settings(
                runtime_env={
                    "HF_MCP_CLIENT_ID": "client",
                    "HF_MCP_CLIENT_SECRET": "secret",
                    "HF_MCP_EXTERNAL_REDIRECT_URI": "https://example.github.io/hf-callback/",
                    "HF_MCP_REDIRECT_URI": "http://127.0.0.1:9999/not-used",
                }
            ),
            open_browser=False,
        )

    assert callback_inputs["redirect_uri"] == "http://127.0.0.1:8765/callback"
    assert exchange_called is False


@pytest.mark.parametrize(
    "external_redirect",
    [
        "http://example.github.io/hf-callback/",
        "https://127.0.0.1:8765/callback",
        "not-a-uri",
    ],
)
def test_authorize_via_loopback_rejects_invalid_hosted_external_redirect(
    monkeypatch: pytest.MonkeyPatch,
    external_redirect: str,
) -> None:
    called = {"callback": False, "exchange": False}

    def _should_not_callback(redirect_uri: str, timeout_seconds: int) -> dict[str, str]:
        del redirect_uri, timeout_seconds
        called["callback"] = True
        raise AssertionError(
            "callback listener should not start for invalid hosted config"
        )

    def _should_not_exchange(**kwargs: str) -> dict[str, object]:
        del kwargs
        called["exchange"] = True
        raise AssertionError("token exchange should not run for invalid hosted config")

    monkeypatch.setattr("hf_mcp.auth._await_loopback_callback", _should_not_callback)
    monkeypatch.setattr("hf_mcp.auth._exchange_code_for_token", _should_not_exchange)

    with pytest.raises(ValueError, match="HF_MCP_EXTERNAL_REDIRECT_URI"):
        authorize_via_loopback(
            _settings(
                runtime_env={
                    "HF_MCP_CLIENT_ID": "client",
                    "HF_MCP_CLIENT_SECRET": "secret",
                    "HF_MCP_EXTERNAL_REDIRECT_URI": external_redirect,
                }
            ),
            open_browser=False,
        )

    assert called["callback"] is False
    assert called["exchange"] is False


def test_auth_bootstrap_saves_bundle_through_token_store(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config_path = (tmp_path / "config.yaml").resolve()
    token_path = (tmp_path / "token.json").resolve()
    settings = _settings(config_path=config_path, token_path=token_path, runtime_env={})

    captured: dict[str, object] = {}

    class _StubTokenStore:
        def __init__(self, path: Path) -> None:
            self.path = path

        def save_bundle(self, bundle: TokenBundle) -> None:
            captured["saved"] = bundle

    stub_store = _StubTokenStore(token_path)

    def _fake_load_settings(
        config_path: Path | None, env: dict[str, str] | None = None
    ) -> HFMCPSettings:
        captured["config_path"] = config_path
        captured["env"] = dict(env or {})
        return settings

    monkeypatch.setattr("hf_mcp.cli.load_settings", _fake_load_settings)
    monkeypatch.setattr("hf_mcp.cli.load_token_store", lambda _: stub_store)

    def _fake_authorize(
        settings: HFMCPSettings,
        open_browser: bool = True,
        announce_authorize_url: Any | None = None,
    ) -> TokenBundle:
        del settings
        captured["open_browser"] = open_browser
        assert callable(announce_authorize_url)
        announce_authorize_url("https://example.test/authorize")
        return TokenBundle(
            access_token="token", token_type="Bearer", scope=frozenset({"posts.read"})
        )

    monkeypatch.setattr("hf_mcp.cli.authorize_via_loopback", _fake_authorize)

    exit_code = main(
        [
            "auth",
            "bootstrap",
            "--config",
            str(config_path),
            "--token-path",
            str(token_path),
            "--no-browser",
        ]
    )
    out = capsys.readouterr()

    assert exit_code == 0
    assert captured["config_path"] == config_path
    assert captured["env"]["HF_MCP_TOKEN_PATH"] == str(token_path)
    assert captured["open_browser"] is False
    assert isinstance(captured["saved"], TokenBundle)
    assert "Authorization URL: https://example.test/authorize" in out.out
    assert out.out.index(
        "Authorization URL: https://example.test/authorize"
    ) < out.out.index("Token saved: yes")
    assert "Token saved: yes" in out.out


def test_auth_bootstrap_defaults_to_no_browser_on_wsl(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = (tmp_path / "config.yaml").resolve()
    token_path = (tmp_path / "token.json").resolve()
    settings = _settings(config_path=config_path, token_path=token_path, runtime_env={})
    captured: dict[str, object] = {}

    class _StubTokenStore:
        def __init__(self, path: Path) -> None:
            self.path = path

        def save_bundle(self, bundle: TokenBundle) -> None:
            captured["saved"] = bundle

    monkeypatch.setattr(
        "hf_mcp.cli.load_settings", lambda config_path, env=None: settings
    )
    monkeypatch.setattr(
        "hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(token_path)
    )
    monkeypatch.setattr("hf_mcp.cli._is_wsl_environment", lambda: True)

    def _fake_authorize(
        settings: HFMCPSettings,
        open_browser: bool = True,
        announce_authorize_url: Any | None = None,
    ) -> TokenBundle:
        del settings, announce_authorize_url
        captured["open_browser"] = open_browser
        return TokenBundle(
            access_token="token", token_type="Bearer", scope=frozenset({"posts.read"})
        )

    monkeypatch.setattr("hf_mcp.cli.authorize_via_loopback", _fake_authorize)

    exit_code = main(
        [
            "auth",
            "bootstrap",
            "--config",
            str(config_path),
            "--token-path",
            str(token_path),
        ]
    )
    assert exit_code == 0
    assert captured["open_browser"] is False
    assert isinstance(captured["saved"], TokenBundle)


def test_auth_bootstrap_open_browser_overrides_wsl_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = (tmp_path / "config.yaml").resolve()
    token_path = (tmp_path / "token.json").resolve()
    settings = _settings(config_path=config_path, token_path=token_path, runtime_env={})
    captured: dict[str, object] = {}

    class _StubTokenStore:
        def __init__(self, path: Path) -> None:
            self.path = path

        def save_bundle(self, bundle: TokenBundle) -> None:
            captured["saved"] = bundle

    monkeypatch.setattr(
        "hf_mcp.cli.load_settings", lambda config_path, env=None: settings
    )
    monkeypatch.setattr(
        "hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(token_path)
    )
    monkeypatch.setattr("hf_mcp.cli._is_wsl_environment", lambda: True)

    def _fake_authorize(
        settings: HFMCPSettings,
        open_browser: bool = True,
        announce_authorize_url: Any | None = None,
    ) -> TokenBundle:
        del settings, announce_authorize_url
        captured["open_browser"] = open_browser
        return TokenBundle(
            access_token="token", token_type="Bearer", scope=frozenset({"posts.read"})
        )

    monkeypatch.setattr("hf_mcp.cli.authorize_via_loopback", _fake_authorize)

    exit_code = main(
        [
            "auth",
            "bootstrap",
            "--config",
            str(config_path),
            "--token-path",
            str(token_path),
            "--open-browser",
        ]
    )
    assert exit_code == 0
    assert captured["open_browser"] is True
    assert isinstance(captured["saved"], TokenBundle)


def test_auth_bootstrap_missing_secrets_returns_clear_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(runtime_env={})

    class _StubTokenStore:
        def __init__(self, path: Path) -> None:
            self.path = path

        def save_bundle(self, bundle: TokenBundle) -> None:
            del bundle
            raise AssertionError(
                "save_bundle should not be called when bootstrap fails"
            )

    monkeypatch.setattr(
        "hf_mcp.cli.load_settings", lambda config_path, env=None: settings
    )
    monkeypatch.setattr(
        "hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(settings.token_path)
    )
    monkeypatch.setattr(
        "hf_mcp.cli.authorize_via_loopback",
        lambda settings, open_browser=True, announce_authorize_url=None: (
            _ for _ in ()
        ).throw(ValueError("Missing required environment variable: HF_MCP_CLIENT_ID")),
    )

    exit_code = main(["auth", "bootstrap"])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert (
        "Auth bootstrap failed: Missing required environment variable: HF_MCP_CLIENT_ID"
        in err
    )


def test_auth_status_reports_local_state_without_network_calls(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config_path = (tmp_path / "config.yaml").resolve()
    token_path = (tmp_path / "token.json").resolve()
    settings = _settings(config_path=config_path, token_path=token_path, runtime_env={})

    class _StubTokenStore:
        def __init__(self, path: Path) -> None:
            self.path = path

        def load_bundle(self) -> TokenBundle | None:
            return TokenBundle(
                access_token="token",
                token_type="Bearer",
                scope=frozenset({"posts.read", "threads.read"}),
            )

    monkeypatch.setattr(
        "hf_mcp.cli.load_settings", lambda config_path, env=None: settings
    )
    monkeypatch.setattr(
        "hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(token_path)
    )

    called = {"authorize": False}

    def _should_not_authorize(
        settings: HFMCPSettings, open_browser: bool = True
    ) -> TokenBundle:
        del settings, open_browser
        called["authorize"] = True
        raise AssertionError("status must not call authorize_via_loopback")

    monkeypatch.setattr("hf_mcp.cli.authorize_via_loopback", _should_not_authorize)

    exit_code = main(
        [
            "auth",
            "status",
            "--config",
            str(config_path),
            "--token-path",
            str(token_path),
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert called["authorize"] is False
    assert f"Config path: {config_path}" in out
    assert f"Token path: {token_path}" in out
    assert "Token present: yes" in out
    assert "Granted scopes: posts.read threads.read" in out


def test_auth_status_token_error_returns_clear_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = _settings(runtime_env={})

    class _StubTokenStore:
        def __init__(self, path: Path) -> None:
            self.path = path

        def load_bundle(self) -> TokenBundle | None:
            raise PermissionError(
                "Token file permissions are too broad. Expected owner-only access (0600)."
            )

    monkeypatch.setattr(
        "hf_mcp.cli.load_settings", lambda config_path, env=None: settings
    )
    monkeypatch.setattr(
        "hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(settings.token_path)
    )

    exit_code = main(["auth", "status"])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "Auth status failed: Token file permissions are too broad." in err


def test_load_token_store_rejects_repo_relative_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_MCP_TOKEN_PATH", "products/hf_mcp/token.json")
    with pytest.raises(ValueError, match="absolute path"):
        load_token_store(_settings())


# --- private token file and quiet auth failures (HF-R2-AUTH) -------------

MARKER = "SEEDED-SECRET-MARKER"


def _write_token(path: Path, mode: int = 0o600) -> None:
    path.write_text(
        json.dumps({"access_token": MARKER, "token_type": "Bearer", "scope": ["a"]}),
        encoding="utf-8",
    )
    path.chmod(mode)


def _bundle() -> TokenBundle:
    return TokenBundle(access_token=MARKER, token_type="Bearer", scope=frozenset({"a"}))


def test_token_round_trips_and_legacy_0600_file_loads(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "sub" / "token.json")
    store.save_bundle(_bundle())
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.path.parent.stat().st_mode) == 0o700
    assert store.load_bundle() == _bundle()

    legacy = tmp_path / "legacy.json"
    _write_token(legacy)
    assert TokenStore(legacy).load_bundle() == _bundle()
    assert TokenStore(tmp_path / "missing.json").load_bundle() is None


@pytest.mark.parametrize("mode", [0o400, 0o640, 0o644, 0o700])
def test_load_rejects_non_0600_modes(tmp_path: Path, mode: int) -> None:
    path = tmp_path / "token.json"
    _write_token(path, mode)
    with pytest.raises(PermissionError) as caught:
        TokenStore(path).load_bundle()
    assert MARKER not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def test_load_rejects_foreign_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "token.json"
    _write_token(path)
    owner = path.stat().st_uid
    monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
    with pytest.raises(PermissionError):
        TokenStore(path).load_bundle()


def test_load_rejects_links_fifo_and_directory(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    _write_token(real)
    link = tmp_path / "link.json"
    link.symlink_to(real)
    dangling = tmp_path / "dangling.json"
    dangling.symlink_to(tmp_path / "nowhere.json")
    fifo = tmp_path / "fifo.json"
    os.mkfifo(fifo, 0o600)
    directory = tmp_path / "dir.json"
    directory.mkdir(mode=0o600)
    for path in (link, dangling, fifo, directory):
        with pytest.raises(PermissionError) as caught:
            TokenStore(path).load_bundle()
        assert MARKER not in str(caught.value)
        assert str(path) not in str(caught.value)


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xfe",
        b"{not json",
        b"[1]",
        b'{"access_token": ""}',
        b'{"x":"' + MARKER.encode(),
    ],
)
def test_load_invalid_content_is_fixed_value_error(
    tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "token.json"
    path.write_bytes(content)
    path.chmod(0o600)
    with pytest.raises(ValueError) as caught:
        TokenStore(path).load_bundle()
    assert str(caught.value) == "Token file content is invalid."
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_require_missing_is_auth_unavailable_and_load_never_writes(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    store = TokenStore(empty / "token.json")
    with pytest.raises(HFAPIError) as caught:
        store.require_bundle()
    assert caught.value.error["code"] == "AUTH_UNAVAILABLE"
    assert caught.value.error["operation"] == "local"
    assert list(empty.iterdir()) == []

    bad = tmp_path / "bad.json"
    _write_token(bad, 0o644)
    before = (bad.stat().st_mode, bad.read_bytes())
    with pytest.raises(PermissionError):
        TokenStore(bad).load_bundle()
    assert (bad.stat().st_mode, bad.read_bytes()) == before


def test_load_token_store_keeps_final_symlink_unresolved(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    _write_token(target)
    link = tmp_path / "link.json"
    link.symlink_to(target)
    store = load_token_store(
        _settings(token_path=link, runtime_env={"HF_MCP_TOKEN_PATH": str(link)})
    )
    assert store.path == link
    with pytest.raises(PermissionError):
        store.load_bundle()


def test_save_ignores_predictable_tmp_symlink_trap(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    path = tmp_path / "token.json"
    (tmp_path / "token.json.tmp").symlink_to(victim)
    TokenStore(path).save_bundle(_bundle())
    assert victim.read_text(encoding="utf-8") == "keep"
    assert TokenStore(path).load_bundle() == _bundle()


def test_save_over_symlink_replaces_link_not_target(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    path = tmp_path / "token.json"
    path.symlink_to(victim)
    TokenStore(path).save_bundle(_bundle())
    assert victim.read_text(encoding="utf-8") == "keep"
    assert not path.is_symlink()


def test_interrupted_save_keeps_prior_file_and_leaves_no_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    path = work / "token.json"
    _write_token(path)
    before = path.read_bytes()

    def _boom(*_: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", _boom)
    other = TokenBundle(access_token="other", token_type="Bearer", scope=frozenset())
    with pytest.raises(OSError):
        TokenStore(path).save_bundle(other)
    assert path.read_bytes() == before
    assert [p.name for p in work.iterdir()] == ["token.json"]


def test_save_never_chmods_existing_directory(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    TokenStore(tmp_path / "token.json").save_bundle(_bundle())
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755


def test_clear_removes_regular_file_only(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    _write_token(path)
    TokenStore(path).clear()
    TokenStore(path).clear()
    assert not path.exists()

    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(victim)
    with pytest.raises(PermissionError):
        TokenStore(link).clear()
    assert victim.exists() and link.is_symlink()


def test_loopback_provider_error_param_is_not_reflected(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)

    class _FakeRequest:
        def __init__(self, path: str) -> None:
            self.path = path
            self.wfile = io.BytesIO()

        def send_response(self, _: int) -> None:
            return None

        def send_header(self, *_: str) -> None:
            return None

        def end_headers(self) -> None:
            return None

    class _FakeServer:
        def __init__(self, address: tuple[str, int], handler: Any) -> None:
            self._handler = handler
            self.timeout = 0.0

        def handle_request(self) -> None:
            request = _FakeRequest(f"/callback?error={MARKER}&state={MARKER}")
            self._handler.do_GET(request)

        def server_close(self) -> None:
            return None

    monkeypatch.setattr(auth_module, "HTTPServer", _FakeServer)
    with pytest.raises(HFAPIError) as caught:
        auth_module._await_loopback_callback(
            "http://127.0.0.1:8765/callback", timeout_seconds=10
        )
    assert caught.value.error["code"] == "AUTH_REJECTED"
    assert MARKER not in str(caught.value)
    assert caught.value.__cause__ is None
    captured = capsys.readouterr()
    assert MARKER not in captured.err + captured.out + caplog.text


def test_loopback_state_mismatch_is_quiet(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: MARKER + "-a")
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda **_: {"code": MARKER, "state": MARKER + "-b"},
    )
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ValueError) as caught:
        authorize_via_loopback(
            _settings(
                runtime_env={
                    "HF_MCP_CLIENT_ID": "client",
                    "HF_MCP_CLIENT_SECRET": MARKER,
                    "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
                }
            ),
            open_browser=False,
        )
    assert MARKER not in str(caught.value)
    captured = capsys.readouterr()
    assert MARKER not in captured.err + captured.out + caplog.text


def test_token_store_failures_are_quiet(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    caplog.set_level(logging.DEBUG)
    bad_mode = tmp_path / "mode.json"
    _write_token(bad_mode, 0o644)
    bad_content = tmp_path / "content.json"
    bad_content.write_bytes(b'{"x":"' + MARKER.encode())
    bad_content.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(bad_mode)
    for path in (bad_mode, bad_content, link):
        with pytest.raises((PermissionError, ValueError)) as caught:
            TokenStore(path).load_bundle()
        assert MARKER not in str(caught.value) and str(tmp_path) not in str(
            caught.value
        )

    with pytest.raises(HFAPIError) as missing:
        TokenStore(tmp_path / "absent.json").require_bundle()
    assert str(tmp_path) not in str(missing.value)

    work = tmp_path / "work"
    work.mkdir()

    def _boom(*_: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        TokenStore(work / "token.json").save_bundle(_bundle())
    captured = capsys.readouterr()
    assert MARKER not in captured.err + captured.out + caplog.text
    assert str(tmp_path) not in captured.err + captured.out + caplog.text


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _exchange() -> dict[str, object]:
    return auth_module._exchange_code_for_token(
        token_url="https://hackforums.net/api/v2/authorize",
        client_id="client",
        client_secret=MARKER,
        code=MARKER,
    )


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://x.test",
        status,
        MARKER,
        {},
        io.BytesIO(MARKER.encode()),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("make_error", "code"),
    [
        (lambda: _http_error(400), "AUTH_REJECTED"),
        (lambda: _http_error(401), "AUTH_REJECTED"),
        (lambda: _http_error(403), "AUTH_REJECTED"),
        (lambda: _http_error(429), "RATE_LIMITED"),
        (lambda: _http_error(500), "UPSTREAM_UNAVAILABLE"),
        (lambda: _http_error(503), "UPSTREAM_UNAVAILABLE"),
        (lambda: _http_error(404), "UPSTREAM_REJECTED"),
        (lambda: _http_error(302), "UPSTREAM_REJECTED"),
        (lambda: urllib.error.URLError(MARKER), "NETWORK_ERROR"),
        (lambda: urllib.error.URLError(TimeoutError(MARKER)), "TIMEOUT"),
        (lambda: TimeoutError(MARKER), "TIMEOUT"),
        (lambda: ConnectionResetError(MARKER), "NETWORK_ERROR"),
    ],
)
def test_exchange_transport_failures_are_fixed_safe_categories(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    make_error: Callable[[], BaseException],
    code: str,
) -> None:
    calls: list[object] = []

    def _urlopen(request: object, timeout: int) -> _Resp:
        calls.append(request)
        raise make_error()

    monkeypatch.setattr("hf_mcp.auth.urllib.request.urlopen", _urlopen)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(HFAPIError) as caught:
        _exchange()
    err = caught.value
    assert len(calls) == 1
    assert err.error["code"] == code
    assert err.error["operation"] == "local"
    assert err.__cause__ is None and err.__context__ is None
    assert MARKER not in str(err) and MARKER not in repr(err.error)
    captured = capsys.readouterr()
    assert MARKER not in captured.err + captured.out + caplog.text


@pytest.mark.parametrize(
    "body",
    [b"\xff\xfe", b"{" + MARKER.encode(), b"[1]", b'"' + MARKER.encode() + b'"'],
)
def test_exchange_unreadable_body_is_protocol_error(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    monkeypatch.setattr(
        "hf_mcp.auth.urllib.request.urlopen", lambda request, timeout: _Resp(body)
    )
    with pytest.raises(HFAPIError) as caught:
        _exchange()
    assert caught.value.error["code"] == "UPSTREAM_PROTOCOL_ERROR"
    assert MARKER not in str(caught.value)
    assert caught.value.__context__ is None


def test_token_payload_without_access_token_is_protocol_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "s")
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda **_: {"code": "abc", "state": "s"},
    )
    monkeypatch.setattr(
        "hf_mcp.auth._exchange_code_for_token", lambda **_: {"token_type": MARKER}
    )
    settings = _settings(
        runtime_env={
            "HF_MCP_CLIENT_ID": "client",
            "HF_MCP_CLIENT_SECRET": "secret",
            "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
        }
    )
    with pytest.raises(HFAPIError) as caught:
        authorize_via_loopback(settings, open_browser=False)
    assert caught.value.error["code"] == "UPSTREAM_PROTOCOL_ERROR"
    assert MARKER not in str(caught.value)


@pytest.mark.parametrize("env_name", ["HF_MCP_TOKEN_URL", "HF_MCP_AUTHORIZE_URL"])
@pytest.mark.parametrize(
    "bad_url",
    [
        "http://" + "evil.test/" + MARKER,
        "evil.test/" + MARKER,
        "https:///" + MARKER,
        "ftp://evil.test/" + MARKER,
        "",
    ],
)
def test_non_https_endpoint_override_is_refused_before_any_action(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
    env_name: str,
    bad_url: str,
) -> None:
    touched: list[str] = []
    monkeypatch.setattr(
        "hf_mcp.auth.webbrowser.open", lambda url: touched.append("browser")
    )
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda **_: touched.append("callback") or {},
    )
    monkeypatch.setattr(
        "hf_mcp.auth.urllib.request.urlopen",
        lambda *a, **k: touched.append("network"),
    )
    announced: list[str] = []
    caplog.set_level(logging.DEBUG)
    with pytest.raises(HFAPIError) as caught:
        authorize_via_loopback(
            _settings(
                runtime_env={
                    "HF_MCP_CLIENT_ID": "client",
                    "HF_MCP_CLIENT_SECRET": MARKER,
                    "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
                    env_name: bad_url,
                }
            ),
            open_browser=True,
            announce_authorize_url=announced.append,
        )
    err = caught.value
    assert err.error["code"] == "INVALID_ARGUMENT"
    assert touched == [] and announced == []
    assert "evil.test" not in str(err) and "evil.test" not in repr(err.error)
    assert MARKER not in str(err) and MARKER not in repr(err.error)
    assert err.__cause__ is None
    captured = capsys.readouterr()
    assert MARKER not in captured.err + captured.out + caplog.text


@pytest.mark.parametrize("env_name", ["HF_MCP_TOKEN_URL", "HF_MCP_AUTHORIZE_URL"])
def test_https_endpoint_override_still_works(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "s")
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda **_: {"code": "abc", "state": "s"},
    )
    seen: dict[str, str] = {}

    def _exchange_ok(**kwargs: str) -> dict[str, object]:
        seen.update(kwargs)
        return {"access_token": "token", "token_type": "Bearer"}

    monkeypatch.setattr("hf_mcp.auth._exchange_code_for_token", _exchange_ok)
    announced: list[str] = []
    bundle = authorize_via_loopback(
        _settings(
            runtime_env={
                "HF_MCP_CLIENT_ID": "client",
                "HF_MCP_CLIENT_SECRET": "secret",
                "HF_MCP_REDIRECT_URI": "http://127.0.0.1:8765/callback",
                env_name: "https://other.test/oauth",
            }
        ),
        open_browser=False,
        announce_authorize_url=announced.append,
    )
    assert bundle.access_token == "token"
    if env_name == "HF_MCP_TOKEN_URL":
        assert seen["token_url"] == "https://other.test/oauth"
    else:
        assert announced[0].startswith("https://other.test/oauth?")


def test_exchange_http_status_is_recorded_without_provider_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _urlopen(request: object, timeout: int) -> _Resp:
        raise _http_error(429)

    monkeypatch.setattr("hf_mcp.auth.urllib.request.urlopen", _urlopen)
    with pytest.raises(HFAPIError) as caught:
        _exchange()
    assert caught.value.error["http_status"] == 429
    assert MARKER not in str(caught.value)
