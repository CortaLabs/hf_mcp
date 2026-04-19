from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PRODUCT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

import hf_mcp.auth as auth_module
from hf_mcp.auth import authorize_via_loopback
from hf_mcp.cli import main
from hf_mcp.config import HFMCPSettings
from hf_mcp.normalizers import normalize_response
from hf_mcp.token_store import TokenBundle, load_token_store
from hf_mcp.transport import HFTransport


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


def test_authorize_via_loopback_rejects_state_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr("hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test")
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda redirect_uri, timeout_seconds: {"code": "abc", "state": "wrong-state"},
    )
    monkeypatch.setattr(
        "hf_mcp.auth._exchange_code_for_token",
        lambda **_: {"access_token": "token", "token_type": "Bearer", "scope": "Basic Info"},
    )

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


def test_authorize_via_loopback_rejects_missing_authorization_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr("hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test")
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda redirect_uri, timeout_seconds: {"state": "expected-state"},
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


def test_authorize_via_loopback_successful_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr("hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test/authorize")
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda redirect_uri, timeout_seconds: {"code": "abc", "state": "expected-state"},
    )

    exchange_inputs: dict[str, str] = {}

    def _fake_exchange(**kwargs: str) -> dict[str, object]:
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

    assert bundle.access_token == "token"
    assert bundle.token_type == "Bearer"
    assert exchange_inputs["client_id"] == "client"
    assert exchange_inputs["client_secret"] == "secret"
    assert exchange_inputs["code"] == "abc"
    assert "redirect_uri" not in exchange_inputs


def test_exchange_code_for_token_uses_documented_form_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        def read(self) -> bytes:
            return b'{\"access_token\":\"token\",\"token_type\":\"Bearer\",\"scope\":\"Basic Info\"}'

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
    form_fields = urllib.parse.parse_qs(body_bytes.decode("utf-8"), keep_blank_values=True)
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


def test_authorize_via_loopback_announces_authorization_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hf_mcp.auth.secrets.token_urlsafe", lambda _: "expected-state")
    monkeypatch.setattr("hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test/authorize")
    monkeypatch.setattr(
        "hf_mcp.auth._await_loopback_callback",
        lambda redirect_uri, timeout_seconds: {"code": "abc", "state": "expected-state"},
    )
    monkeypatch.setattr(
        "hf_mcp.auth._exchange_code_for_token",
        lambda **_: {"access_token": "token", "token_type": "Bearer", "scope": "Basic Info"},
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

    def _fake_await_loopback_callback(redirect_uri: str, timeout_seconds: int) -> dict[str, str]:
        callback_inputs["redirect_uri"] = redirect_uri
        callback_inputs["timeout_seconds"] = timeout_seconds
        return {"code": "abc", "state": "expected-state"}

    def _fake_exchange(**kwargs: str) -> dict[str, object]:
        exchange_inputs.update(kwargs)
        return {"access_token": "token", "token_type": "Bearer", "scope": "Basic Info"}

    monkeypatch.setattr("hf_mcp.auth._build_authorize_url", _fake_build_authorize_url)
    monkeypatch.setattr("hf_mcp.auth._await_loopback_callback", _fake_await_loopback_callback)
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
    monkeypatch.setattr("hf_mcp.auth._build_authorize_url", lambda **_: "https://example.test/authorize")

    callback_inputs: dict[str, object] = {}
    exchange_called = False

    def _fake_await_loopback_callback(redirect_uri: str, timeout_seconds: int) -> dict[str, str]:
        callback_inputs["redirect_uri"] = redirect_uri
        callback_inputs["timeout_seconds"] = timeout_seconds
        return {"code": "abc", "state": "wrong-state"}

    def _should_not_exchange(**kwargs: str) -> dict[str, object]:
        nonlocal exchange_called
        del kwargs
        exchange_called = True
        raise AssertionError("token exchange should not run after callback state mismatch")

    monkeypatch.setattr("hf_mcp.auth._await_loopback_callback", _fake_await_loopback_callback)
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
        raise AssertionError("callback listener should not start for invalid hosted config")

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

    def _fake_load_settings(config_path: Path | None, env: dict[str, str] | None = None) -> HFMCPSettings:
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
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset({"posts.read"}))

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
    assert out.out.index("Authorization URL: https://example.test/authorize") < out.out.index("Token saved: yes")
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

    monkeypatch.setattr("hf_mcp.cli.load_settings", lambda config_path, env=None: settings)
    monkeypatch.setattr("hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(token_path))
    monkeypatch.setattr("hf_mcp.cli._is_wsl_environment", lambda: True)

    def _fake_authorize(
        settings: HFMCPSettings,
        open_browser: bool = True,
        announce_authorize_url: Any | None = None,
    ) -> TokenBundle:
        del settings, announce_authorize_url
        captured["open_browser"] = open_browser
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset({"posts.read"}))

    monkeypatch.setattr("hf_mcp.cli.authorize_via_loopback", _fake_authorize)

    exit_code = main(["auth", "bootstrap", "--config", str(config_path), "--token-path", str(token_path)])
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

    monkeypatch.setattr("hf_mcp.cli.load_settings", lambda config_path, env=None: settings)
    monkeypatch.setattr("hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(token_path))
    monkeypatch.setattr("hf_mcp.cli._is_wsl_environment", lambda: True)

    def _fake_authorize(
        settings: HFMCPSettings,
        open_browser: bool = True,
        announce_authorize_url: Any | None = None,
    ) -> TokenBundle:
        del settings, announce_authorize_url
        captured["open_browser"] = open_browser
        return TokenBundle(access_token="token", token_type="Bearer", scope=frozenset({"posts.read"}))

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
            raise AssertionError("save_bundle should not be called when bootstrap fails")

    monkeypatch.setattr("hf_mcp.cli.load_settings", lambda config_path, env=None: settings)
    monkeypatch.setattr("hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(settings.token_path))
    monkeypatch.setattr(
        "hf_mcp.cli.authorize_via_loopback",
        lambda settings, open_browser=True, announce_authorize_url=None: (_ for _ in ()).throw(
            ValueError("Missing required environment variable: HF_MCP_CLIENT_ID")
        ),
    )

    exit_code = main(["auth", "bootstrap"])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "Auth bootstrap failed: Missing required environment variable: HF_MCP_CLIENT_ID" in err


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

    monkeypatch.setattr("hf_mcp.cli.load_settings", lambda config_path, env=None: settings)
    monkeypatch.setattr("hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(token_path))

    called = {"authorize": False}

    def _should_not_authorize(settings: HFMCPSettings, open_browser: bool = True) -> TokenBundle:
        del settings, open_browser
        called["authorize"] = True
        raise AssertionError("status must not call authorize_via_loopback")

    monkeypatch.setattr("hf_mcp.cli.authorize_via_loopback", _should_not_authorize)

    exit_code = main(["auth", "status", "--config", str(config_path), "--token-path", str(token_path)])
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
            raise PermissionError("Token file permissions are too broad. Expected owner-only access (0600).")

    monkeypatch.setattr("hf_mcp.cli.load_settings", lambda config_path, env=None: settings)
    monkeypatch.setattr("hf_mcp.cli.load_token_store", lambda _: _StubTokenStore(settings.token_path))

    exit_code = main(["auth", "status"])
    err = capsys.readouterr().err

    assert exit_code == 2
    assert "Auth status failed: Token file permissions are too broad." in err


def test_load_token_store_rejects_repo_relative_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_MCP_TOKEN_PATH", "products/hf_mcp/token.json")
    with pytest.raises(ValueError, match="absolute path"):
        load_token_store(_settings())


def test_transport_read_builds_helper_route_and_caps_perpage(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubTokenStore:
        def require_bundle(self) -> TokenBundle:
            return TokenBundle(access_token="abc123", token_type="Bearer", scope=frozenset())

    captured: dict[str, Any] = {}

    def _fake_post_json(self: HFTransport, route: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"posts": {"pid": 42, "subject": "Hello"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = transport.read(
        asks={"posts": {"_uid": [5], "_perpage": 99, "pid": True}},
        helper="posts",
    )

    assert captured["route"] == "/read/posts"
    assert captured["payload"]["asks"]["posts"]["_perpage"] == 30
    assert captured["headers"]["Authorization"] == "Bearer abc123"
    assert captured["headers"]["User-Agent"] == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
    assert result["posts"] == [{"pid": "42", "subject": "Hello"}]


def test_transport_write_builds_helper_route_and_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubTokenStore:
        def require_bundle(self) -> TokenBundle:
            return TokenBundle(access_token="abc123", token_type="Bearer", scope=frozenset())

    captured: dict[str, Any] = {}

    def _fake_post_json(self: HFTransport, route: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        captured["route"] = route
        captured["payload"] = payload
        captured["headers"] = headers
        return {"posts": {"pid": 9001, "subject": "Created"}}

    monkeypatch.setattr(HFTransport, "_post_json", _fake_post_json)

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    result = transport.write(
        asks={"posts": {"_tid": 123, "_message": "Hello"}},
        helper="posts/create",
    )

    assert captured["route"] == "/write/posts/create"
    assert captured["payload"] == {"asks": {"posts": {"_tid": 123, "_message": "Hello"}}}
    assert captured["headers"]["Authorization"] == "Bearer abc123"
    assert captured["headers"]["User-Agent"] == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    )
    assert result["posts"] == [{"pid": "9001", "subject": "Created"}]


def test_transport_rejects_helper_operation_prefix() -> None:
    class _StubTokenStore:
        def require_bundle(self) -> TokenBundle:
            return TokenBundle(access_token="abc123", token_type="Bearer", scope=frozenset())

    transport = HFTransport(token_store=_StubTokenStore(), base_url="https://example.test")
    with pytest.raises(ValueError, match="operation prefix"):
        transport.read(asks={"posts": {"pid": True}}, helper="write/posts")


def test_normalize_response_handles_dict_list_and_absent_advanced_fields() -> None:
    payload = {
        "me": {"uid": 5, "username": "forge"},
        "posts": {"pid": 7, "subject": "Test"},
        "bytes": [{"id": 3, "amount": "430.43"}],
    }

    normalized = normalize_response(payload)

    assert normalized["me"] == [{"uid": "5", "username": "forge"}]
    assert "unreadpms" not in normalized["me"][0]
    assert normalized["posts"] == [{"pid": "7", "subject": "Test"}]
    assert normalized["bytes"] == [{"id": "3", "amount": "430.43"}]
